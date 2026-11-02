"""Test de disponibilite des sources enregistrees en base.

Repond a "mes sources repondent-elles encore ?" : sur un corpus de sources
.onion, une part meurt en permanence (site ferme, adresse changee, saisie).
Sans test, une source morte reste `active` et echoue silencieusement a chaque
cycle -- le seul symptome est une absence de nouveaux documents, qu'on peut
confondre avec "il ne se passe rien sur cette source".

Reutilise `pipeline/collect/onion_healthcheck.check_onion_entries`, deja
utilise par l'import GitHub : meme logique en deux passes (la seconde apres
renouvellement du circuit Tor) pour ne pas confondre une source hors service
avec un circuit Tor degrade -- distinction qui compte, un faux negatif
pousserait a desactiver une source parfaitement vivante.

Ne persiste rien et ne modifie AUCUNE source : le resultat est retourne a
l'appelant, qui l'affiche. Desactiver une source morte reste une decision de
l'analyste (PATCH /api/sources/{id}) -- une desactivation automatique sur un
faux negatif ferait perdre une source silencieusement, exactement le probleme
qu'on cherche a resoudre.

⚠️ LIMITE CONNUE, mesuree le 2026-08-21 : ce test utilise `requests` (client
HTTP simple), alors que certains collecteurs utilisent Playwright (navigateur
complet). Un site qui exige du JS ou filtre les clients non-navigateur
apparaitra donc `reachable=false` alors qu'il se collecte parfaitement --
constate sur Dread, injoignable en `requests` (http ET https) le jour meme ou
le collecteur en ramenait 145 fils.

`reachable=false` signifie donc « ne repond pas a une requete HTTP simple »,
PAS « source morte ». C'est utile pour reperer une adresse changee ou un
service eteint, mais un resultat negatif sur une source `requires_js` doit
etre lu comme non concluant. Ne pas « corriger » en lancant Playwright ici :
le test deviendrait aussi lent qu'une collecte et perdrait son interet.

SUIVI DE PROGRESSION (2026-09-11) : un test dure plusieurs minutes et ne
rendait rien avant la fin -- l'analyste ne savait ni ou il en etait, ni si la
seconde passe avait lieu. `check_source_refs` publie desormais un
`SourceTestProgress` a chaque adresse testee. Les sources sont lues AVANT le
reseau (`load_sources`) pour que l'appelant puisse fermer sa session : garder
une connexion base ouverte pendant tout le test immobiliserait le pool.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from app.pipeline.collect.onion_healthcheck import OnionCheckResult, check_onion_entries
from app.repositories.source_repo import SourceRepository

logger = logging.getLogger(__name__)

# Plafond de securite : borne le trafic sortant d'une execution meme si le
# nombre de sources grossit. Le test passe par Tor avec delai de politesse,
# une execution sur 200 sources durerait deja plusieurs minutes.
MAX_SOURCES_CHECKED = 200

# Etats d'une source pendant un test.
PENDING = "pending"  # pas encore testee
REACHABLE = "reachable"
UNREACHABLE = "unreachable"
RETRYING = "retrying"  # echec en 1re passe, retestee apres renouvellement du circuit
UNTESTED = "untested"  # aucun resultat obtenu (ne devrait pas arriver)


@dataclass(frozen=True)
class SourceRef:
    """Ce qu'il faut savoir d'une source pour la tester -- detache de la
    session SQLAlchemy, qui peut etre fermee pendant le test."""

    source_id: str
    name: str
    url: str
    active: bool
    requires_js: bool
    # Derniere collecte REUSSIE (`update_last_collected` n'est appele qu'en
    # cas de succes). Pour une source `requires_js`, c'est la seule preuve de
    # fonctionnement : le test HTTP simple n'y est pas concluant.
    last_collected_at: datetime | None = None


@dataclass(frozen=True)
class SourceHealthItem:
    source_id: str
    name: str
    url: str
    active: bool
    # Un resultat negatif sur une source `requires_js` n'est pas concluant :
    # elle se collecte via Playwright, pas via `requests` (voir docstring).
    requires_js: bool
    reachable: bool
    http_status: int | None
    checked_at: datetime


@dataclass(frozen=True)
class SourceHealthReport:
    checked: int
    reachable: int
    unreachable: int
    items: list[SourceHealthItem]

    @property
    def reachable_ratio(self) -> float:
        return self.reachable / self.checked if self.checked else 0.0


@dataclass
class SourceTestEntry:
    source_id: str
    name: str
    url: str
    active: bool
    requires_js: bool
    state: str = PENDING
    http_status: int | None = None
    checked_at: datetime | None = None
    last_collected_at: datetime | None = None


@dataclass
class SourceTestProgress:
    """Etat d'un test en cours, publie a chaque adresse testee."""

    entries: list[SourceTestEntry] = field(default_factory=list)
    phase: str = "first_pass"  # first_pass | retry | done
    first_pass_done: int = 0
    retry_total: int = 0
    retry_done: int = 0

    @property
    def total(self) -> int:
        return len(self.entries)

    @property
    def reachable(self) -> int:
        return sum(1 for e in self.entries if e.state == REACHABLE)

    @property
    def unreachable(self) -> int:
        return sum(1 for e in self.entries if e.state == UNREACHABLE)

    def record(self, result: OnionCheckResult, phase: str) -> None:
        cibles = [e for e in self.entries if e.url == result.url]
        if phase == "retry":
            self.retry_done += 1
        else:
            self.first_pass_done += 1
        for entry in cibles:
            entry.state = REACHABLE if result.reachable else UNREACHABLE
            entry.checked_at = result.checked_at
            if result.reachable or phase != "retry":
                entry.http_status = result.http_status

    def begin_retry(self, count: int) -> None:
        self.phase = "retry"
        self.retry_total = count
        for entry in self.entries:
            if entry.state == UNREACHABLE:
                entry.state = RETRYING

    def finish(self) -> None:
        self.phase = "done"
        for entry in self.entries:
            # Retestee sans resultat : l'echec de la 1re passe reste acquis.
            if entry.state == RETRYING:
                entry.state = UNREACHABLE
            elif entry.state == PENDING:
                entry.state = UNTESTED


ProgressCallback = Callable[[SourceTestProgress], None]


def _publier(
    on_progress: ProgressCallback | None, progress: SourceTestProgress
) -> None:
    """Un rappel d'affichage en echec ne fait jamais echouer le test."""
    if on_progress is None:
        return
    try:
        on_progress(progress)
    except Exception:
        logger.exception("Test de sources : publication de la progression en echec")


def load_sources(
    db: Session,
    *,
    only_active: bool = False,
    source_ids: Sequence[str] | None = None,
) -> list[SourceRef]:
    """Sources a tester. `source_ids` cible des sources precises ; sinon
    `only_active=True` limite aux actives -- par defaut on teste TOUT, y
    compris les inactives : c'est justement la qu'on veut savoir si une source
    desactivee est revenue en ligne."""
    repo = SourceRepository(db)
    if source_ids is not None:
        sources = [
            s
            for s in (repo.get(uuid.UUID(str(i))) for i in source_ids)
            if s is not None
        ]
    else:
        sources = (
            repo.get_active() if only_active else repo.list(limit=MAX_SOURCES_CHECKED)
        )

    if len(sources) > MAX_SOURCES_CHECKED:
        logger.warning(
            "Test de sources: %d sources, plafonne a %d",
            len(sources),
            MAX_SOURCES_CHECKED,
        )
        sources = sources[:MAX_SOURCES_CHECKED]

    return [
        SourceRef(
            source_id=str(s.id),
            name=s.name,
            url=s.url,
            active=s.active,
            requires_js=bool(getattr(s, "requires_js", False)),
            last_collected_at=getattr(s, "last_collected_at", None),
        )
        for s in sources
    ]


def check_source_refs(
    refs: Sequence[SourceRef], *, on_progress: ProgressCallback | None = None
) -> SourceHealthReport:
    """Teste les sources donnees, en publiant la progression a chaque adresse."""
    if not refs:
        return SourceHealthReport(checked=0, reachable=0, unreachable=0, items=[])

    progress = SourceTestProgress(
        entries=[
            SourceTestEntry(
                source_id=r.source_id,
                name=r.name,
                url=r.url,
                active=r.active,
                requires_js=r.requires_js,
                last_collected_at=r.last_collected_at,
            )
            for r in refs
        ]
    )
    _publier(on_progress, progress)

    def on_result(result: OnionCheckResult, phase: str) -> None:
        progress.record(result, phase)
        _publier(on_progress, progress)

    def on_retry_start(count: int) -> None:
        progress.begin_retry(count)
        _publier(on_progress, progress)

    # `check_onion_entries` traite aussi bien le clearnet que le .onion (il ne
    # desactive la verification TLS que pour .onion, ou le certificat
    # auto-signe est la norme) -- pas besoin de separer les deux ici.
    results = check_onion_entries(
        [(r.name, r.url) for r in refs],
        on_result=on_result,
        on_retry_start=on_retry_start,
    )
    progress.finish()
    _publier(on_progress, progress)

    by_url = {r.url: r for r in results}
    items: list[SourceHealthItem] = []
    for ref in refs:
        result = by_url.get(ref.url)
        if result is None:
            # Ne devrait pas arriver, mais une source sans resultat doit
            # apparaitre comme non testee plutot que disparaitre du rapport.
            logger.warning("Test de sources: aucun resultat pour %s", ref.url)
            continue
        items.append(
            SourceHealthItem(
                source_id=ref.source_id,
                name=ref.name,
                url=ref.url,
                active=ref.active,
                requires_js=ref.requires_js,
                reachable=result.reachable,
                http_status=result.http_status,
                checked_at=result.checked_at,
            )
        )

    reachable = sum(1 for i in items if i.reachable)
    report = SourceHealthReport(
        checked=len(items),
        reachable=reachable,
        unreachable=len(items) - reachable,
        items=items,
    )
    logger.info(
        "Test de sources: %d testee(s), %d joignable(s), %d injoignable(s)",
        report.checked,
        report.reachable,
        report.unreachable,
    )
    return report


def check_sources(
    db: Session,
    *,
    only_active: bool = False,
    source_ids: Sequence[str] | None = None,
    on_progress: ProgressCallback | None = None,
) -> SourceHealthReport:
    """Teste les sources enregistrees et retourne leur disponibilite (chemin
    synchrone, conserve pour `POST /api/sources/test`)."""
    refs = load_sources(db, only_active=only_active, source_ids=source_ids)
    return check_source_refs(refs, on_progress=on_progress)
