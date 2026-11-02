"""Routes des sources : CRUD, import/export, tests de disponibilite, collecte.

Ne contient plus que les routes et leurs schemas (2026-09-25). La logique qui
y vivait (1 095 lignes) a ete deplacee a l'identique :
  - choix du collecteur          -> pipeline/collect/routing.py
  - collecte groupee             -> services/collect_batch_service.py
  - import depuis GitHub         -> services/github_import_service.py
  - test de disponibilite (fond) -> services/source_test_job_service.py
  - detection de doublon d'URL   -> repositories/source_repo.find_duplicate
"""

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.roles import PEUT_ADMINISTRER, PEUT_VOIR_LE_CORPUS
from app.api.deps import exige_role, get_db
from app.contracts.source import SourceContract, SourceType
from app.core.url_utils import normalize_url
from app.db.models.source import Source
from app.pipeline.collect.onion_healthcheck import check_onion_entries
from app.pipeline.collect.routing import pick_collector
from app.pipeline.detect.keyword_match import find_keyword_matches
from app.repositories.keyword_repo import KeywordRepository
from app.repositories.source_repo import SourceRepository
from app.services.collect_batch_service import (
    BatchJobStatus,
    load_job_status,
    run_collect_all_job,
    save_job_status,
)

# Alias : l'endpoint HTTP de ce module s'appelle deja `collect_source`
# (POST /{source_id}/collect) -- importer le service sous son nom d'origine
# ecraserait silencieusement l'un des deux.
from app.services.collect_service import collect_source as run_collect_source
from app.services.github_import_service import (
    GithubImportJobStatus,
    load_github_import_status,
    run_github_import_job,
    save_github_import_status,
)
from app.services.source_health_service import check_sources
from app.services.source_test_job_service import (
    SourceTestJobStatus,
    load_source_test_status,
    latest_source_test_id,
    new_test_job,
    run_source_test_job,
    running_test,
    with_stale_check,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/sources",
    tags=["sources"],
    dependencies=[Depends(exige_role(PEUT_VOIR_LE_CORPUS))],
)

# Format d'export : versionne pour pouvoir faire evoluer le schema plus tard
# sans casser l'import d'anciens exports (on refuserait alors un format
# inconnu plutot que d'importer des donnees mal interpretees).
EXPORT_FORMAT = "threat-intel-platform.sources.v1"


class SourceCreate(BaseModel):
    model_config = {"extra": "forbid"}

    name: str
    type: SourceType
    url: str
    active: bool = True
    requires_js: bool = False


class SourceUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    name: str | None = None
    type: SourceType | None = None
    url: str | None = None
    active: bool | None = None
    requires_js: bool | None = None


class SourceExportItem(BaseModel):
    """Un seul champ id/created_at/last_collected_at volontairement absents :
    ce sont des donnees operationnelles de CETTE base, pas des attributs
    portables de la source -- un import ne doit jamais rejouer un id existant
    ni pretendre a une date de collecte qui n'a pas eu lieu ici."""

    model_config = {"extra": "forbid"}

    name: str
    type: SourceType
    url: str
    active: bool = True
    requires_js: bool = False


class SourceExportEnvelope(BaseModel):
    model_config = {"extra": "forbid"}

    format: str = EXPORT_FORMAT
    exported_at: datetime
    count: int
    sources: list[SourceExportItem]


class SourceImportError(BaseModel):
    name: str
    reason: str


class SourceImportResult(BaseModel):
    created: int
    skipped: int
    errors: list[SourceImportError] = []


class CollectResult(BaseModel):
    success: bool
    title: str | None = None
    text: str | None = None
    text_length: int | None = None
    matched_keywords: list[str] = []
    error: str | None = None
    saved_count: int = 0
    duration_seconds: int | None = None
    collector: str | None = None


class SourceHealthItemOut(BaseModel):
    source_id: str
    name: str
    url: str
    active: bool
    requires_js: bool = False
    reachable: bool
    http_status: int | None = None
    checked_at: datetime


class SourceHealthReportOut(BaseModel):
    checked: int
    reachable: int
    unreachable: int
    reachable_ratio: float
    items: list[SourceHealthItemOut]


class SourceTestJobRequest(BaseModel):
    only_active: bool = False
    source_id: uuid.UUID | None = None


@router.get("", response_model=list[SourceContract])
def list_sources(db: Session = Depends(get_db)) -> list[Source]:
    return SourceRepository(db).list()


@router.post(
    "",
    response_model=SourceContract,
    status_code=201,
    dependencies=[Depends(exige_role(PEUT_ADMINISTRER))],
)
def create_source(payload: SourceCreate, db: Session = Depends(get_db)) -> Source:
    repo = SourceRepository(db)
    duplicate = repo.find_duplicate(payload.url)
    if duplicate is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Une source pointe déjà vers cette adresse : « {duplicate.name} ».",
        )
    source = Source(
        id=uuid.uuid4(),
        name=payload.name,
        type=payload.type.value,
        url=payload.url,
        active=payload.active,
        requires_js=payload.requires_js,
        created_at=datetime.now(timezone.utc),
    )
    return repo.create(source)


@router.get("/export", response_model=SourceExportEnvelope)
def export_sources(db: Session = Depends(get_db)) -> SourceExportEnvelope:
    """Export portable des sources : uniquement les champs qu'on voudrait
    rejouer ailleurs (name/type/url/active/requires_js) -- pas d'id ni de
    date de collecte, propres a cette base."""
    sources = SourceRepository(db).list(limit=10_000)
    items = [
        SourceExportItem(
            name=s.name,
            type=SourceType(s.type),
            url=s.url,
            active=s.active,
            requires_js=s.requires_js,
        )
        for s in sources
    ]
    return SourceExportEnvelope(
        exported_at=datetime.now(timezone.utc), count=len(items), sources=items
    )


@router.post(
    "/import",
    response_model=SourceImportResult,
    dependencies=[Depends(exige_role(PEUT_ADMINISTRER))],
)
def import_sources(
    payload: SourceExportEnvelope, db: Session = Depends(get_db)
) -> SourceImportResult:
    """Importe un export produit par GET /export (ou un fichier au meme
    format). Idempotent : une source dont l'adresse existe deja (voir
    `SourceRepository.find_duplicate`) est ignoree plutot que dupliquee ou
    ecrasee -- l'import ne modifie jamais une source existante, il ne fait
    qu'ajouter les nouvelles."""
    if payload.format != EXPORT_FORMAT:
        raise HTTPException(
            status_code=400,
            detail=f"Format d'import non reconnu: {payload.format!r} (attendu: {EXPORT_FORMAT!r}).",
        )

    repo = SourceRepository(db)
    created, skipped, errors = 0, 0, []
    for item in payload.sources:
        if repo.find_duplicate(item.url) is not None:
            skipped += 1
            continue
        try:
            repo.create(
                Source(
                    id=uuid.uuid4(),
                    name=item.name,
                    type=item.type.value,
                    url=item.url,
                    active=item.active,
                    requires_js=item.requires_js,
                    created_at=datetime.now(timezone.utc),
                )
            )
            created += 1
        except Exception as exc:
            db.rollback()
            errors.append(SourceImportError(name=item.name, reason=str(exc)))

    return SourceImportResult(created=created, skipped=skipped, errors=errors)


@router.post(
    "/import-github",
    response_model=GithubImportJobStatus,
    status_code=202,
    dependencies=[Depends(exige_role(PEUT_ADMINISTRER))],
)
def import_sources_from_github(
    background_tasks: BackgroundTasks,
) -> GithubImportJobStatus:
    """Rafraichit la liste de forums depuis fastfire/deepdarkCTI (voir
    pipeline/collect/github_import.py) : ne garde que les adresses .onion pas
    deja en base, les teste via Tor, et cree une source (inactive par defaut)
    pour chaque nouvelle adresse joignable. Ne touche jamais aux sources
    existantes -- job de fond (le test de dizaines d'adresses via Tor peut
    prendre plusieurs minutes), suivre la progression via
    GET /import-github/{job_id}/status."""
    job_id = str(uuid.uuid4())
    save_github_import_status(
        job_id, GithubImportJobStatus(job_id=job_id, status="fetching")
    )
    background_tasks.add_task(run_github_import_job, job_id)
    return GithubImportJobStatus(job_id=job_id, status="fetching")


@router.get("/import-github/{job_id}/status", response_model=GithubImportJobStatus)
def get_github_import_status(job_id: str) -> GithubImportJobStatus:
    status = load_github_import_status(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Job introuvable ou expire")
    return status


@router.patch(
    "/{source_id}",
    response_model=SourceContract,
    dependencies=[Depends(exige_role(PEUT_ADMINISTRER))],
)
def update_source(
    source_id: uuid.UUID, payload: SourceUpdate, db: Session = Depends(get_db)
) -> Source:
    repo = SourceRepository(db)
    source = repo.get(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")

    if payload.url is not None and normalize_url(payload.url) != normalize_url(
        source.url
    ):
        duplicate = repo.find_duplicate(payload.url, exclude_id=source.id)
        if duplicate is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Une source pointe déjà vers cette adresse : « {duplicate.name} ».",
            )

    if payload.name is not None:
        source.name = payload.name
    if payload.type is not None:
        source.type = payload.type.value
    if payload.url is not None:
        source.url = payload.url
    if payload.active is not None:
        source.active = payload.active
    if payload.requires_js is not None:
        source.requires_js = payload.requires_js

    return repo.update(source)


@router.delete(
    "/{source_id}",
    status_code=204,
    dependencies=[Depends(exige_role(PEUT_ADMINISTRER))],
)
def delete_source(source_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    SourceRepository(db).delete(source_id)


@router.post(
    "/test",
    response_model=SourceHealthReportOut,
    dependencies=[Depends(exige_role(PEUT_ADMINISTRER))],
)
def test_all_sources(
    only_active: bool = False, db: Session = Depends(get_db)
) -> SourceHealthReportOut:
    """Teste la disponibilité de toutes les sources enregistrées, via Tor.

    Synchrone : le test est long (deux passes avec délai de politesse). Le
    front doit prévenir l'utilisateur plutôt que de laisser croire à un gel.

    Ne modifie AUCUNE source — désactiver une source morte reste une décision
    de l'analyste : un faux négatif (circuit Tor dégradé) désactiverait une
    source vivante, exactement le problème qu'on cherche à éviter."""
    report = check_sources(db, only_active=only_active)
    return SourceHealthReportOut(
        checked=report.checked,
        reachable=report.reachable,
        unreachable=report.unreachable,
        reachable_ratio=report.reachable_ratio,
        items=[SourceHealthItemOut(**vars(item)) for item in report.items],
    )


@router.post(
    "/{source_id}/test",
    response_model=SourceHealthItemOut,
    dependencies=[Depends(exige_role(PEUT_ADMINISTRER))],
)
def test_one_source(
    source_id: uuid.UUID, db: Session = Depends(get_db)
) -> SourceHealthItemOut:
    """Teste la disponibilité d'une source unique, via Tor."""
    source = SourceRepository(db).get(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")

    results = check_onion_entries([(source.name, source.url)])
    if not results:
        raise HTTPException(status_code=502, detail="Test impossible (aucun résultat)")

    result = results[0]
    return SourceHealthItemOut(
        source_id=str(source.id),
        name=source.name,
        url=source.url,
        active=source.active,
        requires_js=source.requires_js,
        reachable=result.reachable,
        http_status=result.http_status,
        checked_at=result.checked_at,
    )


@router.post(
    "/test-jobs",
    response_model=SourceTestJobStatus,
    status_code=202,
    dependencies=[Depends(exige_role(PEUT_ADMINISTRER))],
)
def start_source_test_job(
    payload: SourceTestJobRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> SourceTestJobStatus:
    """Lance un test de disponibilite en tache de fond (toutes les sources,
    les actives, ou une seule) et rend immediatement son etat.

    ⚠️ Un seul test a la fois : si un test tourne deja, c'est LUI qui est
    rendu, pas un second lance en parallele -- deux tests simultanes
    doubleraient le trafic Tor pour une information identique (OPSEC §2.3,
    delais de politesse).

    Ne modifie AUCUNE source (voir source_health_service)."""
    current = running_test()
    if current is not None:
        return current

    if (
        payload.source_id is not None
        and SourceRepository(db).get(payload.source_id) is None
    ):
        raise HTTPException(status_code=404, detail="Source not found")

    scope = (
        "one"
        if payload.source_id is not None
        else ("active" if payload.only_active else "all")
    )
    status = new_test_job(scope)
    background_tasks.add_task(
        run_source_test_job, status.job_id, payload.only_active, payload.source_id
    )
    return status


# ⚠️ Declaree AVANT `/test-jobs/{job_id}` : FastAPI resout dans l'ordre de
# declaration, « latest » serait sinon lu comme un identifiant.
@router.get("/test-jobs/latest", response_model=SourceTestJobStatus)
def get_latest_source_test_job() -> SourceTestJobStatus:
    """Dernier test lance (en cours ou termine depuis moins de 24 h)."""
    latest_id = latest_source_test_id()
    status = load_source_test_status(latest_id) if latest_id else None
    if status is None:
        raise HTTPException(status_code=404, detail="Aucun test récent")
    return with_stale_check(status)


@router.get("/test-jobs/{job_id}", response_model=SourceTestJobStatus)
def get_source_test_job(job_id: str) -> SourceTestJobStatus:
    status = load_source_test_status(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Test introuvable ou expiré (24 h)")
    return with_stale_check(status)


@router.post(
    "/{source_id}/collect",
    response_model=CollectResult,
    dependencies=[Depends(exige_role(PEUT_ADMINISTRER))],
)
def collect_source(
    source_id: uuid.UUID, db: Session = Depends(get_db)
) -> CollectResult:
    """Déclenche une collecte immédiate pour cette source (synchrone, hors
    Celery pour l'instant). Persiste les documents nouveaux en base (dedup
    exacte par content_hash) et fait tourner process/detect dessus -- voir
    RawDocumentRepository.save_new_documents."""
    repo = SourceRepository(db)
    source = repo.get(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")

    outcome = run_collect_source(pick_collector(source), repo, source)
    if not outcome.success or outcome.text is None:
        return CollectResult(success=False, error=outcome.error)

    keywords = KeywordRepository(db).get_active_terms()
    return CollectResult(
        success=True,
        text=outcome.text,
        text_length=len(outcome.text),
        matched_keywords=find_keyword_matches(outcome.text, keywords),
        saved_count=outcome.saved_count,
        collector=outcome.collector_name,
    )


@router.post(
    "/collect-all",
    response_model=BatchJobStatus,
    dependencies=[Depends(exige_role(PEUT_ADMINISTRER))],
)
def collect_all_sources(
    background_tasks: BackgroundTasks, db: Session = Depends(get_db)
) -> BatchJobStatus:
    """Démarre une collecte groupée en tâche de fond et retourne immédiatement un
    `batch_id`. La progression (X/N, résultat par source) se consulte via
    GET /collect-all/{batch_id}/status — le job continue côté serveur même si le
    frontend n'est pas en train de le regarder (onglet fermé, navigation ailleurs)."""
    source_ids = [str(s.id) for s in SourceRepository(db).get_active()]

    batch_id = str(uuid.uuid4())
    save_job_status(batch_id, "running", len(source_ids), 0, [], source_ids)
    background_tasks.add_task(run_collect_all_job, batch_id, source_ids)

    return BatchJobStatus(
        batch_id=batch_id, status="running", total=len(source_ids), done=0, items=[]
    )


@router.get("/collect-all/{batch_id}/status", response_model=BatchJobStatus)
def get_collect_all_status(batch_id: str) -> BatchJobStatus:
    status = load_job_status(batch_id)
    if status is None:
        raise HTTPException(
            status_code=404, detail="Job introuvable ou expiré (TTL 2h)."
        )
    return status
