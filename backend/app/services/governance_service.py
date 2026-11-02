"""Vue de gouvernance (RSSI) : activite du service + menace sectorielle du
perimetre, en AGREGATS (voir pipeline/reporting/governance.py).

La menace sectorielle se lit dans les historiques ransomware.live DEJA en
cache Redis : AUCUN appel reseau ici. ⚠️ La couverture (nombre de gangs lus)
et la date de calcul sont rendues avec les chiffres -- un cache partiel ne
doit pas se lire comme une baisse de la menace.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from typing import cast

from sqlalchemy.orm import Session

from app.core.config import settings
from app.pipeline.enrich.geo import continent_for_country
from app.pipeline.reporting.governance import (
    VictimFact,
    sector_threat,
    service_activity,
    world_threat,
)
from app.repositories.governance_repo import alert_facts
from app.services.corroboration_service import get_redis

logger = logging.getLogger(__name__)

# Meme prefixe que `corroboration_service._RWL_PAYLOAD_KEY`.
_PREFIXE_CACHE = "ransomwarelive_payload:"


def _continents() -> tuple[str, ...]:
    return tuple(
        c.strip()
        for c in (settings.ALERT_WATCHED_CONTINENTS or "").split(",")
        if c.strip()
    )


def _date(texte) -> datetime | None:
    if not texte:
        return None
    try:
        moment = datetime.fromisoformat(str(texte).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def victimes_en_cache() -> tuple[list[VictimFact], list[str]]:
    """Victimes publiees (sans leur nom) de tous les gangs en cache, et la
    liste de ces gangs. Cache indisponible -> ([], []) : absence de mesure,
    affichee comme telle."""
    victimes: list[VictimFact] = []
    gangs: list[str] = []
    try:
        redis = get_redis()
        for cle in redis.scan_iter(f"{_PREFIXE_CACHE}*"):
            cle = cle.decode() if isinstance(cle, bytes) else cle
            gang = cle[len(_PREFIXE_CACHE) :]
            try:
                charge = json.loads(cast("str | None", redis.get(cle)) or "[]")
            except (TypeError, ValueError):
                continue
            if not isinstance(charge, list):
                continue
            gangs.append(gang)
            for v in charge:
                if not isinstance(v, dict):
                    continue
                decouverte = _date(v.get("discovered"))
                if decouverte is None:
                    continue
                victimes.append(
                    VictimFact(
                        discovered=decouverte,
                        gang=gang,
                        sector=(v.get("activity") or None),
                        country=(v.get("country") or None),
                    )
                )
    except Exception:
        logger.warning("Cache des historiques indisponible", exc_info=True)
        return [], []
    return victimes, sorted(gangs)


def bornes_du_mois(mois: str) -> tuple[date, date]:
    """« 2026-09 » -> (1er septembre, 1er octobre). Leve ValueError sinon."""
    annee, numero = (int(x) for x in mois.split("-"))
    debut = date(annee, numero, 1)
    fin = date(annee + (numero == 12), numero % 12 + 1, 1)
    return debut, fin


def governance(
    db: Session,
    *,
    now: datetime | None = None,
    months: int = 12,
    month: str | None = None,
) -> dict:
    """Agregats de gouvernance. `month` (« AAAA-MM ») borne l'ACTIVITE DU
    SERVICE a ce mois ; la menace sectorielle couvre toujours les `months`
    mois precedant `now`."""
    now = now or datetime.now(timezone.utc)
    alertes = alert_facts(db)
    # Debut du CORPUS, pas du mois filtre : c'est ce que dit la limite de
    # lecture (« corpus jeune »). Calculee sur le mois, elle disparaissait des
    # qu'un mois etait vide (constate a l'image le 2026-10-01).
    debut_corpus = min((a.alert_date for a in alertes), default=None)
    if month:
        debut, fin = bornes_du_mois(month)
        alertes = [a for a in alertes if debut <= a.alert_date < fin]
    victimes, gangs = victimes_en_cache()
    menace = sector_threat(
        victimes,
        continent_de=continent_for_country,
        continents=_continents(),
        now=now,
        months=months,
    )
    menace["coverage_gangs"] = len(gangs)
    monde = world_threat(
        victimes,
        continent_de=continent_for_country,
        continents_mis_en_avant=_continents(),
        now=now,
        months=months,
    )
    monde["coverage_gangs"] = len(gangs)
    return {
        "computed_at": now.isoformat(),
        "month": month,
        "corpus_first_alert_date": debut_corpus.isoformat() if debut_corpus else None,
        "service": service_activity(alertes),
        "sector_threat": menace,
        "world_threat": monde,
    }
