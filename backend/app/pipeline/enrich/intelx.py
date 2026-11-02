"""Corroboration via Intelligence X (IntelX) d'un domaine deja declare comme
selecteur d'une entite surveillee, a la demande (bouton sur la fiche entite)
-- jamais dans le chemin critique de collecte, voir CONTRIBUTING.md. Enrichissement
clearnet (reseau `backend`, pas Tor) : IntelX interroge son propre index deja
constitue, ce n'est pas une requete vers l'infrastructure de l'entite
surveillee (voir CONTRIBUTING.md §2).

Contrairement a crt.sh/certspotter (publics, sans cle), IntelX exige une cle
API (`INTELX_API_KEY`, voir .env.example) -- jamais en dur dans le code (regle
non negociable, voir CONTRIBUTING.md §2.4).

Tier gratuit/community : host dedie `free.intelx.io` (voir "Your API details"
dans le compte -- PAS `2.intelx.io`, qui est l'hote par defaut du SDK officiel
pour les cles payantes, ni `public.intelx.io` qui n'existe pas). Endpoint
`/intelligent/search` uniquement (le `/phonebook/search` type-e est reserve
aux comptes payants). La recherche se fait donc sur un terme texte libre --
on interroge le domaine du selecteur `domain` de l'entite (une donnee
publique declaree par l'entite elle-meme, jamais une valeur masquee
reconstituee depuis une detection, voir CONTRIBUTING.md §2 "jamais de PII brute").

Quota tres serre sur ce tier (constate dans le compte : 50 credits
/intelligent/search, 50 /intelligent/search/result, 3 recherches concurrentes
actives max) -- chaque appel de fonction de ce module consomme au maximum
**un seul crebit de chaque endpoint** par domaine corrobore :
1 x POST /intelligent/search (lance la recherche)
1 x GET  /intelligent/search/result (recupere ce qui est deja pret -- ce
  endpoint n'attend pas la fin de la recherche cote serveur, il renvoie l'etat
  courant ; `status` 1 ou 2 signifie "plus rien a attendre", voir
  https://github.com/IntelligenceX/SDK, Python/intelx/intelxapi.py -- une
  seule lecture suffit, pas de boucle de polling)
1 x POST /intelligent/search/terminate (libere le slot de recherche
  concurrente immediatement, sans attendre le timeout naturel du `timeout`
  passe a la recherche)

IntelX ne fournit ici qu'un comptage de correspondances par bucket (source),
jamais le contenu des resultats eux-memes -- perimetre volontairement limite
a la corroboration ("ce domaine apparait dans d'autres index de fuites
connus"), pas a l'extraction de donnees tierces."""

from __future__ import annotations

import time

import requests

_BASE_URL = "https://free.intelx.io"
_SEARCH_URL = f"{_BASE_URL}/intelligent/search"
_RESULT_URL = f"{_BASE_URL}/intelligent/search/result"
_TERMINATE_URL = f"{_BASE_URL}/intelligent/search/terminate"
_TIMEOUT_SECONDS = 15
# Nombre de resultats demandes cote serveur (voir docstring module) -- pas un
# nombre d'appels : un seul GET /intelligent/search/result est fait, quel que
# soit ce que la recherche a deja trouve au moment de l'appel.
#
# ⚠️ MESURE DU 2026-08-26 : ce plafond est ATTEINT par tous les domaines
# reellement exposes. `google.com` rend 200, `institution-exemple.sn` (petite
# institution senegalaise) rend 200 aussi. `hit_count` est donc **saturé** et
# ne discrimine PAS l'ampleur d'une exposition -- seul son caractere non nul
# porte de l'information (un domaine inexistant rend bien 0). Ne jamais
# presenter ce nombre comme une mesure de gravite : voir `is_truncated`.
_MAX_RESULTS = 200
# `status` renvoye par /intelligent/search/result : 1 = pas plus de resultats
# a attendre (deja tout envoye), 2 = id de recherche inconnu/expire. Les deux
# signifient "rien de plus a obtenir en re-interrogeant", voir SDK officiel.
_STATUS_NO_MORE_RESULTS = (1, 2)


class IntelXLookupError(Exception):
    """La cle API est absente, invalide, ou IntelX n'a pas repondu
    correctement (reseau, timeout, JSON inexploitable)."""


class IntelXCorroborationResult:
    def __init__(self, term: str, hit_count: int, buckets: dict[str, int]):
        self.term = term
        self.hit_count = hit_count
        self.buckets = buckets

    @property
    def is_truncated(self) -> bool:
        """True quand `hit_count` a atteint le plafond `_MAX_RESULTS`.

        Mesure du 2026-08-26 : c'est le cas de TOUS les domaines reellement
        exposes (google.com comme institution-exemple.sn rendent 200). Dans ce cas
        le nombre ne mesure rien -- il faut lire « au moins 200 », jamais
        « 200 ». L'interface doit l'afficher comme tel."""
        return self.hit_count >= _MAX_RESULTS


def _headers(api_key: str) -> dict[str, str]:
    return {"x-key": api_key, "User-Agent": "threat-intel-platform"}


def _start_search(term: str, api_key: str) -> str:
    response = requests.post(
        _SEARCH_URL,
        headers=_headers(api_key),
        json={
            "term": term,
            "buckets": [],
            "lookuplevel": 0,
            "maxresults": _MAX_RESULTS,
            "timeout": 5,
            "datefrom": "",
            "dateto": "",
            "sort": 4,
            "media": 0,
            "terminate": [],
        },
        timeout=_TIMEOUT_SECONDS,
    )
    if response.status_code == 401:
        raise IntelXLookupError("Cle API IntelX invalide ou absente")
    response.raise_for_status()

    try:
        search_id = response.json()["id"]
    except (ValueError, KeyError) as exc:
        raise IntelXLookupError(
            "Reponse IntelX inexploitable au lancement de la recherche"
        ) from exc
    return search_id


def _fetch_results_once(search_id: str, api_key: str) -> list[dict]:
    """Un seul GET -- /intelligent/search/result renvoie l'etat courant de la
    recherche sans attendre qu'elle soit terminee cote serveur, voir docstring
    module. Suffisant pour une corroboration (un comptage approximatif, pas un
    export exhaustif) et couteux a repeter vu le quota du tier gratuit.

    Constate en usage reel : `records` peut valoir `null` (pas juste absent)
    quand la recherche n'a pas encore ete initialisee cote serveur au moment
    de ce premier appel -- traite comme "rien pour l'instant", pas une erreur
    (`payload.get("records", [])` seul ne suffit pas, il renvoie `None` tel
    quel si la cle existe avec cette valeur)."""
    params: dict[str, str | int] = {"id": str(search_id), "limit": _MAX_RESULTS}
    response = requests.get(
        _RESULT_URL,
        headers=_headers(api_key),
        params=params,
        timeout=_TIMEOUT_SECONDS,
    )
    response.raise_for_status()

    try:
        payload = response.json()
    except ValueError as exc:
        raise IntelXLookupError(
            "Reponse IntelX inexploitable pendant la recuperation des resultats"
        ) from exc

    return payload.get("records") or []


def _terminate_search(search_id: str, api_key: str) -> None:
    """Libere immediatement le slot de recherche concurrente (3 max sur ce
    tier, voir docstring module) plutot que d'attendre le timeout naturel de
    la recherche. Best-effort : une erreur ici ne doit pas faire echouer la
    corroboration, le resultat a deja ete recupere."""
    try:
        requests.get(
            _TERMINATE_URL,
            headers=_headers(api_key),
            params={"id": search_id},
            timeout=_TIMEOUT_SECONDS,
        )
    except requests.RequestException:
        pass


def corroborate_domain(domain: str, api_key: str) -> IntelXCorroborationResult:
    """Interroge IntelX sur `domain` (valeur en clair d'un selecteur `domain`
    d'entite, jamais une valeur reconstituee depuis une detection masquee) et
    retourne un comptage de correspondances par bucket. Ne remonte jamais le
    contenu des resultats eux-memes, uniquement leur source et leur nombre --
    perimetre volontairement limite a la corroboration, voir CONTRIBUTING.md §2.

    Consomme au maximum 1 credit /intelligent/search + 1 credit
    /intelligent/search/result par appel (voir docstring module) : pas de
    boucle de polling, un seul instantane des resultats deja trouves."""
    if not api_key:
        raise IntelXLookupError("INTELX_API_KEY n'est pas configuree")

    normalized = domain.strip().lower().rstrip(".")
    if not normalized:
        raise IntelXLookupError("Domaine vide")

    try:
        search_id = _start_search(normalized, api_key)
        # Court delai avant la premiere (et unique) lecture des resultats :
        # constate en usage reel, `records` peut valoir `null` si on lit trop
        # tot, avant que la recherche ne soit initialisee cote serveur IntelX
        # (voir SDK officiel, qui laisse toujours 1s entre le lancement et la
        # premiere lecture -- Python/intelx/intelxapi.py, methode search()).
        time.sleep(1)
        records = _fetch_results_once(search_id, api_key)
    except requests.RequestException as exc:
        raise IntelXLookupError(f"IntelX injoignable : {exc}") from exc
    finally:
        if "search_id" in locals():
            _terminate_search(search_id, api_key)

    buckets: dict[str, int] = {}
    for record in records:
        bucket = record.get("bucket", "unknown")
        buckets[bucket] = buckets.get(bucket, 0) + 1

    return IntelXCorroborationResult(
        term=normalized, hit_count=len(records), buckets=buckets
    )
