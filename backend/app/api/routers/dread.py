import json
import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.roles import PEUT_VOIR_LE_CORPUS
from app.api.deps import exige_role, get_db
from app.core.cache import get_redis
from app.pipeline.collect.dread.search import search_dread_for_keyword
from app.pipeline.collect.tor import renew_circuit
from app.repositories.keyword_repo import KeywordRepository
from app.repositories.source_repo import SourceRepository

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/dread-search",
    tags=["dread-search"],
    dependencies=[Depends(exige_role(PEUT_VOIR_LE_CORPUS))],
)

# Identifie la source Dread par son domaine onion (stable), plutôt que par son nom
# affiché (modifiable par l'analyste) — voir Sources pour la source enregistrée.
DREAD_ONION_DOMAIN = "dreadytofatroptsdj6io7l3xptbet6onoyno2yv7jicoxknyazubrad.onion"
JOB_TTL_SECONDS = 7200
# Chaque recherche instancie son propre navigateur Playwright headless (voir
# search.py) : un worker par mot-clé saturerait vite la machine avec 100+
# mots-cles actifs dans la watchlist. Meme ordre de grandeur que
# COLLECT_ALL_MAX_WORKERS (sources.py) pour un cout memoire/CPU comparable.
DREAD_SEARCH_MAX_WORKERS = 5


class DreadSearchHit(BaseModel):
    title: str
    link: str
    subdread: str | None = None
    author: str | None = None
    date: str | None = None
    snippet: str | None = None


class DreadKeywordResult(BaseModel):
    keyword: str
    success: bool
    hits: list[DreadSearchHit] = []
    error: str | None = None


class DreadSearchJobStatus(BaseModel):
    job_id: str
    status: str  # "running" | "done"
    total: int
    done: int
    items: list[DreadKeywordResult]


def _save_job_status(
    job_id: str, status: str, total: int, done: int, items: list[dict]
) -> None:
    get_redis().set(
        f"dread_search_job:{job_id}",
        json.dumps(
            {
                "job_id": job_id,
                "status": status,
                "total": total,
                "done": done,
                "items": items,
            }
        ),
        ex=JOB_TTL_SECONDS,
    )


def _search_one_keyword(base_url: str, keyword: str) -> dict:
    """Recherche un mot-clé, isolé pour tourner dans un thread du pool de
    `_run_dread_search_job` — jamais d'exception qui remonterait au thread
    principal, toujours un DreadKeywordResult serialisé (succès ou échec)."""
    try:
        hits = search_dread_for_keyword(base_url, keyword)
        return DreadKeywordResult(
            keyword=keyword,
            success=True,
            hits=[DreadSearchHit(**h) for h in hits],
        ).model_dump()
    except Exception as exc:
        logger.exception("Dread search failed for keyword %r", keyword)
        return DreadKeywordResult(
            keyword=keyword, success=False, error=str(exc)
        ).model_dump()


def _run_dread_search_job(job_id: str, base_url: str, keywords: list[str]) -> None:
    """Exécuté en tâche de fond : recherche chaque mot-clé actif de la
    Watchlist sur la recherche interne de Dread, EN PARALLÈLE (jusqu'à
    DREAD_SEARCH_MAX_WORKERS à la fois — la watchlist compte désormais 100+
    termes, une exécution séquentielle serait bien trop lente). Le circuit Tor
    n'est renouvelé qu'UNE FOIS avant de lancer tout le lot (pas par mot-clé,
    voir search.py) : toutes les recherches du lot partagent le même circuit,
    un renouvellement par recherche casserait les connexions en cours des
    autres recherches parallèles. Progression consultable via GET
    /{job_id}/status, indépendamment de l'onglet frontend ouvert ou non."""
    try:
        renew_circuit()
    except Exception:
        logger.warning(
            "Could not renew Tor circuit before Dread search batch, continuing with current circuit"
        )

    total = len(keywords)
    items: list[dict] = []
    items_lock = threading.Lock()
    _save_job_status(job_id, "running", total, 0, items)

    with ThreadPoolExecutor(max_workers=DREAD_SEARCH_MAX_WORKERS) as executor:
        futures = {
            executor.submit(_search_one_keyword, base_url, keyword): keyword
            for keyword in keywords
        }
        for future in as_completed(futures):
            item = future.result()
            with items_lock:
                items.append(item)
                done = len(items)
                _save_job_status(job_id, "running", total, done, list(items))

    _save_job_status(job_id, "done", total, total, items)


@router.post("/run", response_model=DreadSearchJobStatus)
def run_dread_search(
    background_tasks: BackgroundTasks, db: Session = Depends(get_db)
) -> DreadSearchJobStatus:
    """Démarre une recherche Dread pour chaque mot-clé actif de la Watchlist, en
    tâche de fond. Ne crée ni n'altère aucune source ni aucun document — se
    contente de remonter les fils/commentaires trouvés pour revue par l'analyste.
    """
    source = SourceRepository(db).find_by_url_contains(DREAD_ONION_DOMAIN)
    if source is None:
        raise HTTPException(
            status_code=404,
            detail="Source Dread introuvable — ajoutez-la dans Sources avant de lancer la recherche.",
        )

    keywords = KeywordRepository(db).get_active_terms()
    if not keywords:
        raise HTTPException(
            status_code=400, detail="Aucun mot-clé actif dans la Watchlist."
        )

    job_id = str(uuid.uuid4())
    _save_job_status(job_id, "running", len(keywords), 0, [])
    background_tasks.add_task(_run_dread_search_job, job_id, source.url, keywords)

    return DreadSearchJobStatus(
        job_id=job_id, status="running", total=len(keywords), done=0, items=[]
    )


@router.get("/{job_id}/status", response_model=DreadSearchJobStatus)
def get_dread_search_status(job_id: str) -> DreadSearchJobStatus:
    raw = get_redis().get(f"dread_search_job:{job_id}")
    if raw is None:
        raise HTTPException(
            status_code=404, detail="Job introuvable ou expiré (TTL 2h)."
        )
    return DreadSearchJobStatus(**json.loads(raw))
