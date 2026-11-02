"""Orchestration de la verification de vivacite des liens mentionnes dans les
documents collectes (voir pipeline/enrich/link_health.py).

Repond a "les annonces collectees sont-elles fiables ?" : un post qui promet un
dump derriere un lien mort n'a pas la meme valeur qu'un post dont le lien
repond encore. Mesure la credibilite d'une ANNONCE, jamais le contenu de ce
qu'elle promet -- aucun corps de reponse n'est rapatrie (voir link_health.py).

Volontairement separe du chemin de collecte : pipeline/collect/link_extraction.py
reste passif par conception (il extrait, il ne requete jamais). Greffer la
verification dans le collecteur en ferait un crawler recursif, ce que ce
module refuse explicitement. La verification est donc une passe distincte, sur
le corpus deja collecte -- planifiable (voir worker/tasks/link_tasks.py) sans
changer la nature de la collecte.

Ne persiste rien : le resultat est retourne a l'appelant (API) qui l'affiche.
Conforme au choix "a la demande, sans persistance" -- pas de table, pas de
migration, et surtout aucune metadonnee de lien tiers conservee en base."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.db.models.raw_document import RawDocument
from app.pipeline.collect.link_extraction import extract_mentioned_urls
from app.pipeline.enrich.link_health import (
    LinkHealthResult,
    LinkStatus,
    check_links,
)

logger = logging.getLogger(__name__)

# Plafond de securite : borne le trafic sortant d'une execution, meme si le
# corpus grossit. A 152 hotes uniques sur le corpus reel actuel, on est loin
# du plafond -- il n'existe que pour qu'une croissance du corpus ne se
# traduise pas silencieusement en martelage de sources.
_MAX_HOSTS_PER_RUN = 300


@dataclass(frozen=True)
class LinkHealthReport:
    """Resultats + comptages agreges. Les comptages sont l'interet principal
    pour juger de la fiabilite du corpus ; le detail sert a l'analyste."""

    results: list[LinkHealthResult]
    documents_scanned: int
    documents_with_links: int
    hosts_checked: int
    counts_by_status: dict[str, int]

    @property
    def alive_ratio(self) -> float | None:
        """Part des hotes joignables parmi ceux verifies. `None` si rien n'a
        ete verifie (pas 0.0 : "aucune mesure" n'est pas "tout est mort")."""
        if not self.hosts_checked:
            return None
        alive = self.counts_by_status.get(LinkStatus.ALIVE.value, 0)
        return alive / self.hosts_checked


def _collect_urls(
    db: Session, *, source_id=None, limit_documents: int | None = None
) -> tuple[list[str], int, int]:
    """Extrait les URLs mentionnees dans les documents (passivement, voir
    link_extraction.py). Retourne (urls, documents_scannes, documents_avec_liens)."""
    query = db.query(RawDocument.url, RawDocument.content)
    if source_id is not None:
        query = query.filter(RawDocument.source_id == source_id)
    if limit_documents is not None:
        query = query.order_by(RawDocument.fetched_at.desc()).limit(limit_documents)

    urls: list[str] = []
    documents_scanned = 0
    documents_with_links = 0
    for document_url, content in query.all():
        documents_scanned += 1
        found = extract_mentioned_urls(content or "", exclude_url=document_url)
        if found:
            documents_with_links += 1
        urls.extend(found)
    return urls, documents_scanned, documents_with_links


def check_corpus_links(
    db: Session, *, source_id=None, limit_documents: int | None = None
) -> LinkHealthReport:
    """Verifie la vivacite des liens mentionnes dans le corpus.

    `source_id` restreint a une source, `limit_documents` aux N documents les
    plus recents -- les deux servent a borner une execution manuelle ; l'appel
    planifie (worker) les laisse a None pour couvrir tout le corpus.

    La deduplication par hote est faite dans check_links : un hebergeur cite
    dans 154 documents n'est interroge qu'une fois."""
    urls, documents_scanned, documents_with_links = _collect_urls(
        db, source_id=source_id, limit_documents=limit_documents
    )

    # Deduplication par hote appliquee ici aussi, en amont du plafond : sans
    # elle, _MAX_HOSTS_PER_RUN tronquerait une liste pleine de doublons et on
    # verifierait 300 fois le meme hebergeur au lieu de 300 hotes distincts.
    seen_hosts: set[str] = set()
    unique_by_host: list[str] = []
    for url in urls:
        host = (urlparse(url).hostname or "").lower()
        if not host or host in seen_hosts:
            continue
        seen_hosts.add(host)
        unique_by_host.append(url)

    truncated = unique_by_host[:_MAX_HOSTS_PER_RUN]
    if len(unique_by_host) > _MAX_HOSTS_PER_RUN:
        logger.warning(
            "Verification de liens tronquee: %d hotes uniques, plafond %d",
            len(unique_by_host),
            _MAX_HOSTS_PER_RUN,
        )

    results = check_links(truncated)

    counts_by_status: dict[str, int] = {}
    for result in results:
        counts_by_status[result.status.value] = (
            counts_by_status.get(result.status.value, 0) + 1
        )

    logger.info(
        "Verification de liens: %d document(s), %d hote(s) verifie(s), %s",
        documents_scanned,
        len(results),
        counts_by_status,
    )

    return LinkHealthReport(
        results=results,
        documents_scanned=documents_scanned,
        documents_with_links=documents_with_links,
        hosts_checked=len(results),
        counts_by_status=counts_by_status,
    )
