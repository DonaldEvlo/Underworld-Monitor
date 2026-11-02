import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, computed_field
from sqlalchemy.orm import Session

from app.core.roles import PEUT_ADMINISTRER, PEUT_VOIR_LE_CORPUS
from app.api.deps import exige_role, get_db
from app.api.routers.documents import DocumentListItem, _list_item
from app.api.routers.llm import get_selected_model
from app.contracts.detection import DetectionContract, DetectionType
from app.contracts.entity import (
    SelectorType,
    VerificationMethod,
    VerificationStatus,
)
from app.core.cache import get_redis
from app.core.config import settings
from app.core.llm.client import filter_organization_candidates
from app.db.models.entity import Entity, EntitySelector
from app.db.session import SessionLocal
from app.pipeline.alerting.matching import matchable_detection_types
from app.pipeline.alerting.candidates import filter_new_candidates
from app.pipeline.alerting.matching import matching_entities
from app.pipeline.detect.patterns.organization import find_organizations
from app.pipeline.enrich.intelx import IntelXLookupError, corroborate_domain
from app.pipeline.enrich.subdomains import SubdomainLookupError, find_subdomains
from app.repositories.detection_repo import DetectionRepository
from app.repositories.document_repo import RawDocumentRepository
from app.repositories.entity_repo import EntityRepository, to_entity_contract
from app.repositories.source_repo import SourceRepository
from app.services import entity_service

router = APIRouter(
    prefix="/api/entities",
    tags=["entities"],
    dependencies=[Depends(exige_role(PEUT_VOIR_LE_CORPUS))],
)

# Meme limite et meme justification que stats.py::_MAX_DETECTIONS_LOADED : le
# croisement entite<->detection se fait en memoire (voir matching_entities),
# pas en SQL -- borne haute pour ne pas tronquer silencieusement le corpus
# reel plutot qu'une pagination cote base a ce niveau.
_MAX_DETECTIONS_LOADED_FOR_MATCHING = 20_000

logger = logging.getLogger(__name__)


class SelectorIn(BaseModel):
    model_config = {"extra": "forbid"}

    type: SelectorType
    value: str


class SelectorOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    type: str
    value: str


class EntityCreate(BaseModel):
    model_config = {"extra": "forbid"}

    name: str
    active: bool = True
    selectors: list[SelectorIn] = []
    # Migration 0033 : groupe parent, pays (ISO alpha-2) et secteur declares.
    parent_id: uuid.UUID | None = None
    country: str | None = None
    sector: str | None = None


class EntityUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    name: str | None = None
    active: bool | None = None
    selectors: list[SelectorIn] | None = None
    verification_method: VerificationMethod | None = None
    verification_status: VerificationStatus | None = None
    # ⚠️ `null` explicite = effacer (retirer le groupe, le pays...). On lit
    # donc `model_fields_set`, pas « different de None ».
    parent_id: uuid.UUID | None = None
    country: str | None = None
    sector: str | None = None


class EntityOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    active: bool
    selectors: list[SelectorOut]
    verification_method: str | None
    verification_status: str
    verified_at: datetime | None
    created_at: datetime
    parent_id: uuid.UUID | None = None
    country: str | None = None
    sector: str | None = None

    @computed_field
    @property
    def can_alert(self) -> bool:
        """Cette entite peut-elle produire une alerte ?

        ⚠️ Une entite ACTIVE sans aucun selecteur ne peut structurellement
        jamais alerter : `matching.py` ne compare que des selecteurs. Mesure du
        2026-09-04 : **8 entites actives sur 42** etaient dans ce cas -- 19 %
        de la watchlist surveillait dans le vide, sans que rien ne le signale.
        Ce n'est pas une erreur du moteur, c'est une declaration incomplete ;
        encore faut-il pouvoir la voir.
        """
        return not self.active or bool(self.selectors)


def _clean_selectors(selectors: list[SelectorIn]) -> list[EntitySelector]:
    return [
        EntitySelector(
            id=uuid.uuid4(),
            type=s.type.value,
            value=s.value.strip(),
            created_at=datetime.now(timezone.utc),
        )
        for s in selectors
        if s.value.strip()
    ]


class SectorOut(BaseModel):
    model_config = {"extra": "forbid"}

    value: str
    label: str
    # Secteur hautement critique de l'annexe I de NIS2 : il eleve la gravite.
    critical: bool


@router.get("/sectors", response_model=list[SectorOut])
def list_sectors() -> list[SectorOut]:
    """Vocabulaire des secteurs declarables (celui de ransomware.live, que lit
    la gravite NIS2), avec le libelle francais. Une seule source : le
    formulaire ne peut pas proposer un secteur que la gravite ignorerait."""
    from app.pipeline.alerting.rules import CRITICAL_SECTORS
    from app.pipeline.reporting.governance import SECTEURS_FR

    return sorted(
        (
            SectorOut(value=v, label=SECTEURS_FR[v], critical=v in CRITICAL_SECTORS)
            for v in entity_service.SECTEURS_DECLARABLES
        ),
        key=lambda s: s.label,
    )


@router.get("", response_model=list[EntityOut])
def list_entities(db: Session = Depends(get_db)) -> list[Entity]:
    return EntityRepository(db).list()


@router.post(
    "",
    response_model=EntityOut,
    status_code=201,
    dependencies=[Depends(exige_role(PEUT_ADMINISTRER))],
)
def create_entity(payload: EntityCreate, db: Session = Depends(get_db)) -> Entity:
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Le nom ne peut pas être vide.")

    try:
        entity_service.controler_parent(db, None, payload.parent_id)
        pays = entity_service.normaliser_pays(payload.country)
        secteur = entity_service.normaliser_secteur(payload.sector)
    except entity_service.EntityError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    entity = Entity(
        id=uuid.uuid4(),
        name=name,
        active=payload.active,
        parent_id=payload.parent_id,
        country=pays,
        sector=secteur,
        created_at=datetime.now(timezone.utc),
    )
    entity.selectors = _clean_selectors(payload.selectors)
    return EntityRepository(db).create(entity)


@router.patch(
    "/{entity_id}",
    response_model=EntityOut,
    dependencies=[Depends(exige_role(PEUT_ADMINISTRER))],
)
def update_entity(
    entity_id: uuid.UUID, payload: EntityUpdate, db: Session = Depends(get_db)
) -> Entity:
    repo = EntityRepository(db)
    entity = repo.get(entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="Entity not found")

    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Le nom ne peut pas être vide.")
        entity.name = name
    if payload.active is not None:
        entity.active = payload.active
    if payload.verification_method is not None:
        entity.verification_method = payload.verification_method.value
    if payload.verification_status is not None:
        entity.verification_status = payload.verification_status.value
        if payload.verification_status == VerificationStatus.VERIFIED:
            entity.verified_at = datetime.now(timezone.utc)
    champs = payload.model_fields_set
    try:
        if "parent_id" in champs:
            entity_service.controler_parent(db, entity.id, payload.parent_id)
            entity.parent_id = payload.parent_id
        if "country" in champs:
            entity.country = entity_service.normaliser_pays(payload.country)
        if "sector" in champs:
            entity.sector = entity_service.normaliser_secteur(payload.sector)
    except entity_service.EntityError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if payload.selectors is not None:
        entity = repo.replace_selectors(entity, _clean_selectors(payload.selectors))
    else:
        entity = repo.update(entity)
    if champs & {"country", "sector"}:
        # Les alertes de l'organisation reprennent aussitot la declaration.
        entity_service.reporter_sur_les_alertes(db, entity.id)
        db.refresh(entity)
    return entity


@router.delete(
    "/{entity_id}",
    status_code=204,
    dependencies=[Depends(exige_role(PEUT_ADMINISTRER))],
)
def delete_entity(entity_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    EntityRepository(db).delete(entity_id)


class SubdomainDiscoveryResponse(BaseModel):
    model_config = {"extra": "forbid"}

    queried_domains: list[str]
    discovered: list[str]


@router.post(
    "/{entity_id}/discover-subdomains",
    response_model=SubdomainDiscoveryResponse,
    dependencies=[Depends(exige_role(PEUT_ADMINISTRER))],
)
def discover_subdomains(
    entity_id: uuid.UUID, db: Session = Depends(get_db)
) -> SubdomainDiscoveryResponse:
    """Interroge crt.sh pour chaque selecteur `domain` deja declare sur
    l'entite (voir pipeline/enrich/subdomains.py et CONTRIBUTING.md §2 pour le
    perimetre -- noms de domaine uniquement, jamais de donnee d'exposition).
    Ne persiste rien : l'analyste choisit ensuite quels sous-domaines ajouter
    via PATCH /{entity_id} (champ selectors), voir CONTRIBUTING.md §9.3."""
    entity = EntityRepository(db).get(entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="Entity not found")

    queried_domains = [
        s.value for s in entity.selectors if s.type == SelectorType.DOMAIN.value
    ]
    if not queried_domains:
        raise HTTPException(
            status_code=400,
            detail="Cette entité n'a aucun sélecteur de type domaine à partir duquel chercher des sous-domaines.",
        )

    discovered: set[str] = set()
    for domain in queried_domains:
        try:
            discovered.update(find_subdomains(domain))
        except SubdomainLookupError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    already_declared = {s.value for s in entity.selectors}
    new_subdomains = sorted(discovered - already_declared)

    return SubdomainDiscoveryResponse(
        queried_domains=queried_domains, discovered=new_subdomains
    )


class IntelXCorroborationOut(BaseModel):
    model_config = {"extra": "forbid"}

    domain: str
    hit_count: int
    # True quand hit_count a atteint le plafond IntelX : le nombre est
    # alors sature et ne mesure rien (voir enrich/intelx.py). L'interface
    # doit lire "au moins N", jamais "N".
    is_truncated: bool = False
    buckets: dict[str, int]


class IntelXCorroborationResponse(BaseModel):
    model_config = {"extra": "forbid"}

    results: list[IntelXCorroborationOut]


@router.post(
    "/{entity_id}/corroborate-intelx",
    response_model=IntelXCorroborationResponse,
    dependencies=[Depends(exige_role(PEUT_ADMINISTRER))],
)
def corroborate_intelx(
    entity_id: uuid.UUID, db: Session = Depends(get_db)
) -> IntelXCorroborationResponse:
    """Interroge IntelX pour chaque selecteur `domain` deja declare sur
    l'entite (voir pipeline/enrich/intelx.py et CONTRIBUTING.md §2). Ne remonte
    qu'un comptage de correspondances par bucket, jamais le contenu des
    resultats -- ne persiste rien, purement informatif pour l'analyste."""
    if not settings.INTELX_API_KEY:
        raise HTTPException(
            status_code=503, detail="INTELX_API_KEY n'est pas configurée."
        )

    entity = EntityRepository(db).get(entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="Entity not found")

    queried_domains = [
        s.value for s in entity.selectors if s.type == SelectorType.DOMAIN.value
    ]
    if not queried_domains:
        raise HTTPException(
            status_code=400,
            detail="Cette entité n'a aucun sélecteur de type domaine à corroborer.",
        )

    results: list[IntelXCorroborationOut] = []
    for domain in queried_domains:
        try:
            result = corroborate_domain(domain, settings.INTELX_API_KEY)
        except IntelXLookupError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        results.append(
            IntelXCorroborationOut(
                domain=result.term,
                hit_count=result.hit_count,
                is_truncated=result.is_truncated,
                buckets=result.buckets,
            )
        )

    return IntelXCorroborationResponse(results=results)


_to_entity_contract = to_entity_contract


class OrganizationCandidateOut(BaseModel):
    model_config = {"extra": "forbid"}

    name: str
    count: int


@router.get("/candidates", response_model=list[OrganizationCandidateOut])
def list_organization_candidates(
    db: Session = Depends(get_db),
) -> list[OrganizationCandidateOut]:
    """Noms d'organisation detectes par NER (voir pipeline/detect/patterns/
    organization.py), tries par frequence, en excluant ceux deja couverts par
    une entite active existante (voir pipeline/alerting/candidates.py). Ne
    persiste rien : c'est a l'analyste de creer l'entite via POST /api/entities
    s'il juge le candidat pertinent (pas de creation automatique)."""
    entities = [_to_entity_contract(e) for e in EntityRepository(db).list_active()]
    raw_candidates = DetectionRepository(db).top_organization_candidates()
    new_candidates = filter_new_candidates(raw_candidates, entities)
    return [
        OrganizationCandidateOut(name=value_masked, count=count)
        for value_masked, _value_hash, count in new_candidates
    ]


class EntityDocumentsResponse(BaseModel):
    model_config = {"extra": "forbid"}

    total: int
    offset: int
    limit: int
    items: list[DocumentListItem]


@router.get("/candidates/documents", response_model=EntityDocumentsResponse)
def list_candidate_documents(
    name: str,
    db: Session = Depends(get_db),
    offset: int = 0,
    limit: int = 50,
) -> EntityDocumentsResponse:
    """Où une entité candidate est citée : les documents qui portent une
    détection ORGANIZATION de ce nom, avec leur source et leur date.

    ⚠️ Déclarée AVANT `/{entity_id}/documents` : sinon « candidates » serait lu
    comme un identifiant (422)."""
    ids = DetectionRepository(db).document_ids_for_value(
        DetectionType.ORGANIZATION.value, name
    )
    docs = RawDocumentRepository(db).list_by_ids(ids, offset=offset, limit=limit)
    source_repo = SourceRepository(db)
    source_names: dict[uuid.UUID, str | None] = {}
    for doc in docs:
        if doc.source_id not in source_names:
            source = source_repo.get(doc.source_id)
            source_names[doc.source_id] = source.name if source else None
    return EntityDocumentsResponse(
        total=len(ids),
        offset=offset,
        limit=limit,
        items=[_list_item(doc, source_names.get(doc.source_id)) for doc in docs],
    )


@router.get("/{entity_id}/documents", response_model=EntityDocumentsResponse)
def list_entity_documents(
    entity_id: uuid.UUID,
    db: Session = Depends(get_db),
    offset: int = 0,
    limit: int = 50,
) -> EntityDocumentsResponse:
    """Documents dont au moins une detection DOMAIN/EMAIL correspond a un
    selecteur de l'entite (voir pipeline/alerting/matching.py -- meme regle
    de rattachement que GET /api/stats/entities, par labels de domaine, jamais
    par sous-chaine). Le croisement se fait en memoire comme dans stats.py :
    aucune table de jointure entite<->document n'existe en base."""
    entity_model = EntityRepository(db).get(entity_id)
    if entity_model is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    entity = _to_entity_contract(entity_model)

    detection_repo = DetectionRepository(db)
    # Filtrage EN SQL plutot qu'en memoire (voir
    # alerting/matching.py::MATCHABLE_DETECTION_TYPES) : le `continue` qui
    # suivait ecartait jusqu'a 61 % des lignes chargees, apres qu'elles aient
    # consomme le plafond.
    rows = detection_repo.list_all(
        limit=_MAX_DETECTIONS_LOADED_FOR_MATCHING,
        types_=matchable_detection_types([entity]),
    )
    if len(rows) == _MAX_DETECTIONS_LOADED_FOR_MATCHING:
        logger.warning(
            "entities.documents: plafond de %s detections atteint -- la liste "
            "de documents rattaches est tronquee.",
            _MAX_DETECTIONS_LOADED_FOR_MATCHING,
        )
    matching_document_ids: set[uuid.UUID] = set()
    for row in rows:
        detection = DetectionContract(
            id=row.id,
            document_id=row.document_id,
            type=row.type,
            value_masked=row.value_masked,
            value_hash=row.value_hash,
            validated=row.validated,
            is_relevant=row.is_relevant,
            created_at=row.created_at,
        )
        if matching_entities(detection, [entity]):
            matching_document_ids.add(row.document_id)

    document_repo = RawDocumentRepository(db)
    ordered_ids = sorted(matching_document_ids)  # ordre stable avant pagination
    total = len(ordered_ids)
    docs = document_repo.list_by_ids(ordered_ids, offset=offset, limit=limit)

    source_repo = SourceRepository(db)
    source_names: dict[uuid.UUID, str | None] = {}
    for doc in docs:
        if doc.source_id not in source_names:
            source = source_repo.get(doc.source_id)
            source_names[doc.source_id] = source.name if source else None

    return EntityDocumentsResponse(
        total=total,
        offset=offset,
        limit=limit,
        items=[_list_item(doc, source_names.get(doc.source_id)) for doc in docs],
    )


class OrganizationCandidatesFilterRequest(BaseModel):
    model_config = {"extra": "forbid"}

    names: list[str]


class OrganizationCandidatesFilterResponse(BaseModel):
    model_config = {"extra": "forbid"}

    kept: list[str]


@router.post(
    "/candidates/filter-with-llm",
    response_model=OrganizationCandidatesFilterResponse,
    dependencies=[Depends(exige_role(PEUT_ADMINISTRER))],
)
async def filter_organization_candidates_with_llm(
    payload: OrganizationCandidatesFilterRequest,
) -> OrganizationCandidatesFilterResponse:
    """Passe les noms de `payload.names` (typiquement la liste retournee par
    GET /candidates) au LLM actuellement selectionne (voir
    api/routers/llm.py::get_selected_model) pour ecarter le bruit residuel du
    NER (vocabulaire de forum, acronymes, logiciels sans rapport -- voir
    core/llm/client.py::filter_organization_candidates) que le filtre
    deterministe de pipeline/detect/patterns/organization.py ne couvre pas.

    A la demande uniquement (bouton dedie cote UI) : ne modifie rien en base,
    l'analyste garde la main pour creer l'entite parmi les noms retenus."""
    try:
        kept = await filter_organization_candidates(get_selected_model(), payload.names)
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Echec de l'appel au modele: {exc}"
        ) from exc
    return OrganizationCandidatesFilterResponse(kept=kept)


class OrganizationBackfillJobStatus(BaseModel):
    model_config = {"extra": "forbid"}

    job_id: str
    status: str  # "running" | "done" | "error"
    total: int = 0
    done: int = 0
    created_count: int = 0
    error: str | None = None


ORGANIZATION_BACKFILL_JOB_TTL_SECONDS = 7200
_BACKFILL_BATCH_SIZE = 200


def _save_organization_backfill_status(
    job_id: str, status: OrganizationBackfillJobStatus
) -> None:
    get_redis().set(
        f"organization_backfill_job:{job_id}",
        status.model_dump_json(),
        ex=ORGANIZATION_BACKFILL_JOB_TTL_SECONDS,
    )


def _run_organization_backfill_job(job_id: str) -> None:
    """Tache de fond : fait tourner find_organizations sur chaque document
    deja collecte (voir pipeline/detect/patterns/organization.py), pour
    combler les documents ingeres avant l'ajout du detecteur ORGANIZATION a
    detect_all (voir registry.py, qui couvre deja les nouveaux documents).

    N'appelle pas detect_all (qui re-detecterait tous les autres types) --
    la dedup automatique de detect_all ne s'applique donc pas ici : chaque
    detection est verifiee individuellement via
    DetectionRepository.exists_for_document avant insertion, pour qu'un
    second lancement de ce backfill ne duplique rien."""
    status = OrganizationBackfillJobStatus(job_id=job_id, status="running")
    _save_organization_backfill_status(job_id, status)

    db = SessionLocal()
    try:
        document_repo = RawDocumentRepository(db)
        detection_repo = DetectionRepository(db)

        status.total = document_repo.count_all()
        _save_organization_backfill_status(job_id, status)

        offset = 0
        while True:
            documents = document_repo.list_all(
                offset=offset, limit=_BACKFILL_BATCH_SIZE
            )
            if not documents:
                break

            for document in documents:
                now = datetime.now(timezone.utc)
                new_detections = []
                for raw_match in find_organizations(document.content):
                    # Filtre sur le type : un meme nom peut exister sous un
                    # autre type avec le meme value_hash (voir
                    # DetectionRepository.exists_for_document).
                    if detection_repo.exists_for_document(
                        document.id,
                        raw_match.value_hash,
                        type_=DetectionType.ORGANIZATION.value,
                    ):
                        continue
                    new_detections.append(
                        DetectionContract(
                            id=uuid.uuid4(),
                            document_id=document.id,
                            type=DetectionType.ORGANIZATION,
                            value_masked=raw_match.value_masked,
                            value_hash=raw_match.value_hash,
                            validated=raw_match.validated,
                            is_relevant=document.matched_keywords is not None
                            and len(document.matched_keywords) > 0,
                            created_at=now,
                        )
                    )
                if new_detections:
                    detection_repo.save_all(new_detections)
                    status.created_count += len(new_detections)
                status.done += 1

            offset += _BACKFILL_BATCH_SIZE
            _save_organization_backfill_status(job_id, status)

        status.status = "done"
        _save_organization_backfill_status(job_id, status)
    except Exception as exc:
        logger.exception("Organization backfill job %s failed", job_id)
        status.status = "error"
        status.error = str(exc)
        _save_organization_backfill_status(job_id, status)
    finally:
        db.close()


@router.post(
    "/backfill-organizations",
    response_model=OrganizationBackfillJobStatus,
    status_code=202,
    dependencies=[Depends(exige_role(PEUT_ADMINISTRER))],
)
def start_organization_backfill(
    background_tasks: BackgroundTasks,
) -> OrganizationBackfillJobStatus:
    """Lance en tache de fond l'extraction NER sur tous les documents deja
    collectes (voir _run_organization_backfill_job). Suivre la progression via
    GET /backfill-organizations/{job_id}/status."""
    job_id = str(uuid.uuid4())
    status = OrganizationBackfillJobStatus(job_id=job_id, status="running")
    _save_organization_backfill_status(job_id, status)
    background_tasks.add_task(_run_organization_backfill_job, job_id)
    return status


@router.get(
    "/backfill-organizations/{job_id}/status",
    response_model=OrganizationBackfillJobStatus,
)
def get_organization_backfill_status(job_id: str) -> OrganizationBackfillJobStatus:
    raw = get_redis().get(f"organization_backfill_job:{job_id}")
    if raw is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return OrganizationBackfillJobStatus.model_validate_json(raw)
