"""Collecte des pastes publics de DoxByte (SPA Next.js) via son API JSON
interne, plutot que le rendu HTML.

Verifie manuellement avant d'ecrire ce module (voir conversation projet) :
la page d'accueil est une SPA pure (aucun contenu server-side, les lignes du
tableau de pastes n'ont pas de <a href> classique -- juste un onClick JS),
mais elle appelle en interne une API REST simple qui ne necessite PAS de
navigateur :
  - GET /api/pastes?search=&offset=N   -> liste paginee (30/page)
  - GET /api/pastes/detail?id=<uuid>   -> contenu complet d'un paste

Cette API est plus fiable qu'un parsing HTML+Playwright (donne un JSON
structure avec createdAt en ISO absolu, pas besoin de deviner un
selecteur CSS fragile) et evite le cout d'un navigateur headless."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urljoin

import requests

from app.pipeline.collect.politeness import polite_delay, with_retry
from app.pipeline.collect.tor import build_socks5_proxy_url
from app.pipeline.collect.useragents import pick_user_agent

logger = logging.getLogger(__name__)

_PAGE_SIZE = 30
_MAX_PAGES_SAFETY_CAP = 300
# Meme principe de fraicheur incrementale que les autres collecteurs de
# listing (xenforo_latest, mybb_latest, exilio404) : quelques pages recentes
# par cycle, pas tout l'historique (149 pastes existants au moment de
# l'ecriture de ce module).
DEFAULT_MAX_PAGES = 2


@dataclass(frozen=True)
class DoxBytePaste:
    id: str
    title: str
    author: str | None
    created_at: datetime | None
    # Contenu complet -- None si le fetch du detail a echoue/pas tente.
    content: str | None = None


def _build_session() -> requests.Session:
    session = requests.Session()
    proxy_url = build_socks5_proxy_url(resolve_via_proxy=True)
    session.proxies = {"http": proxy_url, "https": proxy_url}
    return session


def _is_onion(url: str) -> bool:
    return url.split("//", 1)[-1].split("/", 1)[0].endswith(".onion")


@with_retry
def _fetch_json(url: str) -> dict:
    polite_delay()
    session = _build_session()
    response = session.get(
        url,
        headers={"User-Agent": pick_user_agent()},
        timeout=70,
        verify=not _is_onion(url),
    )
    response.raise_for_status()
    return response.json()


def _parse_iso(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_paste_summary(raw: dict) -> DoxBytePaste:
    return DoxBytePaste(
        id=raw["id"],
        title=raw.get("title") or "(sans titre)",
        author=raw.get("createdBy"),
        created_at=_parse_iso(raw.get("createdAt")),
    )


def fetch_paste_content(base_url: str, paste_id: str) -> str | None:
    detail_url = urljoin(base_url, f"/api/pastes/detail?id={paste_id}")
    try:
        data = _fetch_json(detail_url)
    except Exception:
        logger.exception("DoxByte: echec recuperation du detail %s", paste_id)
        return None
    return data.get("content") or None


def fetch_recent_pastes(
    base_url: str,
    max_pages: int | None = DEFAULT_MAX_PAGES,
    *,
    fetch_bodies: bool = True,
) -> list[DoxBytePaste]:
    """Parcourt le listing public (`/api/pastes`) par pages de _PAGE_SIZE via
    `offset`, jusqu'a `max_pages` ou une page vide. Si `fetch_bodies=True`
    (par defaut), recupere aussi le contenu complet de chaque paste."""
    pastes: list[DoxBytePaste] = []
    page_count = 0
    offset = 0

    while True:
        page_count += 1
        if max_pages is not None and page_count > max_pages:
            break
        if page_count > _MAX_PAGES_SAFETY_CAP:
            logger.warning(
                "DoxByte: plafond de securite (%d pages) atteint", _MAX_PAGES_SAFETY_CAP
            )
            break

        list_url = urljoin(base_url, f"/api/pastes?search=&offset={offset}")
        try:
            data = _fetch_json(list_url)
        except Exception:
            logger.exception("DoxByte: echec recuperation %s, arret", list_url)
            break

        raw_pastes = data.get("pastes", [])
        if not raw_pastes:
            break
        pastes.extend(_parse_paste_summary(p) for p in raw_pastes)
        offset += _PAGE_SIZE

    if fetch_bodies:
        pastes = [
            (
                p
                if p.content is not None
                else _with_content(p, fetch_paste_content(base_url, p.id))
            )
            for p in pastes
        ]

    return pastes


def _with_content(paste: DoxBytePaste, content: str | None) -> DoxBytePaste:
    return DoxBytePaste(
        id=paste.id,
        title=paste.title,
        author=paste.author,
        created_at=paste.created_at,
        content=content,
    )
