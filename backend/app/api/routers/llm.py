import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.roles import PEUT_ADMINISTRER
from app.api.deps import exige_role
from app.core.cache import get_redis
from app.core.config import settings
from app.core.llm.client import generate_batch_response, generate_response
from app.core.llm.ollama_models import OllamaModel

router = APIRouter(
    prefix="/api/llm",
    tags=["llm"],
    dependencies=[Depends(exige_role(PEUT_ADMINISTRER))],
)

# Sélection en mémoire pour l'instant (pas de table dédiée en base tant que
# seules les sources y sont stockées). À déplacer en base si la persistance
# entre redémarrages devient nécessaire.
_selected_model: str = settings.LLM_MODEL


class LLMOption(BaseModel):
    id: str
    provider: str
    label: str
    available: bool


class LLMSelection(BaseModel):
    model_config = {"extra": "forbid"}

    model: str


class AnalyzeRequest(BaseModel):
    model_config = {"extra": "forbid"}

    content: str
    query: str
    model: str | None = None


class AnalyzeResponse(BaseModel):
    response: str


class AnalyzeBatchRequest(BaseModel):
    model_config = {"extra": "forbid"}

    batch_id: str
    query: str
    model: str | None = None


@router.get("/options", response_model=list[LLMOption])
def list_llm_options() -> list[LLMOption]:
    options = [
        LLMOption(
            id="gpt-4.1-mini",
            provider="openai",
            label="OpenAI GPT-4.1 mini",
            available=bool(settings.OPENAI_API_KEY),
        ),
        LLMOption(
            id="gemini-1.5-flash",
            provider="google",
            label="Google Gemini 1.5 Flash",
            available=bool(settings.GOOGLE_API_KEY),
        ),
    ]

    try:
        ollama_models = asyncio.run(OllamaModel.list_models())
    except Exception:
        ollama_models = []

    options += [
        LLMOption(
            id=f"ollama:{name}",
            provider="ollama",
            label=f"Ollama — {name}",
            available=True,
        )
        for name in ollama_models
    ]

    return options


def get_selected_model() -> str:
    """Accès public au modèle actuellement sélectionné, pour les autres routers
    (ex: search.py) — `_selected_model` reste privé à ce module."""
    return _selected_model


@router.get("/select", response_model=LLMSelection)
def get_selected_llm() -> LLMSelection:
    return LLMSelection(model=_selected_model)


@router.post("/select", response_model=LLMSelection)
def select_llm(payload: LLMSelection) -> LLMSelection:
    global _selected_model
    valid_ids = {opt.id for opt in list_llm_options()}
    if payload.model not in valid_ids:
        raise HTTPException(
            status_code=400, detail=f"Modèle inconnu ou indisponible: {payload.model}"
        )
    _selected_model = payload.model
    return LLMSelection(model=_selected_model)


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_content(payload: AnalyzeRequest) -> AnalyzeResponse:
    """Discussion / résumé à la demande sur un contenu déjà extrait (section
    Collecte). Jamais appelé automatiquement pendant la collecte elle-même."""
    model_name = payload.model or _selected_model
    try:
        text = await generate_response(model_name, payload.content, payload.query)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Échec de l'appel au modèle: {exc}"
        ) from exc
    return AnalyzeResponse(response=text)


@router.post("/analyze-batch", response_model=AnalyzeResponse)
async def analyze_batch(payload: AnalyzeBatchRequest) -> AnalyzeResponse:
    """Résumé/analyse page par page d'un lot collecté via POST /api/sources/collect-all.
    Les pages sont lues depuis Redis (stockage temporaire, TTL) par `batch_id`."""
    raw = get_redis().get(f"collect_batch:{payload.batch_id}")
    if raw is None:
        raise HTTPException(
            status_code=404,
            detail="Lot introuvable ou expiré (stockage temporaire Redis, TTL 1h).",
        )
    pages = json.loads(raw)
    if not pages:
        raise HTTPException(
            status_code=400, detail="Aucune page collectée avec succès dans ce lot."
        )

    model_name = payload.model or _selected_model
    try:
        text = await generate_batch_response(model_name, pages, payload.query)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Échec de l'appel au modèle: {exc}"
        ) from exc
    return AnalyzeResponse(response=text)
