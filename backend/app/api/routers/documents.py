import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from langdetect import LangDetectException, detect
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.roles import PEUT_ADMINISTRER, PEUT_VOIR_LE_CORPUS
from app.api.deps import exige_role, get_db
from app.db.models.raw_document import RawDocument
from app.pipeline.enrich.translate import TranslationUnavailableError, translate_text
from app.api.routers.llm import get_selected_model
from app.core.config import settings
from app.core.llm.client import generate_response
from app.repositories.document_repo import (
    DocumentSortBy,
    RawDocumentRepository,
    SortOrder,
)
from app.repositories.source_repo import SourceRepository
from app.services.uncertain_triage_service import (
    DEFAULT_MAX_DOCUMENTS,
    triage_uncertain_documents,
)

router = APIRouter(
    prefix="/api/documents",
    tags=["documents"],
    dependencies=[Depends(exige_role(PEUT_VOIR_LE_CORPUS))],
)

# Apercu de contenu pour la liste (evite de faire transiter des dizaines de Mo
# de `content`/`raw_html` juste pour afficher un tableau) -- le detail complet
# reste disponible via GET /api/documents/{id}.
LIST_PREVIEW_CHARS = 300


class DocumentListItem(BaseModel):
    id: uuid.UUID
    source_id: uuid.UUID
    source_name: str | None
    url: str
    content_preview: str
    title: str | None
    author: str | None
    source_type: str
    collector: str
    published_at: datetime | None
    fetched_at: datetime
    is_duplicate: bool
    matched_keywords: list[str] | None
    mentioned_url_count: int
    content_locked: bool
    # Verdict du classifieur d'annonces (detect/announcement_filter.py).
    # Il etait calcule et persiste depuis le 2026-08-28 mais n'etait expose
    # par aucune couche : l'analyste voyait une publicite de service
    # exactement comme une annonce de fuite. `announcement_reason` accompagne
    # le verdict parce qu'un classement sans motif n'est pas contestable.
    announcement_class: str | None
    announcement_reason: str | None


class DocumentListResponse(BaseModel):
    total: int
    offset: int
    limit: int
    items: list[DocumentListItem]


class DocumentDetail(BaseModel):
    id: uuid.UUID
    source_id: uuid.UUID
    source_name: str | None
    url: str
    content: str
    content_hash: str
    title: str | None
    author: str | None
    source_type: str
    collector: str
    collector_version: str
    published_at: datetime | None
    fetched_at: datetime
    raw_html: str | None
    source_meta: dict | None
    is_duplicate: bool
    matched_keywords: list[str] | None


def _list_item(doc: RawDocument, source_name: str | None) -> DocumentListItem:
    meta = doc.source_meta or {}
    mentioned_urls = meta.get("mentioned_urls")
    return DocumentListItem(
        id=doc.id,
        source_id=doc.source_id,
        source_name=source_name,
        url=doc.url,
        content_preview=doc.content[:LIST_PREVIEW_CHARS],
        title=doc.title,
        author=doc.author,
        source_type=doc.source_type,
        collector=doc.collector,
        published_at=doc.published_at,
        fetched_at=doc.fetched_at,
        is_duplicate=doc.is_duplicate,
        matched_keywords=doc.matched_keywords,
        mentioned_url_count=(
            len(mentioned_urls) if isinstance(mentioned_urls, list) else 0
        ),
        content_locked=meta.get("content_locked") is True,
        announcement_class=doc.announcement_class,
        announcement_reason=doc.announcement_reason,
    )


@router.get("", response_model=DocumentListResponse)
def list_documents(
    db: Session = Depends(get_db),
    source_id: uuid.UUID | None = None,
    collector: str | None = None,
    q: str | None = Query(
        default=None, description="Recherche dans le titre et le contenu"
    ),
    only_matched: bool = Query(
        default=False,
        description="Ne garder que les documents avec un mot-cle watchlist trouve",
    ),
    fetched_from: datetime | None = Query(
        default=None,
        description="Ne garder que les documents collectes a partir de cette date (incluse)",
    ),
    fetched_to: datetime | None = Query(
        default=None,
        description="Ne garder que les documents collectes jusqu'a cette date (incluse)",
    ),
    announcement_class: list[str] | None = Query(
        default=None,
        description=(
            "Ne garder que ces verdicts de classement (leak, uncertain, noise). "
            "Repetable. Par defaut : tous, y compris le bruit -- l'interface "
            "choisit d'ecarter le bruit et l'affiche explicitement."
        ),
    ),
    sort_by: DocumentSortBy = Query(
        default=DocumentSortBy.RELEVANCE, description="Champ de tri"
    ),
    sort_order: SortOrder = Query(default=SortOrder.DESC, description="Sens du tri"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> DocumentListResponse:
    repo = RawDocumentRepository(db)
    docs = repo.list_all(
        offset=offset,
        limit=limit,
        source_id=source_id,
        collector=collector,
        search=q,
        only_matched=only_matched,
        fetched_from=fetched_from,
        fetched_to=fetched_to,
        sort_by=sort_by,
        sort_order=sort_order,
        announcement_classes=announcement_class,
    )
    # Le meme filtre doit s'appliquer au total, sinon la pagination annonce
    # plus de documents qu'elle n'en sert.
    total = repo.count_all(
        source_id=source_id,
        collector=collector,
        search=q,
        only_matched=only_matched,
        fetched_from=fetched_from,
        fetched_to=fetched_to,
        announcement_classes=announcement_class,
    )

    source_repo = SourceRepository(db)
    source_names: dict[uuid.UUID, str] = {}
    for doc in docs:
        if doc.source_id not in source_names:
            source = source_repo.get(doc.source_id)
            source_names[doc.source_id] = source.name if source else None

    return DocumentListResponse(
        total=total,
        offset=offset,
        limit=limit,
        items=[_list_item(doc, source_names.get(doc.source_id)) for doc in docs],
    )


class DeleteAllResponse(BaseModel):
    deleted_count: int
    deleted_detections_count: int


@router.delete(
    "",
    response_model=DeleteAllResponse,
    dependencies=[Depends(exige_role(PEUT_ADMINISTRER))],
)
def delete_all_documents(db: Session = Depends(get_db)) -> DeleteAllResponse:
    """Vide entierement la base de collecte (raw_documents) ainsi que les
    detections qui en dependent (une detection n'existe que par rapport a un
    document en base). Les sources et la watchlist ne sont pas affectees."""
    deleted_count, deleted_detections_count = RawDocumentRepository(db).delete_all()
    return DeleteAllResponse(
        deleted_count=deleted_count, deleted_detections_count=deleted_detections_count
    )


class TranslateRequest(BaseModel):
    target_lang: str  # "fr" ou "en"


class TranslateResponse(BaseModel):
    source_lang: str
    target_lang: str
    translated_title: str | None
    translated_content: str


@router.post("/{document_id}/translate", response_model=TranslateResponse)
def translate_document(
    document_id: uuid.UUID, body: TranslateRequest, db: Session = Depends(get_db)
) -> TranslateResponse:
    """Traduit a la demande le titre et le contenu d'un document vers le francais
    ou l'anglais (bouton "Traduire" du panneau detail, voir CONTRIBUTING.md : LLM/inference
    hors chemin critique d'ingestion). La langue source est detectee automatiquement."""
    doc = RawDocumentRepository(db).get(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document introuvable")

    if body.target_lang not in ("fr", "en"):
        raise HTTPException(
            status_code=400, detail="target_lang doit etre 'fr' ou 'en'"
        )

    try:
        source_lang = detect(doc.content)
    except LangDetectException as exc:
        raise HTTPException(
            status_code=422,
            detail="Langue source indetectable (contenu trop court ou vide)",
        ) from exc

    try:
        translated_content = translate_text(doc.content, source_lang, body.target_lang)
        translated_title = (
            translate_text(doc.title, source_lang, body.target_lang)
            if doc.title
            else None
        )
    except TranslationUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return TranslateResponse(
        source_lang=source_lang,
        target_lang=body.target_lang,
        translated_title=translated_title,
        translated_content=translated_content,
    )


@router.get("/{document_id}", response_model=DocumentDetail)
def get_document(
    document_id: uuid.UUID, db: Session = Depends(get_db)
) -> DocumentDetail:
    doc = RawDocumentRepository(db).get(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document introuvable")

    source = SourceRepository(db).get(doc.source_id)
    return DocumentDetail(
        id=doc.id,
        source_id=doc.source_id,
        source_name=source.name if source else None,
        url=doc.url,
        content=doc.content,
        content_hash=doc.content_hash,
        title=doc.title,
        author=doc.author,
        source_type=doc.source_type,
        collector=doc.collector,
        collector_version=doc.collector_version,
        published_at=doc.published_at,
        fetched_at=doc.fetched_at,
        raw_html=doc.raw_html,
        source_meta=doc.source_meta,
        is_duplicate=doc.is_duplicate,
        matched_keywords=doc.matched_keywords,
    )


class TriageResponse(BaseModel):
    model_config = {"extra": "forbid"}

    submitted: int
    classified: int
    # Reponses ecartees parce que l'echo du titre ne concordait pas : le modele
    # avait decale ses numeros. Un rejet est un garde-fou qui a fonctionne, pas
    # une erreur -- ces documents seront represents.
    rejected: int
    counts: dict[str, int]
    model: str


@router.post("/triage-uncertain", response_model=TriageResponse)
async def triage_uncertain(
    limit: int = Query(default=DEFAULT_MAX_DOCUMENTS, ge=1, le=1000),
    model: str | None = Query(
        default=None,
        description="Modele a employer ; par defaut celui configure pour l'arbitrage",
    ),
    db: Session = Depends(get_db),
) -> TriageResponse:
    """Soumet au LLM les annonces que les REGLES n'ont pas su trancher.

    ⚠️ N'ecrase JAMAIS `announcement_class`. Le verdict du LLM est stocke a
    part (`llm_class`) : les regles restent maitresses du chemin critique parce
    qu'elles sont reproductibles, et l'on veut pouvoir comparer les deux
    lectures plutot que remplacer l'une par l'autre.

    Ne declenche aucune alerte et ne change rien au pipeline : `uncertain` est
    deja actionnable cote regles. Ce que ce travail ameliore, c'est le TRI et
    le corpus etiquete disponible pour l'apprentissage.
    """
    # Modele DEDIE a l'arbitrage, distinct de celui que l'analyste a choisi
    # pour le chat : le banc d'essai du 2026-09-03 donne 90 % de justesse a
    # qwen3 contre 60 % a llama3 sur cette tache precise.
    modele = model or settings.TRIAGE_LLM_MODEL
    rapport = await triage_uncertain_documents(db, model_name=modele, limit=limit)
    return TriageResponse(**rapport, model=modele)


class DocumentSummaryResponse(BaseModel):
    model_config = {"extra": "forbid"}

    document_id: uuid.UUID
    model: str
    summary: str
    # Longueur reelle du document et longueur reellement soumise : l'ecart doit
    # rester visible, sans quoi le lecteur croit que le resume porte sur tout.
    content_length: int
    submitted_length: int


# Longueur maximale soumise au modele.
#
# ⚠️ Le corpus contient un document de **735 797 caracteres** (mesure du
# 2026-09-03) : 95 depassent 8 000 et 17 depassent 30 000. Les envoyer entiers
# saturerait la fenetre de contexte d'un modele 8B et rendrait la reponse
# incoherente -- ou l'appel echouerait. On borne, et on ANNONCE la troncature
# au modele comme dans la reponse.
_MAX_SUMMARY_INPUT = 12_000

_SUMMARY_QUERY = (
    "Resume ce document en francais UNIQUEMENT (jamais un mot d'anglais), en "
    "5 phrases maximum, pour un analyste en renseignement sur les menaces.\n\n"
    "Precise si le document nomme une organisation victime, ce qui est "
    "annonce comme divulgue, et par qui.\n\n"
    "Regles impératives :\n"
    "- N'utilise QUE le texte fourni. N'invente aucun nom, chiffre ni date.\n"
    "- Si le texte est signale comme tronque, dis-le plutot que de conclure "
    "sur ce que tu n'as pas lu.\n"
    "- Si le document ne nomme aucune victime, dis-le simplement."
)


@router.post("/{document_id}/summarize", response_model=DocumentSummaryResponse)
async def summarize_document(
    document_id: uuid.UUID, db: Session = Depends(get_db)
) -> DocumentSummaryResponse:
    """Resume LLM d'un document collecte.

    Utile sur la traine longue du corpus : 95 documents depassent 8 000
    caracteres et le plus long en fait 735 797 -- illisibles tels quels dans un
    panneau de detail.

    A la demande uniquement, jamais pendant la collecte (CONTRIBUTING.md §3.4).
    """
    document = RawDocumentRepository(db).get(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    contenu = document.content or ""
    soumis = contenu[:_MAX_SUMMARY_INPUT]
    if len(contenu) > _MAX_SUMMARY_INPUT:
        soumis += (
            "\n\n[Texte tronque : seuls les "
            f"{_MAX_SUMMARY_INPUT} premiers caracteres sur {len(contenu)} "
            "sont fournis.]"
        )

    modele = get_selected_model()
    try:
        texte = await generate_response(
            modele, soumis, _SUMMARY_QUERY, temperature=settings.SUMMARY_LLM_TEMPERATURE
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Echec de l'appel au modele: {exc}"
        ) from exc

    return DocumentSummaryResponse(
        document_id=document.id,
        model=modele,
        summary=texte,
        content_length=len(contenu),
        submitted_length=len(soumis),
    )
