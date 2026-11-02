"""Suivi du statut de publication d'une victime (plan de credibilite, phase 2).

Le statut (`published` / `pending`) est lu par les parsers de sites de fuite
(`dls/scraper.py`) et range dans `source_meta`, JAMAIS dans `content` :
`content` porte le `content_hash`, et y inscrire un etat qui change
(« SOON » -> « PUBLISHED ») recreerait un document a chaque bascule -- le
piege des compteurs volatils (ORION : 111 documents pour 12 victimes).

Consequence : un document deja connu n'est pas reecrit par la deduplication.
Ce module decide, a chaque nouvelle observation, s'il faut mettre a jour les
seules cles de statut d'un document existant. C'est ce qui rend visible la
BASCULE « en attente -> publiee », le signal le plus parlant du plan.

Logique pure : aucune base, aucun reseau.
"""

from __future__ import annotations

import re

STATUS_KEY = "publication_status"
EVIDENCE_KEY = "publication_evidence"
SINCE_KEY = "publication_status_since"
PREVIOUS_KEY = "publication_previous_status"

_CLES = (STATUS_KEY, EVIDENCE_KEY, SINCE_KEY, PREVIOUS_KEY)


def status_fields(status: str | None, evidence: str | None, now_iso: str) -> dict:
    """Cles a poser dans `source_meta` d'un document NOUVEAU. Vide si le site
    n'expose aucun statut : l'absence de cle se lit « inconnu »."""
    if not status:
        return {}
    return {STATUS_KEY: status, EVIDENCE_KEY: evidence, SINCE_KEY: now_iso}


def merge_publication_status(
    stored_meta: dict | None, incoming_meta: dict | None, now_iso: str
) -> dict | None:
    """Nouveau `source_meta` a ecrire sur un document EXISTANT, ou None s'il
    n'y a rien a changer.

    - Observation sans statut : rien ne change. Un marqueur absent a une passe
      (page partiellement rendue, gabarit modifie) ne prouve pas un
      changement d'etat -- on n'efface jamais un statut par de l'inconnu.
    - Meme statut : rien ne change, `publication_status_since` garde la date
      de la PREMIERE observation de cet etat. Reecrire a chaque passe
      toucherait des centaines de lignes pour rien et perdrait la date.
    - Statut different : bascule enregistree, avec l'etat precedent.

    Seules les cles de statut sont touchees ; le reste de `source_meta` est
    conserve tel quel."""
    incoming = incoming_meta or {}
    nouveau = incoming.get(STATUS_KEY)
    if not nouveau:
        return None
    stored = dict(stored_meta or {})
    ancien = stored.get(STATUS_KEY)
    if ancien == nouveau:
        return None
    stored[STATUS_KEY] = nouveau
    stored[EVIDENCE_KEY] = incoming.get(EVIDENCE_KEY)
    stored[SINCE_KEY] = now_iso
    if ancien:
        stored[PREVIOUS_KEY] = ancien
    return stored


# Libelles que NOS parsers ont recopies en tete de description, avant la
# phase 2 (KRYBIT « PUBLISHED - » / « SOON - », ORION, SAFEPAY, MYDATA). Ils
# ont ete ecrits par `dls/scraper.py` a partir d'un element dedie de la page,
# pas devines dans du texte libre : c'est ce qui autorise a les relire.
_LIBELLES_COLLECTES = {
    "PUBLISHED": "published",
    "SOON": "pending",
    "THE DATA HAS BEEN PUBLISHED": "published",
}
_LIBELLE_RE = re.compile(
    r"\n\n?(PUBLISHED|SOON|Published|The data has been published) - "
)


def status_from_collected_label(content: str | None) -> str | None:
    """Statut relu dans le libelle recopie par nos parsers, ou None.

    ⚠️ C'est l'etat affiche AU MOMENT DE LA COLLECTE : l'appelant doit le
    dater de `fetched_at`, jamais d'aujourd'hui. Un « SOON » d'aout n'est pas
    une attente actuelle."""
    trouve = _LIBELLE_RE.search(content or "")
    if trouve is None:
        return None
    return _LIBELLES_COLLECTES.get(trouve.group(1).upper())


def best_status(statuses) -> str | None:
    """Statut le plus fort parmi plusieurs documents d'une meme victime :
    `published` l'emporte sur `pending`, qui l'emporte sur l'inconnu. Une
    victime peut porter plusieurs documents (une bascule qui modifie le texte
    en cree un nouveau, voir KRYBIT)."""
    vus = {s for s in statuses if s}
    if "published" in vus:
        return "published"
    if "pending" in vus:
        return "pending"
    return None
