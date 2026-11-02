"""Localise les victimes publiees SANS domaine localisable (base + reseau).

Logique pure : `pipeline/enrich/victim_location.py`. Ici : choix des
documents candidats, appels a ransomware.live (en cache), ecriture du pays
DECLARE dans `source_meta` du document.

⚠️ `source_meta`, jamais `content` : le pays n'est pas dans l'annonce du gang,
il vient d'un tiers. Le mettre dans le contenu changerait le `content_hash`
et melangerait ce que nous avons lu avec ce qu'un autre publie.

⚠️ Clearnet, hors Tor : meme exception documentee que les autres
enrichisseurs (CONTRIBUTING.md regle 3, CONTRIBUTING.md §2). Seul le NOM DU GANG sort.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import cast

import requests
from sqlalchemy.orm import Session

from app.core.cache import get_redis
from app.db.models.detection import Detection
from app.db.models.raw_document import RawDocument
from app.db.models.source import Source
from app.pipeline.detect.announcement_filter import VICTIM_PUBLISHING_COLLECTORS
from app.pipeline.enrich.geo import locate_domain
from app.pipeline.enrich.ransomlook_corroboration import gang_slug_for_source
from app.pipeline.enrich.ransomware_live import RECENT_VICTIMS_URL
from app.pipeline.enrich.victim_location import build_location_index, locate_victim
from app.services.corroboration_service import payload_rwl, rwl_payload_cached

logger = logging.getLogger(__name__)

# Fenetre des documents examines : celle de l'alerting (7 jours) -- localiser
# une victime qu'aucune passe d'alerte ne reverra ne servirait a rien.
FENETRE_JOURS = 7
# Appels RESEAU d'historiques par passe (les historiques deja en cache, eux,
# sont lus sans limite). ransomware.live limite a ~1 requete par MINUTE : dix
# appels d'affilee en verraient neuf refuses. On en fait donc peu, espaces
# d'une minute ; caches 24 h, la couverture se complete au fil des passes
# horaires.
MAX_HISTORIQUES_PAR_PASSE = 3
PAUSE_ENTRE_APPELS_S = 61
_CLE_RECENTES = "ransomwarelive_recent"
# Les victimes recentes changent vite : une heure, pas 24.
_TTL_RECENTES = 3600
PROVENANCE = "ransomware.live"


@dataclass
class LocationOutcome:
    candidates: int = 0
    located: int = 0
    recent_available: bool = False
    gangs_loaded: int = 0
    gangs_unavailable: list[str] = field(default_factory=list)


def _victimes_recentes() -> tuple[list | None, bool]:
    """`/v2/recentvictims` (~100 victimes, ~5 jours), cache 1 h. None si
    indisponible -- et une indisponibilite n'est JAMAIS mise en cache (meme
    regle que les historiques : le message de rate limit arrive en HTTP 200)."""
    redis = None
    try:
        redis = get_redis()
        cache = cast("str | None", redis.get(_CLE_RECENTES))
        if cache is not None:
            return json.loads(cache), False
    except Exception:
        logger.warning("Cache des victimes recentes indisponible", exc_info=True)
    try:
        reponse = requests.get(
            RECENT_VICTIMS_URL,
            timeout=60,
            headers={"User-Agent": "threat-intel-platform"},
        )
        reponse.raise_for_status()
        charge = reponse.json()
    except Exception:
        logger.warning("Victimes recentes ransomware.live indisponibles", exc_info=True)
        return None, True
    if not isinstance(charge, list):
        return None, True
    if redis is not None:
        try:
            redis.set(_CLE_RECENTES, json.dumps(charge), ex=_TTL_RECENTES)
        except Exception:
            logger.warning("Victimes recentes non mises en cache", exc_info=True)
    return charge, True


def _a_un_domaine_localisable(valeurs: list[str]) -> bool:
    return any(locate_domain(v)[0] for v in valeurs if v)


def locate_victims(
    db: Session,
    *,
    now: datetime | None = None,
    max_gangs: int = MAX_HISTORIQUES_PAR_PASSE,
    pause: Callable[[float], None] = time.sleep,
) -> LocationOutcome:
    """Renseigne `source_meta.victim_country` des victimes recentes qui n'ont
    aucun domaine localisable, quand ransomware.live declare leur pays."""
    now = now or datetime.now(timezone.utc)
    requete = (
        db.query(RawDocument, Source)
        .join(Source, Source.id == RawDocument.source_id)
        .filter(
            RawDocument.collector.in_(tuple(VICTIM_PUBLISHING_COLLECTORS)),
            RawDocument.fetched_at >= now - timedelta(days=FENETRE_JOURS),
            RawDocument.title.isnot(None),
        )
    )
    lignes: list[tuple[RawDocument, Source]] = [
        (d, s)
        for d, s in requete.all()
        if not (d.source_meta or {}).get("victim_country")
    ]
    if not lignes:
        return LocationOutcome()

    valeurs: dict = {}
    for document_id, valeur in db.query(
        Detection.document_id, Detection.value_masked
    ).filter(
        Detection.document_id.in_([d.id for d, _ in lignes]),
        Detection.type == "domain",
    ):
        valeurs.setdefault(document_id, []).append(valeur)

    candidats = []
    for document, source in lignes:
        # Une victime deja localisable par son domaine est traitee par la
        # passe regionale ordinaire : rien a ajouter.
        if _a_un_domaine_localisable(
            [document.title or "", *valeurs.get(document.id, [])]
        ):
            continue
        gang = (document.source_meta or {}).get("group_name") or gang_slug_for_source(
            source.name
        )
        if gang:
            candidats.append((document, gang))

    issue = LocationOutcome(candidates=len(candidats))
    if not candidats:
        return issue

    entrees: list[tuple[str, dict]] = []
    recentes, appel_reseau = _victimes_recentes()
    if recentes is not None:
        issue.recent_available = True
        entrees += [(v.get("group") or "", v) for v in recentes if isinstance(v, dict)]
    # L'appel aux victimes recentes consomme deja la minute s'il est alle
    # sur le reseau : le premier historique doit alors attendre.
    appels = 0
    deja_appele = appel_reseau
    for gang in sorted({g for _, g in candidats}):
        if not rwl_payload_cached(gang):
            if appels >= max_gangs:
                # Reporte a une passe suivante -- pas une indisponibilite.
                continue
            if deja_appele:
                pause(PAUSE_ENTRE_APPELS_S)
            appels += 1
            deja_appele = True
        charge = payload_rwl(gang)
        if charge is None:
            issue.gangs_unavailable.append(gang)
            continue
        issue.gangs_loaded += 1
        entrees += [(gang, v) for v in charge]

    index = build_location_index(entrees)
    horodatage = now.isoformat()
    for document, gang in candidats:
        localisation = locate_victim(document.title, gang, index)
        if localisation is None:
            continue
        # Nouveau dict : une mutation en place d'un JSONB n'est pas vue par
        # SQLAlchemy et ne serait jamais ecrite.
        document.source_meta = {
            **(document.source_meta or {}),
            "victim_country": localisation.country,
            "victim_domain": localisation.domain,
            "victim_location_source": PROVENANCE,
            "victim_located_at": horodatage,
        }
        issue.located += 1
    db.commit()
    return issue
