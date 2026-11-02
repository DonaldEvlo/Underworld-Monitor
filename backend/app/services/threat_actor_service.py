"""Qui frappe où : classement des groupes par région (voir
pipeline/reporting/threat_actors.py).

Lit les historiques ransomware.live DÉJÀ en cache (aucun appel réseau, même
source que la menace mondiale de la Gouvernance) et la liste de nos sources
actives, pour marquer les groupes dont nous lisons réellement le site.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.pipeline.collect.routing import publishes_victims
from app.pipeline.enrich.geo import continent_for_country
from app.pipeline.enrich.ransomlook_corroboration import gang_slug_for_source
from app.pipeline.reporting.threat_actors import actors_by_region
from app.repositories.source_repo import SourceRepository
from app.services.governance_service import _continents, victimes_en_cache


def groupes_collectes(db: Session) -> set[str]:
    """Identifiants des groupes dont un site de fuite est ACTIVEMENT collecté.

    ⚠️ Vérifié le 2026-10-05 : les 17 sites actifs ont leur identifiant exact
    dans le cache ransomware.live (`gang_slug_for_source`, la règle de la
    corroboration). Une source inactive ne compte pas : nous ne la lisons
    plus."""
    slugs: set[str] = set()
    for source in SourceRepository(db).get_active():
        try:
            if not publishes_victims(source):
                continue
        except Exception:  # noqa: BLE001 -- une source mal formée ne bloque rien
            continue
        slug = gang_slug_for_source(source.name)
        if slug:
            slugs.add(slug)
    return slugs


def threat_actors(
    db: Session,
    *,
    continent: str | None = None,
    country: str | None = None,
    months: int = 12,
    now: datetime | None = None,
) -> dict:
    victimes, gangs = victimes_en_cache()
    resultat = actors_by_region(
        victimes,
        continent_de=continent_for_country,
        now=now or datetime.now(timezone.utc),
        months=months,
        continent=continent,
        country=country,
        collected=groupes_collectes(db),
    )
    # La couverture accompagne TOUJOURS le classement : un groupe absent du
    # cache est absent du classement, sans que cela dise qu'il est inactif.
    resultat["coverage_gangs"] = len(gangs)
    resultat["highlighted"] = list(_continents())
    resultat["computed_at"] = datetime.now(timezone.utc).isoformat()
    return resultat
