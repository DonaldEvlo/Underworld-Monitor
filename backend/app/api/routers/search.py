from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from app.core.roles import PEUT_VOIR_LE_CORPUS
from app.api.deps import exige_role
from app.api.routers.llm import get_selected_model
from app.core.llm.client import filter_search_results, refine_search_query
from app.pipeline.collect.robin.query_search import search_all_engines

router = APIRouter(
    prefix="/api/search",
    tags=["search"],
    dependencies=[Depends(exige_role(PEUT_VOIR_LE_CORPUS))],
)


class SearchRequest(BaseModel):
    model_config = {"extra": "forbid"}

    query: str
    model: str | None = None


class SearchCandidate(BaseModel):
    title: str
    link: str
    engine: str


class SearchResponse(BaseModel):
    refined_query: str
    candidates: list[SearchCandidate]


@router.post("", response_model=SearchResponse)
async def search(payload: SearchRequest) -> SearchResponse:
    """Recherche des candidats de nouvelles sources à travers les moteurs de
    recherche onion (voir pipeline/collect/robin). Ne crée jamais de source
    automatiquement — l'analyste choisit lesquelles ajouter via POST /api/sources.
    """
    if not payload.query.strip():
        raise HTTPException(status_code=400, detail="La requête ne peut pas être vide.")

    model_name = payload.model or get_selected_model()

    try:
        refined = await refine_search_query(model_name, payload.query.strip())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Échec de l'appel au modèle: {exc}"
        ) from exc

    # `search_all_engines` est synchrone (ThreadPoolExecutor interne, ~20-40s) :
    # on la déporte dans le threadpool FastAPI pour ne pas geler la boucle asyncio
    # pendant ce temps (même piège que le premier jet de l'adapter de collecte).
    raw_results = await run_in_threadpool(
        search_all_engines, refined, payload.query.strip()
    )

    try:
        filtered = await filter_search_results(model_name, refined, raw_results)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Échec de l'appel au modèle: {exc}"
        ) from exc

    return SearchResponse(
        refined_query=refined,
        candidates=[SearchCandidate(**c) for c in filtered],
    )
