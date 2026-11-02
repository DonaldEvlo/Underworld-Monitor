"""Collecte des fils recents de subdreads cibles sur Dread (forum .onion).

Complete `search.py` (recherche par mots-cles a la demande, resultats en Redis
sans persistance) : ce module-ci est un vrai collecteur, il produit des
`RawDocumentContract` persistes qui passent par la detection.

Perimetre volontairement borne (CONTRIBUTING.md regle 1 : observation, pas crawl) :
- **subdreads cibles** plutot que tout le forum. Mesure du 2026-08-19 sur la
  recherche : le signal se concentre sur /d/DataBrokers, /d/hacking et
  /d/leaks ; le reste du forum (/d/Drugs, /d/Reviews...) est hors sujet.
- **fraicheur incrementale**, pas crawl historique complet -- meme regime que
  mybb_latest/exilio404/doxbyte (voir `DEFAULT_MAX_PAGES`).
- **budget de corps borne** (`DEFAULT_MAX_BODIES`) : a ~34 s par corps mesures,
  un cycle non borne depasserait `task_time_limit` (35 min) et serait rejoue en
  boucle par Celery sans jamais aboutir.

Deux contraintes specifiques a Dread, mesurees le 2026-08-19 :

1. **Anti-bot ("DDOS Protection")**. Il s'active quand on enchaine trop de
   requetes rapprochees -- constate en direct en sondant /d/leaks plusieurs
   fois de suite. On ne tente JAMAIS de le resoudre : on detecte la page, on
   log et on s'arrete proprement pour ce subdread. `polite_delay()` (3-9 s)
   entre chaque requete est la contrepartie qui rend la collecte tenable.

2. **Playwright renvoie des echecs transitoires** ("Page.content: Unable to
   retrieve content because the page is navigating"). `_fetch_search_html`
   (search.py) leve desormais `_TransientFetchError` dans ce cas pour que le
   retry de tenacity s'applique -- voir le correctif du 2026-08-19."""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.pipeline.collect.dread.search import (
    _fetch_search_html,
    is_ddos_protection_page,
)
from app.pipeline.collect.politeness import polite_delay
from app.pipeline.collect.tor import renew_circuit

logger = logging.getLogger(__name__)

# Plafond dur : garde-fou contre une boucle de pagination qui ne terminerait
# pas (subdread tres actif, lien "next" toujours present).
_MAX_PAGES_SAFETY_CAP = 50

# Fraicheur incrementale par cycle, pas rattrapage historique : 1 page = 20
# fils par subdread, au-dela du volume publie entre deux cycles sur ce forum.
DEFAULT_MAX_PAGES = 1

# Plafond de fils dont on va chercher le CORPS, par cycle (tous subdreads
# confondus). Le plafond existe pour que la tache tienne dans ses limites
# Celery (`dread_tasks`: 75 min souple / 85 min dur) : sans lui, une tache
# depassant la limite serait tuee puis REJOUEE en boucle sans jamais aboutir
# (CONTRIBUTING.md §8).
#
# Passe de 40 a 100 le 2026-08-20, apres la parallelisation des corps
# (BODY_FETCH_WORKERS). Mesure du cycle reel qui a suivi : 923 s au total dont
# ~5 min de listings, soit **~15 s par corps** contre ~34 s en sequentiel.
#   - nominal : 100 x 15 s + 5 min = ~30 min
#   - degrade : ce meme cycle a subi 25 % de rendus partiels (10/40) sans
#     deborder, donc ~40-45 min dans le pire cas observe
# Les deux restent nettement sous les 75 min souples. Ne PAS monter davantage
# sans remesurer : au-dela on augmente le trafic vers une source unique, ce que
# l'OPSEC (CONTRIBUTING.md §2.3) demande de garder discret.
DEFAULT_MAX_BODIES = 100

# Recuperation des corps en parallele. Mesure du 2026-08-20 (deux subdreads
# reels) : sequentiel 32 s/fil, 5 workers 14-16 s/fil et 22/22 corps recuperes
# -- plus rapide ET plus fiable. Aligne sur DREAD_SEARCH_MAX_WORKERS
# (api/routers/dread.py) : meme site, meme cout memoire par navigateur
# Playwright. Ne PAS monter sans remesurer : au-dela, on se rapproche du
# martelage que le delai de politesse cherche a eviter (CONTRIBUTING.md §2.3).
BODY_FETCH_WORKERS = 5

# Subdreads collectes par defaut. Choisis sur la mesure du 2026-08-19 (top
# subdreads des resultats de recherche : DataBrokers 41, hacking 40, leaks 27,
# fraudship 8, hackingNoobs 7) -- pas sur une intuition. A completer si un
# nouveau subdread pertinent apparait dans les resultats de `search.py`.
DEFAULT_SUBDREADS = (
    "leaks",
    "DataBrokers",
    "hacking",
    "Fraud",
    "fraudship",
    "hackingNoobs",
    "darknet",
    "onions",
)

# Dread date ses fils dans l'attribut `title` d'un span, au format
# "24th January, 2026 - 02:13" (jour AVANT mois) — verifie sur /d/leaks le
# 2026-08-19. Le texte visible est relatif ("6 months ago") et inutilisable.
# La variante mois-avant-jour est acceptee aussi : la page de recherche
# (search.py) affiche "August 1st, 2026".
_MONTH_NAMES = (
    "January|February|March|April|May|June|July|August|September|"
    "October|November|December"
)
_DATE_DAY_FIRST_RE = re.compile(
    rf"(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\s+(?P<month>{_MONTH_NAMES}),?\s*(?P<year>\d{{4}})",
    re.IGNORECASE,
)
_DATE_MONTH_FIRST_RE = re.compile(
    rf"(?P<month>{_MONTH_NAMES})\s+(?P<day>\d{{1,2}})(?:st|nd|rd|th)?,\s*(?P<year>\d{{4}})",
    re.IGNORECASE,
)

# Valeurs de `title` qui ne sont PAS une date de publication : elles
# cohabitent avec elle dans le meme item (constate sur /d/leaks).
_NON_DATE_TITLE_MARKERS = ("edited", "sticky", "archived", "joined")
_MONTHS = {
    m.lower(): i
    for i, m in enumerate(
        [
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ],
        start=1,
    )
}


@dataclass(frozen=True)
class DreadThread:
    """Un fil de subdread. `body` est le corps du premier post (None si non
    recupere ou echec) -- c'est la ou se trouvent domaines/emails/volumes, le
    titre seul ne donne quasiment rien a detecter."""

    title: str
    thread_url: str
    subdread: str | None = None
    author: str | None = None
    published_at: datetime | None = None
    comment_count: int | None = None
    body: str | None = None


def parse_thread_date(text: str) -> datetime | None:
    """Extrait une date de publication d'un libelle Dread.

    Renvoie None si aucune date reconnaissable -- Dread affiche aussi des
    formes relatives ("3 hours ago") qu'on ne cherche pas a interpreter : une
    date absente vaut mieux qu'une date fausse (le document reste collecte,
    `published_at` est simplement nul)."""
    match = _DATE_DAY_FIRST_RE.search(text or "") or _DATE_MONTH_FIRST_RE.search(
        text or ""
    )
    if match is None:
        return None
    month = _MONTHS.get(match.group("month").lower())
    if month is None:
        return None
    try:
        return datetime(
            int(match.group("year")),
            month,
            int(match.group("day")),
            tzinfo=timezone.utc,
        )
    except ValueError:
        return None


def _clean_title(raw: str) -> str:
    """Nettoie le titre d'un item de listing.

    Dread colle au libelle du lien des suffixes d'interface ("Crosspost",
    "Download", "★Announcement") sans separateur -- constate sur /d/leaks. On
    coupe sur ces marqueurs connus plutot que de deviner, et on normalise les
    espaces."""
    title = re.sub(r"\s+", " ", raw or "").strip()
    # Suffixes releves sur /d/leaks le 2026-08-19 : "…Download", "…Offer",
    # "…Request", "…Crosspost", "…★Announcement". Boucle (et non un seul
    # passage) car ils se cumulent ("…★AnnouncementSticky").
    markers = (
        "★Announcement",
        "Announcement",
        "Crosspost",
        "Download",
        "Request",
        "Offer",
        "Sticky",
        "Archived",
    )
    changed = True
    while changed:
        changed = False
        for marker in markers:
            if title.endswith(marker) and len(title) > len(marker):
                title = title[: -len(marker)].strip()
                changed = True
    return title


def _strip_subdread_prefix(label: str) -> str:
    """Retire le prefixe "/d/" d'un libelle de subdread.

    `removeprefix` et NON `lstrip("/d/")` : lstrip retire tous les caracteres
    de l'ensemble {'/', 'd'} en tete, donc "/d/darknet" devenait "arknet" et
    "/d/DataBrokers" survivait par hasard (majuscule). Bug constate en base le
    2026-08-20 sur une collecte reelle."""
    return (label or "").removeprefix("/d/").removeprefix("d/")


def _parse_listing_item(item, base_url: str) -> DreadThread | None:
    link = item.select_one("a.title[href^='/post/'], .postTop a[href^='/post/']")
    if link is None:
        return None

    title = _clean_title(link.get_text(strip=True))
    if not title:
        return None

    # `.author_link` d'abord : un item contient aussi une carte de profil au
    # survol avec d'autres liens /u/, dont la date d'inscription de l'auteur --
    # a ne surtout pas confondre avec la date du post.
    author_el = item.select_one("a.author_link[href^='/u/']") or item.select_one(
        "a[href^='/u/']"
    )
    subdread_el = item.select_one(
        ".crosspost-heading a[href^='/d/']"
    ) or item.select_one("a[href^='/d/']")

    comment_count = None
    comments_el = item.find(string=re.compile(r"\d+\s+comments?"))
    if comments_el:
        found = re.search(r"(\d+)", comments_el)
        if found:
            comment_count = int(found.group(1))

    return DreadThread(
        title=title,
        thread_url=urljoin(base_url, link["href"]),
        subdread=(
            _strip_subdread_prefix(subdread_el.get_text(strip=True))
            if subdread_el
            else None
        ),
        author=author_el.get_text(strip=True) if author_el else None,
        published_at=_extract_published_at(item),
        comment_count=comment_count,
    )


def _extract_published_at(item) -> datetime | None:
    """Date de publication du fil.

    Elle vit dans l'attribut `title` d'un span ("24th January, 2026 - 02:13"),
    le texte visible etant relatif. Deux pieges verifies sur /d/leaks :
    - la carte de profil au survol (`.dataCard`) porte la date d'INSCRIPTION de
      l'auteur — la prendre daterait tous les fils de la meme date ;
    - d'autres span[title] cohabitent ("Edited ...", "Sticky", "Archived")."""
    for span in item.select("span[title]"):
        if span.find_parent(class_="dataCard") is not None:
            continue
        title_attr = span.get("title") or ""
        if any(marker in title_attr.lower() for marker in _NON_DATE_TITLE_MARKERS):
            continue
        parsed = parse_thread_date(title_attr)
        if parsed is not None:
            return parsed
    return None


def parse_subdread_listing(html: str, base_url: str) -> list[DreadThread]:
    """Extrait les fils d'une page de listing de subdread (`.postBoard .item`,
    meme conteneur que la page de recherche)."""
    soup = BeautifulSoup(html, "html.parser")
    board = soup.select_one(".postBoard")
    if board is None:
        return []

    threads = []
    for item in board.select(".item"):
        parsed = _parse_listing_item(item, base_url)
        if parsed is not None:
            threads.append(parsed)
    return threads


def parse_thread_body(html: str) -> str | None:
    """Extrait le corps du premier post d'un fil.

    Volontairement limite au post initial, pas aux commentaires : c'est
    l'annonce qui porte le signal (domaine victime, volume, echantillon), les
    commentaires sont majoritairement du bavardage. Meme choix que
    exilio404 (question sans les reponses) et mybb_latest (premier message).

    Le post initial vit dans le premier `.item` de la page (meme conteneur que
    les listings) ; les commentaires sont dans des `.commentBody` distincts,
    qu'on exclut. La carte de profil au survol (`.dataCard`) est retiree : elle
    injecterait le score et la date d'inscription de l'auteur dans le texte."""
    soup = BeautifulSoup(html, "html.parser")

    item = soup.select_one(".postBoard .item") or soup.select_one(".item")
    if item is not None:
        for noise in item.select(".dataCard, .commentBody, .comment, .voting, form"):
            noise.decompose()
        text = item.get_text(" ", strip=True)
        if text:
            return text

    # Repli sur les selecteurs historiques au cas ou le markup varie selon le
    # type de fil (annonce epinglee, crosspost...).
    content = soup.select_one(".postContent, .post-content, .postMain .content")
    if content is None:
        return None
    return content.get_text(" ", strip=True) or None


def _is_partial_render(html: str) -> bool:
    """Vrai si la page a ete capturee avant l'injection JS de son contenu.

    Mesure du 2026-08-19 : trois appels successifs sur la MEME URL ont renvoye
    89 572 o (complet), 1081 o (coquille vide) puis une page anti-bot.
    Playwright rend la main avant que Dread ait fini de peupler le DOM.
    Sans ce garde-fou, on enregistrait une page vide comme un fait acquis
    (constate : 2 corps vides sur 3 fils) alors qu'un simple reessai suffit.

    Une page anti-bot n'est PAS un rendu partiel : elle est complete et doit
    etre traitee a part (on ne la rejoue pas, on abandonne le subdread)."""
    if is_ddos_protection_page(html):
        return False
    return "postBoard" not in html and "commentBody" not in html


def _fetch_rendered(url: str, attempts: int = 3) -> str | None:
    """Recupere une page en re-essayant tant qu'elle revient partiellement
    rendue.

    `_fetch_search_html` gere deja les echecs *durs* (exception Playwright)
    via tenacity, mais un rendu partiel est un SUCCES de son point de vue : il
    renvoie une chaine valide, simplement vide de contenu. Mesure du
    2026-08-19 : 1 tentative sur 3 seulement etait exploitable sur /d/leaks —
    sans ce re-essai, deux collectes sur trois repartaient les mains vides et
    `collect_source` concluait a tort « source injoignable ou vide ».

    Renvoie la page anti-bot telle quelle (l'appelant doit la reconnaitre et
    abandonner proprement), ou None si toutes les tentatives ont echoue."""
    for attempt in range(1, attempts + 1):
        try:
            html = _fetch_search_html(url)
        except Exception:
            logger.exception("Dread: echec recuperation %s (essai %d)", url, attempt)
            return None

        if not html:
            return None
        if is_ddos_protection_page(html):
            return html
        if not _is_partial_render(html):
            return html

        logger.info(
            "Dread: rendu partiel sur %s (%d o, essai %d/%d), nouvelle tentative",
            url,
            len(html),
            attempt,
            attempts,
        )

    logger.warning(
        "Dread: %s toujours partiellement rendue apres %d tentatives", url, attempts
    )
    return None


def fetch_thread_body(thread_url: str) -> str | None:
    html = _fetch_rendered(thread_url)
    if not html or is_ddos_protection_page(html):
        return None
    return parse_thread_body(html)


def build_subdread_url(base_url: str, subdread: str, page: int) -> str:
    """URL de listing d'un subdread. Page 1 = URL nue, suivantes en `?p=N`
    (pagination reelle observee sur /d/leaks)."""
    url = urljoin(base_url, f"/d/{subdread}")
    return url if page <= 1 else f"{url}?p={page}"


def _retry_after_new_circuit(page_url: str) -> str | None:
    """Renouvelle le circuit Tor puis retente UNE fois la page.

    L'anti-bot de Dread est **aleatoire, pas structurel** : mesure sur deux
    cycles reels (2026-08-19 et 2026-08-20), /d/leaks et /d/hacking ont rendu
    0 fil le premier jour et 20 fils chacun le lendemain, a position identique
    dans la liste. L'hypothese « ils sont en tete donc ils encaissent » etait
    donc fausse -- c'est l'IP de sortie qui compte, pas l'ordre.

    Un NEWNYM change l'adresse de sortie, ce qui suffit generalement a passer.
    UNE seule tentative, precedee du delai de politesse habituel : au-dela on
    martelerait un site qui vient explicitement de nous freiner, ce que
    l'OPSEC (CONTRIBUTING.md §2.3) interdit. Si ca echoue encore, on abandonne le
    subdread pour ce cycle -- le prochain repartira sur un autre circuit."""
    logger.info("Dread: anti-bot sur %s, renouvellement du circuit Tor", page_url)
    try:
        renew_circuit()
    except Exception:
        logger.warning(
            "Dread: renouvellement de circuit impossible, abandon de %s", page_url
        )
        return None

    polite_delay()
    return _fetch_rendered(page_url)


def fetch_subdread_threads(
    base_url: str,
    subdread: str,
    max_pages: int | None = DEFAULT_MAX_PAGES,
    *,
    fetch_bodies: bool = True,
) -> list[DreadThread]:
    """Parcourt les pages de listing d'un subdread jusqu'a `max_pages`, une
    page vide, ou l'anti-bot. Si `fetch_bodies=True`, recupere aussi le corps
    du premier post de chaque fil (+1 requete par fil).

    Ne leve jamais : un subdread en echec ne doit pas interrompre les autres.
    """
    threads: list[DreadThread] = []
    seen_urls: set[str] = set()
    page = 0

    while True:
        page += 1
        if max_pages is not None and page > max_pages:
            break
        if page > _MAX_PAGES_SAFETY_CAP:
            logger.warning(
                "Dread: plafond de securite (%d pages) atteint sur /d/%s",
                _MAX_PAGES_SAFETY_CAP,
                subdread,
            )
            break

        page_url = build_subdread_url(base_url, subdread, page)
        html = _fetch_rendered(page_url)
        if not html:
            break

        if is_ddos_protection_page(html):
            html = _retry_after_new_circuit(page_url)
        if not html or is_ddos_protection_page(html):
            logger.warning(
                "Dread: page anti-bot persistante sur %s, subdread abandonne "
                "pour ce cycle",
                page_url,
            )
            break

        page_threads = parse_subdread_listing(html, base_url)
        if not page_threads:
            break

        new_threads = [t for t in page_threads if t.thread_url not in seen_urls]
        if not new_threads:
            # Meme page reservie (pagination qui boucle) : inutile d'insister.
            break
        seen_urls.update(t.thread_url for t in new_threads)
        threads.extend(new_threads)

    if not fetch_bodies:
        return threads
    return _with_bodies(threads)


def _with_bodies(
    threads: list[DreadThread], budget: int | None = None
) -> list[DreadThread]:
    """Recupere le corps du 1er post de chaque fil, dans la limite de `budget`
    fils (None = pas de limite).

    Les fils au-dela du budget sont conserves SANS corps plutot qu'ecartes :
    leur titre porte deja du signal (« Restauration-exemple.fr - Database Leak ») et le
    lien permet la revue humaine. Les plus recents sont servis en premier par
    le listing, donc le budget beneficie aux fils les plus frais.

    Recuperation PARALLELE (`BODY_FETCH_WORKERS`) : mesure du 2026-08-20 sur
    deux subdreads, 5 workers donnent 14-16 s/fil contre 32 s en sequentiel
    (~2,2x) AVEC un meilleur taux de succes (22/22 corps contre 31/40).
    Contre-intuitif au vu de la mesure du 2026-08-19 sur la *recherche*, ou la
    concurrence declenchait echecs Playwright et anti-bot : la difference est
    le volume de requetes simultanees ouvertes (5 recherches lourdes contre
    5 pages de fil), pas la concurrence en soi.

    Le parallelisme s'applique UNIQUEMENT aux corps, jamais aux listings : ces
    derniers restent sequentiels car c'est la qu'un anti-bot coute cher (tout
    un subdread perdu) et qu'un renouvellement de circuit doit rester isole."""
    to_fetch = threads if budget is None else threads[:budget]
    deferred = [] if budget is None else threads[budget:]

    bodies: dict[str, str | None] = {}
    if to_fetch:
        with ThreadPoolExecutor(max_workers=BODY_FETCH_WORKERS) as executor:
            futures = {
                executor.submit(fetch_thread_body, t.thread_url): t.thread_url
                for t in to_fetch
            }
            for future in as_completed(futures):
                url = futures[future]
                try:
                    bodies[url] = future.result()
                except Exception:
                    # Un fil en echec ne doit pas faire tomber le lot : le
                    # document reste collecte, sans corps.
                    logger.exception("Dread: echec recuperation du corps de %s", url)
                    bodies[url] = None

    return [
        DreadThread(
            title=thread.title,
            thread_url=thread.thread_url,
            subdread=thread.subdread,
            author=thread.author,
            published_at=thread.published_at,
            comment_count=thread.comment_count,
            body=bodies.get(thread.thread_url),
        )
        for thread in [*to_fetch, *deferred]
    ]


def fetch_dread_threads(
    base_url: str,
    subdreads: tuple[str, ...] = DEFAULT_SUBDREADS,
    max_pages: int | None = DEFAULT_MAX_PAGES,
    *,
    fetch_bodies: bool = True,
    max_bodies: int | None = DEFAULT_MAX_BODIES,
) -> list[DreadThread]:
    """Collecte les fils recents de plusieurs subdreads, sequentiellement.

    Sequentiel et non parallele, contrairement a la recherche par mots-cles
    (`api/routers/dread.py`) : la mesure du 2026-08-19 montre que la
    concurrence declenche a la fois les echecs Playwright transitoires et
    l'anti-bot. Ici on privilegie l'aboutissement du cycle sur la vitesse.

    Les listings sont recuperes pour TOUS les subdreads, puis les corps sont
    demandes dans la limite de `max_bodies` (budget global, pas par subdread —
    sinon le dernier subdread n'aurait jamais de corps). Voir DEFAULT_MAX_BODIES
    pour le calcul du plafond face a `task_time_limit`."""
    all_threads: list[DreadThread] = []
    for subdread in subdreads:
        threads = fetch_subdread_threads(
            base_url, subdread, max_pages, fetch_bodies=False
        )
        logger.info("Dread: /d/%s -> %d fils", subdread, len(threads))
        all_threads.extend(threads)

    if not fetch_bodies:
        return all_threads

    enriched = _with_bodies(all_threads, budget=max_bodies)
    with_body = sum(1 for t in enriched if t.body)
    logger.info(
        "Dread: %d fils collectes, %d corps recuperes (budget %s)",
        len(enriched),
        with_body,
        max_bodies,
    )
    return enriched
