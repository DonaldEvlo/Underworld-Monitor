"""Soumet au LLM les annonces que les REGLES n'ont pas su trancher.

Le classifieur rend trois verdicts et le troisieme, `uncertain`, existe pour ne
rien jeter en silence. Il attendait depuis le 2026-08-28 qu'un LLM le tranche :
728 documents, 18 % du corpus.

⚠️ Ce que ce service N'EST PAS : il ne modifie jamais `announcement_class`, ne
declenche aucune alerte et ne change rien au pipeline. Il ajoute une seconde
lecture, consultable et comparable a celle des regles. `uncertain` reste par
ailleurs *actionnable* cote regles -- ces documents alimentaient deja la
detection, ce travail ameliore le TRI et fournit le corpus etiquete qui manque
a `pipeline/classify/` (l'entrainement exclut `uncertain` : sans arbitrage, ces
728 lignes sont perdues pour le modele).

⚠️ Jamais sur le chemin d'ingestion (CONTRIBUTING.md §3.4 : le LLM reste en bout de
pipeline, en batch). Une classification non reproductible a l'ingestion rendrait
les alertes invérifiables.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.llm.client import generate_response
from app.db.models.raw_document import RawDocument
from app.pipeline.classify.llm_triage import (
    DEFAULT_BATCH_SIZE,
    TRIAGE_QUERY,
    TriageItem,
    build_triage_prompt,
    parse_triage_response,
)
from app.pipeline.detect.announcement_filter import source_publishes_victims

logger = logging.getLogger(__name__)

# Plafond par execution. A ~15 s pour 20 documents (mesure du 2026-09-03 avec
# llama3 local), 200 represente environ 2,5 minutes -- assez pour avancer, assez
# court pour ne pas monopoliser le modele, que l'analyste utilise aussi
# interactivement.
DEFAULT_MAX_DOCUMENTS = 200


async def triage_uncertain_documents(
    db: Session,
    *,
    model_name: str,
    limit: int = DEFAULT_MAX_DOCUMENTS,
    document_ids: list | None = None,
) -> dict:
    """Classe les documents `uncertain` encore sans verdict LLM.

    `document_ids` restreint le travail a ces documents -- utilise par les
    tests pour ne pas soumettre au modele les milliers de lignes reelles de la
    base d'integration.
    """
    query = db.query(RawDocument).filter(
        RawDocument.announcement_class == "uncertain",
        RawDocument.llm_class.is_(None),
    )
    if document_ids is not None:
        query = query.filter(RawDocument.id.in_(document_ids))
    documents = query.limit(limit).all()

    if not documents:
        return {"submitted": 0, "classified": 0, "rejected": 0, "counts": {}}

    classes = 0
    rejets = 0
    comptes: dict[str, int] = {}
    maintenant = datetime.now(timezone.utc)

    for depart in range(0, len(documents), DEFAULT_BATCH_SIZE):
        lot = documents[depart : depart + DEFAULT_BATCH_SIZE]
        items = [
            TriageItem(
                key=str(doc.id),
                title=doc.title or "",
                content=doc.content or "",
                source_publishes_victims=source_publishes_victims(doc.collector),
            )
            for doc in lot
        ]
        try:
            reponse = await generate_response(
                model_name,
                build_triage_prompt(items),
                TRIAGE_QUERY,
                temperature=settings.TRIAGE_LLM_TEMPERATURE,
            )
        except Exception:  # noqa: BLE001 - un lot perdu n'arrete pas la passe
            # Le document reste sans verdict et sera represente : ne rien
            # ecrire vaut mieux qu'ecrire une valeur par defaut, qui serait
            # indiscernable d'un vrai verdict.
            logger.exception("triage LLM : lot en echec, documents laisses en attente")
            continue

        verdicts, rejetes = parse_triage_response(reponse, items)
        rejets += rejetes

        for doc in lot:
            verdict = verdicts.get(str(doc.id))
            if verdict is None:
                continue
            doc.llm_class = verdict.verdict
            doc.llm_reason = verdict.reason[:255] or None
            doc.llm_model = model_name
            doc.llm_classified_at = maintenant
            comptes[verdict.verdict] = comptes.get(verdict.verdict, 0) + 1
            classes += 1

    db.commit()
    logger.info(
        "triage LLM : %s soumis, %s classes, %s rejetes pour desalignement (%s)",
        len(documents),
        classes,
        rejets,
        comptes,
    )
    return {
        "submitted": len(documents),
        "classified": classes,
        # Un rejet n'est pas un echec silencieux : c'est une reponse dont
        # l'echo de titre ne concordait pas, donc ecartee volontairement.
        "rejected": rejets,
        "counts": comptes,
    }
