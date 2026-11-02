"""Recherche multi-moteurs de sources .onion (adapté de apurvsinghgautam/robin).

⚠️ Outil de DÉCOUVERTE de sources, pas un collecteur : il interroge une
quinzaine de moteurs de recherche .onion pour proposer de NOUVELLES adresses,
il ne crée ni source ni document. Lecture seule, via Tor.

Durcissements portés de l'amont le 2026-09-30 (voir `engines.py`) :
- filtre de contenu pédocriminel (`_ABUSE_MATERIAL`) : les moteurs .onion
  indexent ce contenu ; un titre qui matche est écarté avant tout affichage,
  et jamais journalisé. Impératif éthique/légal, cohérent avec la
  désactivation de DOXBYTE (règles 1-2) ;
- plafond de lecture (2 Mo) : un moteur hostile peut renvoyer une réponse
  énorme (même durcissement que link_health.py) ;
- limite par hôte : un annuaire qui noie les résultats ne compte que 3 fois ;
- timeout (connexion, lecture) séparé.
"""

import logging
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.pipeline.collect.robin.engines import SEARCH_ENGINES
from app.pipeline.collect.tor import build_socks5_proxy_url
from app.pipeline.collect.useragents import pick_user_agent

logger = logging.getLogger(__name__)

_ONION_LINK_RE = re.compile(r"https?://[a-z0-9]+\.onion[^\s\"']*")
_WORD_RE = re.compile(r"\w+")
_MIN_KEYWORD_LEN = 3

# (connexion, lecture) : un moteur lent peut prendre la quasi-totalité des
# 30 s pour se connecter ; celui qui n'a pas répondu à 40 s ne répondra pas.
_ENGINE_TIMEOUT = (30, 40)
# Un moteur .onion hostile peut renvoyer une réponse volumineuse : on ne lit
# jamais plus que ça, comme link_health.py.
_SEARCH_PAGE_MAX_BYTES = 2 * 1024 * 1024
# Un même annuaire renvoie parfois des dizaines de liens : on en garde au plus
# quelques-uns pour ne pas laisser un seul hôte noyer les autres.
_MAX_RESULTS_PER_HOST = 3

# ⚠️ Filtre de matériel pédocriminel, porté verbatim de l'amont. Les moteurs
# .onion indexent ce contenu ; un résultat dont le titre OU le lien y
# correspond est écarté avant tout affichage, et n'est jamais journalisé (on
# ne compte que le NOMBRE d'écartés). Frontière non négociable (règles 1-2),
# même posture que la désactivation de DOXBYTE.
_ABUSE_MATERIAL = re.compile(
    r"child\W{0,3}(?:porn|sex|rape|nud)"
    r"|(?:rape|porn|sex)\W{0,3}child"
    r"|\bpedo(?:phil\w*|s)?\b"
    r"|\bpthc\b|\bjailbait\b|\bpreteens?\b|\blolitas?\b|\bhurtcore\b"
    r"|\bkidflix|\bonly\W{0,3}kids"
    r"|\bkid(?:s|dy|die)?\W{0,3}(?:porn|sex|nud)"
    r"|\bunderage\W{0,3}(?:porn|sex|nud|girls?|boys?)"
    r"|\bcp\W{0,3}(?:porn|videos?|links?|archive|collection)\b"
    r"|\bcsam\b",
    re.IGNORECASE,
)


def _query_keywords(query: str) -> set[str]:
    return {w for w in _WORD_RE.findall(query.lower()) if len(w) >= _MIN_KEYWORD_LEN}


def _title_matches_query(title: str, query_keywords: set[str]) -> bool:
    """Beaucoup de moteurs onion renvoient, faute de vrais résultats, leur propre
    page d'accueil/annuaire (catégories génériques, liens "featured") identique
    quelle que soit la requête. On ne garde un résultat que si son titre partage
    au moins un mot avec la requête d'origine — un vrai résultat de recherche en
    contient presque toujours, un lien de navigation générique jamais."""
    if not query_keywords:
        return True
    title_words = set(_WORD_RE.findall(title.lower()))
    return bool(query_keywords & title_words)


def is_abuse_material(result: dict) -> bool:
    """Le titre ou le lien d'un résultat correspond-il à un indicateur de
    contenu pédocriminel ? Écarté avant tout affichage (voir `_ABUSE_MATERIAL`)."""
    return bool(
        _ABUSE_MATERIAL.search(result.get("title", ""))
        or _ABUSE_MATERIAL.search(result.get("link", ""))
    )


def _build_search_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        read=3,
        connect=3,
        backoff_factor=0.5,
        status_forcelist=[500, 502, 503, 504],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    # `resolve_via_proxy=True` : `requests` ne sait pas résoudre les .onion
    # lui-même, il faut que Tor fasse la résolution (schéma socks5h).
    proxy_url = build_socks5_proxy_url(resolve_via_proxy=True)
    session.proxies = {"http": proxy_url, "https": proxy_url}
    return session


def _read_capped(response: requests.Response) -> str:
    """Lit au plus `_SEARCH_PAGE_MAX_BYTES` du corps puis s'arrête. `stream=True`
    permet de ne PAS rapatrier une réponse énorme d'un moteur hostile."""
    chunks = bytearray()
    for chunk in response.iter_content(chunk_size=8192):
        chunks.extend(chunk)
        if len(chunks) >= _SEARCH_PAGE_MAX_BYTES:
            break
    return bytes(chunks).decode("utf-8", errors="replace")


def _fetch_engine_results(
    engine: dict, search_query: str, query_keywords: set[str]
) -> list[dict]:
    url = engine["url"].format(query=search_query)
    # Netloc du moteur lui-même : sert à écarter ses propres liens de navigation
    # (about, contact, annonces sponsorisées...) qui apparaissent sur CHAQUE page
    # de résultats indépendamment de la requête et n'ont donc rien à voir avec elle.
    own_netloc = urlparse(engine["url"]).netloc
    headers = {"User-Agent": pick_user_agent()}

    try:
        session = _build_search_session()
        response = session.get(
            url, headers=headers, timeout=_ENGINE_TIMEOUT, stream=True
        )
        if response.status_code != 200:
            return []

        soup = BeautifulSoup(_read_capped(response), "html.parser")
        links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            title = a.get_text(strip=True)
            match = _ONION_LINK_RE.search(href)
            if not match or len(title) <= 3:
                continue
            result_link = match.group(0)
            if urlparse(result_link).netloc == own_netloc:
                continue
            if not _title_matches_query(title, query_keywords):
                continue
            candidate = {
                "title": title,
                "link": result_link,
                "engine": engine["name"],
            }
            # Écarté au plus tôt : un titre pédocriminel ne doit jamais
            # atteindre la déduplication ni l'affichage.
            if is_abuse_material(candidate):
                continue
            links.append(candidate)
        return links
    except Exception:
        logger.warning(
            "Moteur %s injoignable pour la requête %r",
            engine["name"],
            search_query,
            exc_info=True,
        )
        return []


def search_all_engines(
    search_query: str, original_query: str, max_workers: int = 5
) -> list[dict]:
    """Interroge les moteurs de recherche onion en parallèle (via Tor) et retourne
    une liste dédupliquée de `{title, link, engine}`. Usage à la demande (section
    Recherche) — ne touche jamais aux sources déjà enregistrées, ne fait que
    proposer des candidats.

    `search_query` (reformulée par le LLM) sert à interroger les moteurs ;
    `original_query` (telle que tapée par l'analyste, mots garantis bien séparés)
    sert à juger la pertinence des résultats — insensible aux fantaisies de la
    reformulation (mots fusionnés/ajoutés)."""
    query_keywords = _query_keywords(original_query)
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(_fetch_engine_results, engine, search_query, query_keywords)
            for engine in SEARCH_ENGINES
        ]
        for future in as_completed(futures):
            results.extend(future.result())

    seen_links: set[str] = set()
    par_hote: Counter[str] = Counter()
    unique_results: list[dict] = []
    for res in results:
        # Filet de sécurité : le filtre est déjà appliqué au fetch, on le
        # rejoue ici pour que rien ne dépende d'un seul point de passage.
        if is_abuse_material(res):
            continue
        clean_link = res["link"].rstrip("/")
        if clean_link in seen_links:
            continue
        hote = urlparse(clean_link).netloc
        if par_hote[hote] >= _MAX_RESULTS_PER_HOST:
            continue
        seen_links.add(clean_link)
        par_hote[hote] += 1
        unique_results.append(res)

    return unique_results
