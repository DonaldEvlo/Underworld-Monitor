"""Donnees de la mesure d'avance sur les agregateurs : nos victimes (base) et
les historiques FRAIS des agregateurs (reseau). Le calcul est pur, dans
`pipeline/evaluation/lead_time.py`.

⚠️ SANS CACHE, contrairement a la corroboration. Les historiques y sont
gardes 24 h ; pour une mesure d'avance, une victime indexee apres la mise en
cache paraitrait absente, donc « nous en avance » a tort. On paie donc un
appel frais par gang et par observateur -- dont ~1/min chez ransomware.live
(limite mesuree le 2026-09-15) : une passe prend une vingtaine de minutes.

Lecture seule en base. Aucune donnee de victime n'est envoyee aux
agregateurs : on telecharge leur historique public d'un gang et on compare
localement.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime

import requests
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models.raw_document import RawDocument
from app.db.models.source import Source
from app.pipeline.enrich.ransomlook_corroboration import (
    gang_slug_for_source,
    group_evidence_api_url,
    parse_group_history,
)
from app.pipeline.enrich.ransomware_live import (
    group_victims_url,
    parse_group_victims,
)
from app.pipeline.evaluation.lead_time import (
    LeadObservation,
    OurVictim,
    build_index,
    existed_before_collection,
    is_eligible,
    observe,
)

logger = logging.getLogger(__name__)

RANSOMLOOK = "RansomLook"
RANSOMWARE_LIVE = "ransomware.live"

# Sources qui publient leurs victimes ET que nous lisons nous-memes. RansomLook
# en est exclu : c'est un agregateur, se comparer a lui-meme ne mesure rien.
_COLLECTEURS_MESURES = ("dls", "akira")
_TIMEOUT = 120
_PAUSE_RWL_SECONDES = 62


def our_victims(db: Session) -> tuple[list[OurVictim], dict[str, datetime]]:
    """Nos victimes (une par source + URL, premiere observation = plus ancien
    `fetched_at`) et la date de PREMIERE collecte de chaque source."""
    lignes = (
        db.query(RawDocument, Source.name)
        .join(Source, Source.id == RawDocument.source_id)
        .filter(RawDocument.collector.in_(_COLLECTEURS_MESURES))
        .all()
    )
    premieres: dict[str, datetime] = {
        nom: premiere
        for nom, premiere in db.query(Source.name, func.min(RawDocument.fetched_at))
        .join(RawDocument, RawDocument.source_id == Source.id)
        .filter(RawDocument.collector.in_(_COLLECTEURS_MESURES))
        .group_by(Source.name)
        .all()
    }
    vues: dict[tuple[str, str], datetime] = {}
    termes: dict[tuple[str, str], set[str]] = defaultdict(set)
    for doc, source in lignes:
        cle = (source, doc.url)
        if doc.fetched_at is not None and (
            cle not in vues or doc.fetched_at < vues[cle]
        ):
            vues[cle] = doc.fetched_at
        meta = doc.source_meta or {}
        for t in (doc.title, meta.get("victim_site"), meta.get("victim_name")):
            if t:
                termes[cle].add(str(t))
    victimes = []
    for (source, _url), vu in vues.items():
        gang = gang_slug_for_source(source)
        if gang and termes[(source, _url)]:
            victimes.append(
                OurVictim(source, gang, vu, tuple(sorted(termes[(source, _url)])))
            )
    return victimes, premieres


def _get_json(url: str) -> object:
    reponse = requests.get(
        url, timeout=_TIMEOUT, headers={"User-Agent": "threat-intel-platform"}
    )
    if reponse.status_code == 404:
        return []
    reponse.raise_for_status()
    return reponse.json()


def fresh_indexes(
    gangs: set[str],
    fetch: Callable[[str], object] = _get_json,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[tuple[str, str], dict[str, datetime] | None]:
    """Index frais par (observateur, gang). `None` = indisponible : le gang
    est alors EXCLU de la mesure pour cet observateur, jamais compte comme
    « absent » (une absence de mesure n'est pas une avance)."""
    index: dict[tuple[str, str], dict[str, datetime] | None] = {}
    for gang in sorted(gangs):
        try:
            index[(RANSOMLOOK, gang)] = build_index(
                parse_group_history(fetch(group_evidence_api_url(gang)))
            )
        except Exception:
            logger.warning("RansomLook indisponible pour %s", gang, exc_info=True)
            index[(RANSOMLOOK, gang)] = None
    for i, gang in enumerate(sorted(gangs)):
        if i:
            sleep(_PAUSE_RWL_SECONDES)
        charge: object = None
        for _essai in range(2):
            try:
                charge = fetch(group_victims_url(gang))
            except Exception:
                logger.warning(
                    "ransomware.live indisponible pour %s", gang, exc_info=True
                )
                charge = None
            # ⚠️ La limite de debit est servie en HTTP 200 avec un OBJET
            # (`{"message": "1 per 1 minute"}`) : seule une LISTE est une
            # reponse. Une seconde tentative apres la pause, puis abandon.
            if isinstance(charge, list):
                break
            sleep(_PAUSE_RWL_SECONDES)
        index[(RANSOMWARE_LIVE, gang)] = (
            build_index(parse_group_victims(charge))
            if isinstance(charge, list)
            else None
        )
    return index


def measure(
    victimes: list[OurVictim],
    premieres: dict[str, datetime],
    index: dict[tuple[str, str], dict[str, datetime] | None],
    window_start: datetime,
    now: datetime,
) -> tuple[list[LeadObservation], dict[str, int]]:
    """Observations pour chaque victime eligible et chaque observateur qui a
    REPONDU pour son gang. Rend aussi les compteurs d'exclusion, affiches par
    le script : un chiffre sans son assiette n'est pas verifiable."""
    compteurs = {
        "total": len(victimes),
        "rattrapage_ou_hors_fenetre": 0,
        "rattrapage_tardif": 0,
        "eligibles": 0,
    }
    observations: list[LeadObservation] = []
    for v in victimes:
        premiere = premieres.get(v.source)
        if premiere is None or not is_eligible(v, premiere, window_start):
            compteurs["rattrapage_ou_hors_fenetre"] += 1
            continue
        # `None` = pas de reponse ; `{}` = l'observateur ne suit PAS ce gang
        # (RansomLook et APT73, par exemple). Dans les deux cas, pas de
        # mesure : sinon toutes ses victimes passeraient pour « nous en
        # avance », alors qu'il ne les cherchera jamais.
        repondants = {
            o: idx
            for o in (RANSOMLOOK, RANSOMWARE_LIVE)
            if (idx := index.get((o, v.gang)))
        }
        if existed_before_collection(v, repondants.values(), premiere):
            compteurs["rattrapage_tardif"] += 1
            continue
        compteurs["eligibles"] += 1
        for observateur, idx in repondants.items():
            observations.append(observe(v, observateur, idx, now))
    return observations, compteurs
