"""Calcul et persistance de la severite sur les DETECTIONS (migration 0015).

Repond a un manque de conception, pas a un bug : jusqu'ici la severite
n'existait que dans le chemin d'alerting, ou `alert_service` fait
`continue` sur toute detection qui ne correspond a aucune entite surveillee --
avant meme d'appeler `severity_for_detection`. Une institution hors perimetre
n'avait donc AUCUNE severite, alors qu'elle peut etre une victime nommee et
confirmee par un tiers.

Mesure du 2026-09-01 : 65 detections corroborees avec attribution de gang,
dont 61 pour des organisations non surveillees (`alarmes-exemple.com` / lockbit5,
`industry.airliquide.kr` / safepay...). RansomLook en couvre ~1000.

⚠️ Une severite n'est PAS une alerte. L'alerte reste reservee aux entites
surveillees (`alerts.entity_id` est NOT NULL) : cette separation est
deliberee, car noyer les 120 alertes de perimetre sous un millier de victimes
hors cible detruirait le livrable. La severite sert au tri et a la
decouverte ; l'alerte sert a prevenir une organisation surveillee.

Logique metier ici et non dans le depot (CONTRIBUTING.md §3.3) ; la decision
elle-meme reste dans `pipeline/alerting/rules.py`, qui demeure pur.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.orm import Session

from app.contracts.detection import DetectionContract, DetectionType
from app.db.models.detection import Detection
from app.pipeline.alerting.matching import (
    MATCHABLE_DETECTION_TYPES,
    matching_entities,
)
from app.pipeline.alerting.rules import severity_for_detection
from app.pipeline.enrich.ransomlook_corroboration import CorroborationStatus
from app.repositories.entity_repo import EntityRepository, to_entity_contract

logger = logging.getLogger(__name__)

# Meme plafond et meme justification que alert_service : le croisement se fait
# en memoire. Le filtrage des types est pousse en SQL pour ne pas gaspiller ce
# budget (voir MATCHABLE_DETECTION_TYPES).
_MAX_DETECTIONS_LOADED = 20_000

_CORROBORATED = CorroborationStatus.CORROBORATED.value


def _is_collection_infrastructure(value_masked: str) -> bool:
    """Un `.onion` du corpus est l'adresse d'un forum ou d'un site de fuite que
    NOUS collectons -- de l'infrastructure, jamais une victime.

    Meme regle que corroboration_service, qui les ecarte deja explicitement
    (« les .onion sont tronques et ne sont de toute facon pas des victimes »),
    et meme constat que CONTRIBUTING.md §6 : le pattern `domain` capte
    l'infrastructure du support, pas celle des victimes.

    ⚠️ Sans ce garde-fou l'echelle est inutilisable. Mesure du 2026-09-01 :
    **401 des 467 detections HIGH etaient des `.onion`**, promues par la seule
    branche `validated`. Or `validated` sur un domaine ne signifie que « format
    `.onion` reconnu », pas « fait confirme » -- les 1216 domaines valides du
    corpus sont TOUS des `.onion`. Presenter l'adresse d'un forum collecte
    comme une victime de gravite haute tromperait l'analyste.

    Le probleme ne se voyait pas dans l'alerting, ou un `.onion` ne matche
    jamais un selecteur clearnet et sortait donc avant tout calcul de severite.
    """
    value = value_masked or ""
    return ".onion" in value or "..." in value


_to_entity_contract = to_entity_contract


def _to_detection_contract(detection: Detection) -> DetectionContract:
    return DetectionContract(
        id=detection.id,
        document_id=detection.document_id,
        type=DetectionType(detection.type),
        value_masked=detection.value_masked,
        value_hash=detection.value_hash,
        validated=detection.validated,
        is_relevant=detection.is_relevant,
        created_at=detection.created_at,
    )


def refresh_detection_severities(
    db: Session, *, detection_ids: list[uuid.UUID] | None = None
) -> dict[str, int]:
    """Recalcule `detections.severity` pour les detections matchables et
    persiste le resultat. Retourne le compte par niveau, plus `updated`.

    ⚠️ Ne touche QUE les types matchables (DOMAIN/EMAIL). Les autres n'ont pas
    de severite interpretable ici : `matching.py` ne sait pas les rattacher, et
    la corroboration ne porte que sur des domaines. Leur `severity` reste NULL,
    ce qui se lit « pas evaluee » et non « aucune » -- meme convention que
    `corroboration_status` NULL.

    `detection_ids` restreint la passe a ces detections. `None` (defaut, usage
    normal depuis la tache planifiee) traite tout le corpus matchable ; les
    tests s'en servent pour ne pas reecrire les milliers de lignes reelles de
    la base d'integration en effet de bord.

    ⚠️ Le rattachement a une entite est evalue avec la watchlist DU MOMENT.
    Ajouter une entite ne met donc pas a jour retroactivement les severites
    tant que cette passe n'a pas retourne -- meme propriete que
    `alerts.generate` (voir CONTRIBUTING.md §8)."""
    entities = [_to_entity_contract(e) for e in EntityRepository(db).list_active()]

    query = db.query(Detection).filter(
        Detection.type.in_(list(MATCHABLE_DETECTION_TYPES))
    )
    if detection_ids is not None:
        query = query.filter(Detection.id.in_(detection_ids))
    rows = (
        query.order_by(Detection.created_at.desc()).limit(_MAX_DETECTIONS_LOADED).all()
    )
    if len(rows) == _MAX_DETECTIONS_LOADED:
        logger.warning(
            "detection_severity: plafond de %s detections atteint -- les plus "
            "anciennes conservent leur severite precedente.",
            _MAX_DETECTIONS_LOADED,
        )

    counts: dict[str, int] = {}
    updated = 0
    skipped_infrastructure = 0
    for row in rows:
        if _is_collection_infrastructure(row.value_masked):
            # NULL = « sans objet ici », pas « faible » : une adresse de
            # collecte n'a pas de gravite, la question ne se pose pas pour elle.
            skipped_infrastructure += 1
            if row.severity is not None:
                row.severity = None
                updated += 1
            continue
        contract = _to_detection_contract(row)
        severity = severity_for_detection(
            contract,
            matches_watched_entity=bool(matching_entities(contract, entities)),
            corroborated=row.corroboration_status == _CORROBORATED,
        )
        counts[severity.value] = counts.get(severity.value, 0) + 1
        # N'ecrire que sur changement : la passe tourne a chaque cycle
        # d'alerting et le corpus est stable a plus de 99 %.
        if row.severity != severity.value:
            row.severity = severity.value
            updated += 1

    db.commit()
    logger.info(
        "detection_severity: %s lignes, %s mises a jour, %s ecartees "
        "(infrastructure de collecte) (%s)",
        len(rows),
        updated,
        skipped_infrastructure,
        counts,
    )
    return {
        "evaluated": len(rows),
        "updated": updated,
        "skipped_infrastructure": skipped_infrastructure,
        **counts,
    }
