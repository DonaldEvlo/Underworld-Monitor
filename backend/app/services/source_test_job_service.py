"""Test de disponibilite des sources en tache de fond (2026-09-11).

⚠️ Le test synchrone (`POST /test`) durait plusieurs minutes SANS AUCUN
RETOUR, et son resultat ne vivait que dans l'etat de la page : changer de
page, ou un onglet recharge par le navigateur, perdait le test en cours comme
le resultat (signale a l'usage). Meme patron que la collecte groupee : job de
fond, etat dans Redis mis a jour a chaque adresse testee, consultable par
identifiant ou via `latest` -- l'interface retrouve le dernier test en
revenant, sans rien avoir a memoriser.

Vivait dans le routeur `api/routers/sources.py`, deplace a l'identique le
2026-09-25 (un routeur ne porte pas de logique metier, CONTRIBUTING.md §3.3).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import cast

from pydantic import BaseModel

from app.core.cache import get_redis
from app.db.session import SessionLocal
from app.services.source_health_service import (
    SourceTestProgress,
    check_source_refs,
    load_sources,
)

logger = logging.getLogger(__name__)

# 24 h et non 2 h : un test lance en fin de matinee avait DISPARU l'apres-midi
# (constate le 2026-09-11), alors que l'ecran promet de retrouver le dernier
# test. L'age du test est affiche, un resultat ancien se lit comme tel.
SOURCE_TEST_JOB_TTL_SECONDS = 86400
SOURCE_TEST_STALE_SECONDS = 300
_SOURCE_TEST_LATEST_KEY = "source_test_job:latest"


class SourceTestEntryOut(BaseModel):
    source_id: str
    name: str
    url: str
    active: bool
    requires_js: bool = False
    # pending | reachable | unreachable | retrying | untested
    state: str
    http_status: int | None = None
    checked_at: datetime | None = None
    # Derniere collecte REUSSIE : fait foi quand le test n'est pas concluant
    # (source qui exige un navigateur).
    last_collected_at: datetime | None = None


class SourceTestJobStatus(BaseModel):
    job_id: str
    status: str  # running | done | error
    scope: str  # active | all | one
    phase: str = "first_pass"  # first_pass | retry | done
    total: int = 0
    first_pass_done: int = 0
    retry_total: int = 0
    retry_done: int = 0
    reachable: int = 0
    unreachable: int = 0
    entries: list[SourceTestEntryOut] = []
    started_at: datetime
    # Battement de coeur : un job « running » qui ne bouge plus depuis
    # SOURCE_TEST_STALE_SECONDS est un job mort (API redemarree en plein test).
    updated_at: datetime
    finished_at: datetime | None = None
    error: str | None = None


def _save_source_test_status(status: SourceTestJobStatus) -> None:
    get_redis().set(
        f"source_test_job:{status.job_id}",
        status.model_dump_json(),
        ex=SOURCE_TEST_JOB_TTL_SECONDS,
    )


def load_source_test_status(job_id: str) -> SourceTestJobStatus | None:
    raw = cast("str | None", get_redis().get(f"source_test_job:{job_id}"))
    return None if raw is None else SourceTestJobStatus.model_validate_json(raw)


def latest_source_test_id() -> str | None:
    raw = cast("str | bytes | None", get_redis().get(_SOURCE_TEST_LATEST_KEY))
    if raw is None:
        return None
    return raw.decode() if isinstance(raw, bytes) else str(raw)


def is_stale(status: SourceTestJobStatus) -> bool:
    age = (datetime.now(timezone.utc) - status.updated_at).total_seconds()
    return status.status == "running" and age > SOURCE_TEST_STALE_SECONDS


def with_stale_check(status: SourceTestJobStatus) -> SourceTestJobStatus:
    """Un job mort ne doit pas s'afficher « en cours » jusqu'a son expiration."""
    if is_stale(status):
        status.status = "error"
        status.error = (
            "Test interrompu (le service a probablement redémarré) — relancez-le."
        )
    return status


def running_test() -> SourceTestJobStatus | None:
    """Le test en cours, s'il y en a un vivant.

    ⚠️ Un seul test a la fois : deux tests simultanes doubleraient le trafic
    Tor pour une information identique (OPSEC §2.3, delais de politesse)."""
    latest_id = latest_source_test_id()
    if latest_id is None:
        return None
    current = load_source_test_status(latest_id)
    if current is not None and current.status == "running" and not is_stale(current):
        return current
    return None


def new_test_job(scope: str) -> SourceTestJobStatus:
    """Cree l'etat d'un nouveau test et le designe comme le dernier."""
    now = datetime.now(timezone.utc)
    status = SourceTestJobStatus(
        job_id=str(uuid.uuid4()),
        status="running",
        scope=scope,
        started_at=now,
        updated_at=now,
    )
    _save_source_test_status(status)
    get_redis().set(
        _SOURCE_TEST_LATEST_KEY, status.job_id, ex=SOURCE_TEST_JOB_TTL_SECONDS
    )
    return status


def _apply_progress(status: SourceTestJobStatus, progress: SourceTestProgress) -> None:
    status.phase = progress.phase
    status.total = progress.total
    status.first_pass_done = progress.first_pass_done
    status.retry_total = progress.retry_total
    status.retry_done = progress.retry_done
    status.reachable = progress.reachable
    status.unreachable = progress.unreachable
    status.entries = [SourceTestEntryOut(**vars(e)) for e in progress.entries]
    status.updated_at = datetime.now(timezone.utc)


def run_source_test_job(
    job_id: str, only_active: bool, source_id: uuid.UUID | None
) -> None:
    status = load_source_test_status(job_id)
    if status is None:
        return

    # Sources lues puis session FERMEE avant le reseau : le test dure des
    # minutes, une connexion base immobilisee d'autant priverait le pool.
    db = SessionLocal()
    try:
        refs = load_sources(
            db,
            only_active=only_active,
            source_ids=[str(source_id)] if source_id is not None else None,
        )
    except Exception as exc:
        logger.exception("Test de sources %s : lecture des sources en echec", job_id)
        status.status = "error"
        status.error = f"Lecture des sources impossible : {exc}"
        status.finished_at = datetime.now(timezone.utc)
        _save_source_test_status(status)
        return
    finally:
        db.close()

    def on_progress(progress: SourceTestProgress) -> None:
        _apply_progress(status, progress)
        _save_source_test_status(status)

    try:
        check_source_refs(refs, on_progress=on_progress)
        status.status = "done"
        status.phase = "done"
    except Exception as exc:
        logger.exception("Test de sources %s en echec", job_id)
        status.status = "error"
        status.error = f"Le test s'est interrompu : {exc}"
    now = datetime.now(timezone.utc)
    status.finished_at = now
    status.updated_at = now
    _save_source_test_status(status)
