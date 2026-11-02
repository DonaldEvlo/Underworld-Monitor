"""Notation Admiralty des alertes (voir `pipeline/alerting/admiralty.py`).

Calcule A LA VOLEE, jamais persistee : une valeur stockee deviendrait fausse
en silence au premier ajustement des seuils ou au premier historique qui
evolue (meme choix que la geographie).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterable

from sqlalchemy.orm import Session

from app.db.models.alert import Alert
from app.pipeline.alerting.admiralty import (
    AdmiraltyRating,
    Grade,
    SourceTrack,
    best_source,
    information_credibility,
    source_reliability,
)
from app.pipeline.detect.announcement_filter import (
    VICTIM_PUBLISHING_COLLECTORS,
    source_publishes_victims,
)
from app.repositories.admiralty_repo import (
    alert_source_rows,
    alert_victim_claims,
    alert_victim_titles,
    source_track_rows,
)


def source_tracks(db: Session) -> dict[uuid.UUID, tuple[str, SourceTrack]]:
    """Historique de chaque source. Une source dont UN collecteur publie des
    victimes est un site de victimes ; seuls les documents de ce collecteur
    comptent dans son historique (un repli ponctuel sur le collecteur
    generique ne doit pas diluer le taux)."""
    cumul: dict[uuid.UUID, list] = {}
    for source_id, nom, collecteur, evaluees, confirmees in source_track_rows(db):
        publie = source_publishes_victims(collecteur)
        entree = cumul.setdefault(source_id, [nom, False, 0, 0])
        if publie:
            entree[1] = True
            entree[2] += evaluees
            entree[3] += confirmees
    return {
        sid: (nom, SourceTrack(publie, evaluees, confirmees))
        for sid, (nom, publie, evaluees, confirmees) in cumul.items()
    }


def rate_alerts(
    db: Session, alerts: Iterable[Alert]
) -> dict[uuid.UUID, AdmiraltyRating]:
    alertes = list(alerts)
    if not alertes:
        return {}
    historiques = source_tracks(db)
    sources_par_alerte: dict[uuid.UUID, list[tuple[uuid.UUID, str | None]]] = (
        defaultdict(list)
    )
    for alert_id, source_id, collecteur in alert_source_rows(
        db, (a.id for a in alertes)
    ):
        sources_par_alerte[alert_id].append((source_id, collecteur))

    notes: dict[uuid.UUID, AdmiraltyRating] = {}
    for alerte in alertes:
        candidates: list[tuple[Grade, str]] = []
        site_de_victimes = False
        for source_id, collecteur in sources_par_alerte.get(alerte.id, []):
            site_de_victimes |= source_publishes_victims(collecteur)
            if source_id in historiques:
                nom, historique = historiques[source_id]
                candidates.append((source_reliability(historique), nom))
        meilleure = best_source([g for g, _ in candidates])
        nom_source: str | None = None
        if meilleure is None:
            meilleure = Grade("F", "aucune source rattachee")
        else:
            nom_source = candidates[[g for g, _ in candidates].index(meilleure)][1]
        notes[alerte.id] = AdmiraltyRating(
            source=meilleure,
            source_name=nom_source,
            information=information_credibility(
                alerte.credibility_level,
                corroborated=alerte.corroboration_status == "corroborated",
                from_victim_site=site_de_victimes,
            ),
        )
    return notes


def victim_claims(db: Session, alert: Alert) -> list[tuple[str, str | None]]:
    """(victime, gang qui la revendique) pour chaque victime de l'alerte."""
    return alert_victim_claims(db, alert.id, VICTIM_PUBLISHING_COLLECTORS)


def victim_titles(db: Session, alerts: Iterable[Alert]) -> dict[uuid.UUID, list[str]]:
    """Victimes nommees de chaque alerte (titres des documents de sites de
    victimes). Sert a intituler une alerte REGIONALE, qui n'a pas d'entite."""
    return alert_victim_titles(db, (a.id for a in alerts), VICTIM_PUBLISHING_COLLECTORS)
