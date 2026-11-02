import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.roles import PEUT_VOIR_LE_CORPUS
from app.api.deps import exige_role, get_db
from app.core.config import settings
from app.db.models.detection import Detection
from app.pipeline.enrich.intelx import IntelXLookupError, corroborate_domain
from app.repositories.detection_repo import (
    DetectionRepository,
    DetectionSortBy,
    SortOrder,
)
from app.repositories.document_repo import RawDocumentRepository

router = APIRouter(
    prefix="/api/detections",
    tags=["detections"],
    dependencies=[Depends(exige_role(PEUT_VOIR_LE_CORPUS))],
)


class DetectionListItem(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    document_title: str | None
    document_url: str | None
    document_collector: str | None
    # Rubrique de classement declaree par la source pour le document d'origine
    # (voir pipeline/detect/patterns/topic.py) -- contexte de publication : une
    # detection issue de la rubrique presse n'a pas la meme portee qu'une
    # annonce postee dans une section de vente/leak.
    document_topic: str | None
    type: str
    value_masked: str
    validated: bool
    is_relevant: bool
    # Severite de la detection elle-meme (voir
    # services/detection_severity_service.py). Distincte de la severite d'une
    # alerte : une institution HORS perimetre de surveillance en porte une,
    # sans qu'aucune alerte ne soit creee.
    # NULL = non evaluee (type non matchable, ou infrastructure de collecte),
    # jamais « aucune ».
    severity: str | None
    corroborated_group: str | None
    # Corroboration par victime (migration 0024). `not_applicable` = mention
    # de forum ou infrastructure ; NULL = jamais confrontee.
    corroboration_status: str | None = None
    corroborated_groups: list[str] | None = None
    corroboration_match: str | None = None
    corroboration_first_seen_at: datetime | None = None
    corroboration_evidence_url: str | None = None
    # Observateurs tiers ayant vu la victime (ransomlook, ransomware_live).
    corroboration_observers: list[str] | None = None
    created_at: datetime


class DetectionListResponse(BaseModel):
    total: int
    offset: int
    limit: int
    counts_by_type: dict[str, int]
    relevant_count: int
    items: list[DetectionListItem]


def _list_item(
    detection: Detection,
    document_repo: RawDocumentRepository,
    topics: dict[uuid.UUID, str] | None = None,
) -> DetectionListItem:
    doc = document_repo.get(detection.document_id)
    return DetectionListItem(
        id=detection.id,
        document_id=detection.document_id,
        document_title=doc.title if doc else None,
        document_url=doc.url if doc else None,
        document_collector=doc.collector if doc else None,
        document_topic=(topics or {}).get(detection.document_id),
        type=detection.type,
        value_masked=detection.value_masked,
        validated=detection.validated,
        is_relevant=detection.is_relevant,
        severity=detection.severity,
        corroborated_group=detection.corroborated_group,
        corroboration_status=detection.corroboration_status,
        corroborated_groups=detection.corroborated_groups,
        corroboration_match=detection.corroboration_match,
        corroboration_first_seen_at=detection.corroboration_first_seen_at,
        corroboration_evidence_url=detection.corroboration_evidence_url,
        corroboration_observers=detection.corroboration_observers,
        created_at=detection.created_at,
    )


@router.get("", response_model=DetectionListResponse)
def list_detections(
    db: Session = Depends(get_db),
    type: str | None = Query(
        default=None, description="Filtrer par type (email, card, iban, ...)"
    ),
    validated: bool | None = Query(
        default=None, description="Filtrer sur les detections validees par un checksum"
    ),
    is_relevant: bool | None = Query(
        default=None,
        description="Filtrer sur la correspondance avec la watchlist (voir keyword_match.py)",
    ),
    created_from: datetime | None = Query(
        default=None,
        description="Ne garder que les detections a partir de cette date (incluse)",
    ),
    created_to: datetime | None = Query(
        default=None,
        description="Ne garder que les detections jusqu'a cette date (incluse)",
    ),
    q: str | None = Query(
        default=None,
        description=(
            "Recherche dans la valeur masquee (ex: « institution-exemple »). "
            "Seule la valeur masquee est conservee, c'est donc la seule "
            "cherchable."
        ),
    ),
    sort_by: DetectionSortBy = Query(
        default=DetectionSortBy.CREATED_AT, description="Champ de tri"
    ),
    sort_order: SortOrder = Query(default=SortOrder.DESC, description="Sens du tri"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> DetectionListResponse:
    repo = DetectionRepository(db)
    document_repo = RawDocumentRepository(db)

    detections = repo.list_all(
        offset=offset,
        limit=limit,
        type_=type,
        validated=validated,
        is_relevant=is_relevant,
        created_from=created_from,
        created_to=created_to,
        sort_by=sort_by,
        sort_order=sort_order,
        search=q,
    )
    total = repo.count_all(
        type_=type,
        validated=validated,
        is_relevant=is_relevant,
        created_from=created_from,
        created_to=created_to,
        search=q,
    )
    counts_by_type = repo.count_by_type()
    relevant_count = repo.count_all(is_relevant=True)

    # Chargement groupe des rubriques (une requete pour toute la page) plutot
    # qu'un appel par ligne -- voir DetectionRepository.topics_for_documents.
    topics = repo.topics_for_documents([d.document_id for d in detections])

    return DetectionListResponse(
        total=total,
        offset=offset,
        limit=limit,
        counts_by_type=counts_by_type,
        relevant_count=relevant_count,
        items=[_list_item(d, document_repo, topics) for d in detections],
    )


class IntelXDetectionCorroborationResponse(BaseModel):
    model_config = {"extra": "forbid"}

    domain: str
    hit_count: int
    # Voir entities.py : plafond IntelX atteint = compteur non significatif.
    is_truncated: bool = False
    buckets: dict[str, int]


@router.post(
    "/{detection_id}/corroborate-intelx",
    response_model=IntelXDetectionCorroborationResponse,
)
def corroborate_detection_intelx(
    detection_id: uuid.UUID, db: Session = Depends(get_db)
) -> IntelXDetectionCorroborationResponse:
    """Corrobore une detection de type `domain` via IntelX (voir
    pipeline/enrich/intelx.py). Reserve a `domain` : c'est le seul type dont
    `value_masked` est deja la valeur en clair (un domaine n'est pas une PII,
    voir pipeline/detect/patterns/domain.py) -- les autres types (email,
    card...) restent masques en base et ne peuvent pas etre reconstitues ici,
    voir CONTRIBUTING.md §2. Ne persiste rien, purement informatif."""
    if not settings.INTELX_API_KEY:
        raise HTTPException(
            status_code=503, detail="INTELX_API_KEY n'est pas configurée."
        )

    detection = DetectionRepository(db).get(detection_id)
    if detection is None:
        raise HTTPException(status_code=404, detail="Detection not found")
    if detection.type != "domain":
        raise HTTPException(
            status_code=400,
            detail="Seules les détections de type 'domain' peuvent être corroborées via IntelX (valeur non masquée).",
        )

    try:
        result = corroborate_domain(detection.value_masked, settings.INTELX_API_KEY)
    except IntelXLookupError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return IntelXDetectionCorroborationResponse(
        domain=result.term,
        hit_count=result.hit_count,
        is_truncated=result.is_truncated,
        buckets=result.buckets,
    )
