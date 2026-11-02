"""Import de nouvelles sources depuis deepdarkCTI (GitHub), en tache de fond.

Vivait dans le routeur `api/routers/sources.py`, deplace a l'identique le
2026-09-25 (un routeur ne porte pas de logique metier, CONTRIBUTING.md §3.3).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import cast

from pydantic import BaseModel

from app.contracts.source import SourceType
from app.core.cache import get_redis
from app.core.url_utils import normalize_url
from app.db.models.source import Source
from app.db.session import SessionLocal
from app.pipeline.collect.onion_healthcheck import check_onion_entries
from app.repositories.source_repo import SourceRepository

logger = logging.getLogger(__name__)

GITHUB_IMPORT_JOB_TTL_SECONDS = 7200


class GithubImportCreatedSource(BaseModel):
    name: str
    url: str
    http_status: int | None


class GithubImportJobStatus(BaseModel):
    job_id: str
    status: str  # "fetching" | "testing" | "done" | "error"
    total_parsed: int = 0
    new_candidates: int = 0
    tested: int = 0
    created: list[GithubImportCreatedSource] = []
    unreachable: int = 0
    error: str | None = None


def save_github_import_status(job_id: str, status: GithubImportJobStatus) -> None:
    get_redis().set(
        f"github_import_job:{job_id}",
        status.model_dump_json(),
        ex=GITHUB_IMPORT_JOB_TTL_SECONDS,
    )


def load_github_import_status(job_id: str) -> GithubImportJobStatus | None:
    raw = cast("str | None", get_redis().get(f"github_import_job:{job_id}"))
    return None if raw is None else GithubImportJobStatus.model_validate_json(raw)


def run_github_import_job(job_id: str) -> None:
    """Tache de fond : recupere forum.md depuis GitHub, ne garde que les
    adresses .onion pas deja en base, les teste via Tor, et cree une `Source`
    (type=forum, active=False -- selection manuelle avant collecte, voir
    CONTRIBUTING.md §2) pour chaque nouvelle adresse joignable.
    Ne touche jamais aux sources deja existantes."""
    from app.pipeline.collect.github_import import fetch_all_lists, find_new_candidates
    from app.pipeline.collect.onion_healthcheck import parse_onion_entries_from_text

    status = GithubImportJobStatus(job_id=job_id, status="fetching")
    save_github_import_status(job_id, status)

    db = SessionLocal()
    try:
        try:
            markdown_text = fetch_all_lists()
        except Exception as exc:
            status.status = "error"
            status.error = f"Echec de recuperation des listes depuis GitHub : {exc}"
            save_github_import_status(job_id, status)
            return

        repo = SourceRepository(db)
        existing_normalized = {normalize_url(s.url) for s in repo.list(limit=10_000)}
        candidates = find_new_candidates(
            markdown_text, existing_normalized, normalize_url
        )

        status.total_parsed = len(parse_onion_entries_from_text(markdown_text))
        status.new_candidates = len(candidates)
        status.status = "testing"
        save_github_import_status(job_id, status)

        if not candidates:
            status.status = "done"
            save_github_import_status(job_id, status)
            return

        results = check_onion_entries(candidates)
        for result in sorted(results, key=lambda r: r.name):
            status.tested += 1
            if not result.reachable:
                status.unreachable += 1
                save_github_import_status(job_id, status)
                continue

            # Re-verifier au cas ou une source identique aurait ete ajoutee
            # entre temps (import concurrent, ou create_source manuel) --
            # ne jamais dupliquer.
            if repo.find_duplicate(result.url) is not None:
                save_github_import_status(job_id, status)
                continue

            source = Source(
                id=uuid.uuid4(),
                name=result.name,
                type=SourceType.FORUM.value,
                url=result.url,
                active=False,  # selection manuelle avant collecte
                requires_js=False,
                created_at=datetime.now(timezone.utc),
            )
            repo.create(source)
            status.created.append(
                GithubImportCreatedSource(
                    name=result.name, url=result.url, http_status=result.http_status
                )
            )
            save_github_import_status(job_id, status)

        status.status = "done"
        save_github_import_status(job_id, status)
    except Exception as exc:
        logger.exception("Github import job %s failed", job_id)
        status.status = "error"
        status.error = str(exc)
        save_github_import_status(job_id, status)
    finally:
        db.close()
