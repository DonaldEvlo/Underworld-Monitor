"""Collecte groupee (« Collecter tout ») en tache de fond, avec progression.

Vivait dans le routeur `api/routers/sources.py`, deplace a l'identique le
2026-09-25 : un routeur ne porte pas de logique metier (CONTRIBUTING.md §3.3).
Le routeur ne fait plus que lancer le job et en lire l'etat.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import cast

from pydantic import BaseModel

from app.core.cache import get_redis
from app.db.session import SessionLocal
from app.pipeline.collect.routing import pick_collector
from app.pipeline.detect.keyword_match import find_keyword_matches
from app.repositories.keyword_repo import KeywordRepository
from app.repositories.source_repo import SourceRepository
from app.services.collect_service import collect_source as run_collect_source

logger = logging.getLogger(__name__)

BATCH_TTL_SECONDS = 3600
JOB_TTL_SECONDS = 7200
PREVIEW_CHARS = 300

# Nombre de sources collectees en parallele lors d'un "collecter tout". Chaque
# source garde son propre delai de politesse interne (polite_delay entre ses
# requetes successives) -- ce plafond borne seulement le nombre de sources
# DIFFERENTES actives en meme temps, pas le rythme a l'interieur de chacune.
# Un seul circuit Tor est partage par le conteneur pour tout le batch (pas de
# renouvellement par source) : suffisant pour l'usage actuel, a revisiter si
# l'isolation de circuit par flux devient necessaire.
COLLECT_ALL_MAX_WORKERS = 5


class BatchItem(BaseModel):
    source_id: str
    name: str
    success: bool
    text_length: int | None = None
    text_preview: str | None = None
    matched_keywords: list[str] = []
    error: str | None = None
    saved_count: int = 0
    # Duree de collecte de CETTE source. Etait transmise sans que le
    # champ existe : Pydantic l'ignorait en silence et l'interface ne la
    # recevait jamais (trouve par mypy, 2026-09-25).
    duration_seconds: int | None = None
    collector: str | None = None


class BatchJobStatus(BaseModel):
    batch_id: str
    status: str  # "running" | "done"
    total: int
    done: int
    items: list[BatchItem]
    # Temps restant ESTIME, en secondes. `None` tant qu'aucune duree passee
    # n'est connue -- on prefere ne rien afficher qu'afficher un chiffre
    # invente.
    eta_seconds: int | None = None
    # Sur combien de sources l'estimation repose reellement. Affiche a cote
    # d'elle : une estimation batie sur 3 sources connues sur 24 ne vaut pas
    # celle batie sur 24, et le lecteur doit pouvoir en juger.
    eta_known_sources: int = 0
    eta_total_sources: int = 0


def calculer_eta(
    durees_restantes: list[int | None], durees_connues: list[int], parallelisme: int
) -> int | None:
    """Temps restant estime, en secondes. Fonction PURE, testable sans base.

    ⚠️ Divise par le parallelisme : les sources sont collectees jusqu'a
    `COLLECT_ALL_MAX_WORKERS` a la fois, une somme brute surestimerait donc
    d'un facteur 5.

    ⚠️ Renvoie `None` si AUCUNE duree passee n'est connue -- mieux vaut ne rien
    afficher qu'un chiffre invente.

    ⚠️ Une source jamais chronometree est estimee a la MEDIANE des durees
    connues, jamais a zero : sans cela une premiere collecte annoncerait
    « quelques secondes » avant de tourner une heure.
    """
    if not durees_connues:
        return None
    mediane = sorted(durees_connues)[len(durees_connues) // 2]
    total = sum(d if d is not None else mediane for d in durees_restantes)
    return max(0, round(total / max(1, parallelisme)))


def _estimer_temps_restant(source_ids: list[str], done_ids: set[str]) -> dict:
    """Charge les durees en base puis delegue le calcul a `calculer_eta`.

    L'estimation reste un ordre de grandeur : la duree d'une source .onion
    varie fortement d'une passe a l'autre (DARKNET ARMY entre 1292 et 1481 s,
    mesure du 2026-08-21).
    """
    db = SessionLocal()
    try:
        repo = SourceRepository(db)
        connues: list[int] = []
        restantes: list[int | None] = []
        for sid in source_ids:
            source = repo.get(uuid.UUID(sid))
            duree = source.last_collection_duration_seconds if source else None
            if duree is not None:
                connues.append(duree)
            if sid not in done_ids:
                restantes.append(duree)
    finally:
        db.close()

    return {
        "eta_seconds": calculer_eta(restantes, connues, COLLECT_ALL_MAX_WORKERS),
        # Le nombre de sources reellement chronometrees est expose : une
        # estimation batie sur 1 source sur 24 ne vaut pas celle batie sur 24.
        "eta_known_sources": len(connues),
        "eta_total_sources": len(source_ids),
    }


def save_job_status(
    batch_id: str,
    status: str,
    total: int,
    done: int,
    items: list[dict],
    source_ids: list[str] | None = None,
) -> None:
    corps = {
        "batch_id": batch_id,
        "status": status,
        "total": total,
        "done": done,
        "items": items,
    }
    # L'estimation n'a de sens que tant que le lot tourne : une fois termine,
    # afficher un « temps restant » serait absurde.
    if source_ids is not None and status == "running":
        traitees = {str(item.get("source_id")) for item in items}
        corps.update(_estimer_temps_restant(source_ids, traitees))
    get_redis().set(f"collect_job:{batch_id}", json.dumps(corps), ex=JOB_TTL_SECONDS)


def load_job_status(batch_id: str) -> BatchJobStatus | None:
    raw = cast("str | None", get_redis().get(f"collect_job:{batch_id}"))
    return None if raw is None else BatchJobStatus(**json.loads(raw))


def _collect_one_source_isolated(
    source_id: str, keywords: list[str]
) -> tuple[dict, dict | None]:
    """Collecte une source dans sa PROPRE session SQLAlchemy (une `Session` n'est
    pas thread-safe pour un usage concurrent) -- appele depuis un thread du pool
    de `run_collect_all_job`. Retourne (BatchItem serialise, page pour l'aperçu
    ou None)."""
    db = SessionLocal()
    try:
        repo = SourceRepository(db)
        source = repo.get(uuid.UUID(source_id))
        if source is None:
            return (
                BatchItem(
                    source_id=source_id,
                    name="?",
                    success=False,
                    error="Source introuvable",
                ).model_dump(),
                None,
            )

        outcome = run_collect_source(pick_collector(source), repo, source)
        if outcome.success and outcome.text:
            item = BatchItem(
                source_id=str(source.id),
                name=source.name,
                success=True,
                text_length=len(outcome.text),
                text_preview=outcome.text[:PREVIEW_CHARS],
                matched_keywords=find_keyword_matches(outcome.text, keywords),
                saved_count=outcome.saved_count,
                duration_seconds=outcome.duration_seconds,
                collector=outcome.collector_name,
            ).model_dump()
            return item, {
                "source_id": str(source.id),
                "name": source.name,
                "text": outcome.text,
            }

        item = BatchItem(
            source_id=str(source.id),
            name=source.name,
            success=False,
            error=outcome.error,
        ).model_dump()
        return item, None
    finally:
        db.close()


def run_collect_all_job(batch_id: str, source_ids: list[str]) -> None:
    """Exécuté en tâche de fond (voir BackgroundTasks dans collect_all_sources) :
    collecte les sources EN PARALLÈLE (jusqu'à COLLECT_ALL_MAX_WORKERS à la fois,
    chacune dans sa propre connexion DB) et met à jour l'état du job dans Redis
    après CHAQUE source terminée, pour une progression consultable en temps réel
    via GET /collect-all/{batch_id}/status — indépendamment de la page frontend
    ouverte ou non (la collecte continue même si l'onglet est fermé).

    Le délai de politesse et le rythme des requêtes restent inchangés À
    L'INTÉRIEUR de chaque source (voir `politeness.polite_delay`) : seul le
    nombre de sources DIFFÉRENTES traitées en même temps augmente."""
    db = SessionLocal()
    try:
        keywords = KeywordRepository(db).get_active_terms()
    finally:
        db.close()

    total = len(source_ids)
    items: list[dict] = []
    pages: list[dict] = []
    items_lock = threading.Lock()
    save_job_status(batch_id, "running", total, 0, items, source_ids)

    try:
        with ThreadPoolExecutor(max_workers=COLLECT_ALL_MAX_WORKERS) as executor:
            futures = {
                executor.submit(
                    _collect_one_source_isolated, source_id, keywords
                ): source_id
                for source_id in source_ids
            }
            for future in as_completed(futures):
                try:
                    item, page = future.result()
                except Exception:
                    logger.exception(
                        "Collecte parallele: echec inattendu pour la source %s",
                        futures[future],
                    )
                    item = BatchItem(
                        source_id=futures[future],
                        name="?",
                        success=False,
                        error="Erreur interne",
                    ).model_dump()
                    page = None

                with items_lock:
                    items.append(item)
                    if page is not None:
                        pages.append(page)
                    done = len(items)
                    save_job_status(
                        batch_id, "running", total, done, list(items), source_ids
                    )

        get_redis().set(
            f"collect_batch:{batch_id}", json.dumps(pages), ex=BATCH_TTL_SECONDS
        )
        save_job_status(batch_id, "done", total, total, items)
    except Exception:
        logger.exception("Batch collect job %s failed", batch_id)
        save_job_status(batch_id, "done", len(source_ids), len(source_ids), [])
