"""Collecte de la categorie "Doxxing" d'Exilio404 (forum bresilien, moteur
Question2Answer), accessible sans compte -- verifie manuellement avant
d'ecrire ce module (voir conversation projet).

Q2A n'expose pas d'horodatage absolu sur le listing ni sur la page de
question (uniquement du texte relatif type "10 horas atras", meme
limitation que breachforums_guest) : `published_at` reste volontairement
None plutot que de parser un texte relatif fragile."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app.pipeline.collect.politeness import polite_delay, with_retry
from app.pipeline.collect.tor import build_socks5_proxy_url
from app.pipeline.collect.useragents import pick_user_agent

logger = logging.getLogger(__name__)

_MAX_PAGES_SAFETY_CAP = 300
# 20 questions par page (standard Q2A) -- meme principe de fraicheur
# incrementale que les autres collecteurs de listing (xenforo_latest,
# mybb_latest) : quelques pages par cycle, pas tout l'historique.
DEFAULT_MAX_PAGES = 2
_PAGE_SIZE = 20


@dataclass(frozen=True)
class Q2AQuestion:
    title: str
    question_url: str
    author: str | None
    # Corps de la question -- None si le fetch de la page individuelle a
    # echoue/pas tente.
    body: str | None = None


def _build_session() -> requests.Session:
    session = requests.Session()
    proxy_url = build_socks5_proxy_url(resolve_via_proxy=True)
    session.proxies = {"http": proxy_url, "https": proxy_url}
    return session


def _is_onion(url: str) -> bool:
    return url.split("//", 1)[-1].split("/", 1)[0].endswith(".onion")


@with_retry
def _fetch_html(url: str) -> str:
    polite_delay()
    session = _build_session()
    response = session.get(
        url,
        headers={"User-Agent": pick_user_agent()},
        timeout=70,
        verify=not _is_onion(url),
    )
    response.raise_for_status()
    return response.text


def _parse_question_item(item, base_url: str) -> Q2AQuestion | None:
    title_el = item.select_one(".qa-q-item-title a")
    if title_el is None or not title_el.get("href"):
        return None

    author_el = item.select_one(".qa-q-item-who-data a") or item.select_one(
        ".qa-q-item-who-data"
    )

    return Q2AQuestion(
        title=title_el.get_text(strip=True),
        question_url=urljoin(base_url, title_el["href"]),
        author=author_el.get_text(strip=True) if author_el else None,
    )


def parse_category_questions(html_text: str, base_url: str) -> list[Q2AQuestion]:
    """Extrait les questions listees dans une page de categorie
    (`.qa-q-list-item`, markup Question2Answer standard). Deduplique par URL
    de question."""
    soup = BeautifulSoup(html_text, "html.parser")
    seen_urls: set[str] = set()
    questions: list[Q2AQuestion] = []

    for item in soup.select(".qa-q-list-item"):
        question = _parse_question_item(item, base_url)
        if question is None or question.question_url in seen_urls:
            continue
        seen_urls.add(question.question_url)
        questions.append(question)

    return questions


def parse_question_body(html_text: str) -> str | None:
    """Extrait le texte de la question (`.qa-q-view-content`, markup Q2A
    standard) -- la question elle-meme, pas les reponses (voir docstring du
    module : perimetre volontairement limite a la question initiale, pas au
    fil de reponses)."""
    soup = BeautifulSoup(html_text, "html.parser")
    content = soup.select_one(".qa-q-view-content")
    if content is None:
        return None
    text = content.get_text(separator=" ", strip=True)
    return text or None


def fetch_question_body(question_url: str) -> str | None:
    try:
        html_text = _fetch_html(question_url)
    except Exception:
        logger.exception("Exilio404: echec recuperation du corps de %s", question_url)
        return None
    return parse_question_body(html_text)


def fetch_category_questions(
    category_url: str,
    max_pages: int | None = DEFAULT_MAX_PAGES,
    *,
    fetch_bodies: bool = True,
) -> list[Q2AQuestion]:
    """Parcourt une categorie Q2A (ex: /doxxing) en paginant via `?start=N`
    (N multiple de _PAGE_SIZE) jusqu'a `max_pages`, ou jusqu'a une page vide
    (fin de categorie). Si `fetch_bodies=True` (par defaut), recupere aussi
    le corps de chaque question -- le titre seul ne suffit pas a juger une
    question ambigue (meme principe que xenforo_latest/mybb_latest)."""
    questions: list[Q2AQuestion] = []
    page_count = 0
    start = 0

    while True:
        page_count += 1
        if max_pages is not None and page_count > max_pages:
            break
        if page_count > _MAX_PAGES_SAFETY_CAP:
            logger.warning(
                "Exilio404: plafond de securite (%d pages) atteint",
                _MAX_PAGES_SAFETY_CAP,
            )
            break

        page_url = category_url if start == 0 else f"{category_url}?start={start}"
        try:
            html_text = _fetch_html(page_url)
        except Exception:
            logger.exception("Exilio404: echec recuperation %s, arret", page_url)
            break

        page_questions = parse_category_questions(html_text, page_url)
        if not page_questions:
            break
        questions.extend(page_questions)
        start += _PAGE_SIZE

    if fetch_bodies:
        questions = [
            (
                q
                if q.body is not None
                else _with_body(q, fetch_question_body(q.question_url))
            )
            for q in questions
        ]

    return questions


def _with_body(question: Q2AQuestion, body: str | None) -> Q2AQuestion:
    return Q2AQuestion(
        title=question.title,
        question_url=question.question_url,
        author=question.author,
        body=body,
    )
