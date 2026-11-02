"""Tests d'integration de repositories/detection_repo.py pour les methodes
d'agregation SQL (top_organization_candidates, exists_for_document) --
necessitent une vraie session SQLAlchemy pour verifier le GROUP BY/ORDER BY,
pas seulement la forme des donnees. Meme pattern que
integration/test_alert_service.py : chaque test cree ses propres lignes et
les supprime en `finally`."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.db.models.detection import Detection
from app.db.models.raw_document import RawDocument
from app.db.models.source import Source
from app.db.session import SessionLocal
from app.repositories.detection_repo import DetectionRepository


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _make_source_and_document(db) -> tuple[Source, RawDocument]:
    source = Source(
        id=uuid.uuid4(),
        name="Test source (detection_repo)",
        type="forum",
        url=f"http://test-{uuid.uuid4().hex}.onion",
        active=False,
        created_at=datetime.now(timezone.utc),
    )
    db.add(source)
    db.commit()

    document = RawDocument(
        id=uuid.uuid4(),
        source_id=source.id,
        url="http://test.onion/doc",
        content="test content",
        content_hash=uuid.uuid4().hex,
        fetched_at=datetime.now(timezone.utc),
        source_type="forum",
        collector="test",
        collector_version="1",
        is_duplicate=False,
    )
    db.add(document)
    db.commit()
    return source, document


def _make_detection(
    db,
    document: RawDocument,
    *,
    type_: str,
    value_masked: str,
    value_hash: str,
    created_at: datetime | None = None,
) -> Detection:
    detection = Detection(
        id=uuid.uuid4(),
        document_id=document.id,
        type=type_,
        value_masked=value_masked,
        value_hash=value_hash,
        validated=False,
        is_relevant=False,
        created_at=created_at or datetime.now(timezone.utc),
    )
    db.add(detection)
    db.commit()
    return detection


def _cleanup(db, *, detections=(), documents=(), sources=()):
    for d in detections:
        db.query(Detection).filter(Detection.id == d.id).delete()
    for doc in documents:
        db.query(RawDocument).filter(RawDocument.id == doc.id).delete()
    for s in sources:
        db.query(Source).filter(Source.id == s.id).delete()
    db.commit()


class TestTopOrganizationCandidates:
    def test_groups_and_counts_by_value(self, db):
        """`top_organization_candidates` est borne par `limit` et trie par
        frequence decroissante : sur une base qui contient deja des milliers de
        detections reelles, une valeur de test creee en 2 exemplaires ne
        remonterait jamais dans le top. Le test cree donc assez d'occurrences
        pour depasser le maximum existant -- ce qui verifie du meme coup le
        ORDER BY count DESC, pas seulement le GROUP BY."""
        repo = DetectionRepository(db)
        existing_max = max(
            (
                count
                for _masked, _hash, count in repo.top_organization_candidates(limit=1)
            ),
            default=0,
        )
        occurrences = existing_max + 1

        source, document = _make_source_and_document(db)
        value_hash = uuid.uuid4().hex
        detections = [
            _make_detection(
                db,
                document,
                type_="organization",
                value_masked="Telco",
                value_hash=value_hash,
            )
            for _ in range(occurrences)
        ]
        try:
            results = repo.top_organization_candidates()
            assert results[0] == ("Telco", value_hash, occurrences)
        finally:
            _cleanup(db, detections=detections, documents=[document], sources=[source])

    def test_ignores_non_organization_detections(self, db):
        source, document = _make_source_and_document(db)
        value_hash = uuid.uuid4().hex
        detection = _make_detection(
            db,
            document,
            type_="domain",
            value_masked="example.tld",
            value_hash=value_hash,
        )
        try:
            results = DetectionRepository(db).top_organization_candidates()
            assert all(r[1] != value_hash for r in results)
        finally:
            _cleanup(db, detections=[detection], documents=[document], sources=[source])


class TestExistsForDocument:
    def test_returns_true_for_existing_pair(self, db):
        source, document = _make_source_and_document(db)
        value_hash = uuid.uuid4().hex
        detection = _make_detection(
            db,
            document,
            type_="organization",
            value_masked="Telco",
            value_hash=value_hash,
        )
        try:
            assert (
                DetectionRepository(db).exists_for_document(document.id, value_hash)
                is True
            )
        finally:
            _cleanup(db, detections=[detection], documents=[document], sources=[source])

    def test_returns_false_for_unknown_pair(self, db):
        source, document = _make_source_and_document(db)
        try:
            assert (
                DetectionRepository(db).exists_for_document(document.id, "unknown-hash")
                is False
            )
        finally:
            _cleanup(db, documents=[document], sources=[source])


class TestTypesFilter:
    """`types_` pousse le filtrage des types EN SQL, la ou les appelants qui
    croisent le corpus en memoire (alert_service, stats, entities) le faisaient
    apres coup avec un `if row.type in ...`.

    L'enjeu n'est pas la performance mais la CORRECTION : ces appelants sont
    bornes par un plafond de lignes trie `created_at DESC`. Filtrer apres coup
    laisse les types inutilisables consommer ce plafond, si bien que des
    detections matchables plus anciennes tombent hors du scan -- sans erreur ni
    log. Mesure du 2026-09-01 sur la base reelle : 61 % du plafond consomme par
    des types jetes aussitot, et 193 detections matchables hors scan, dont 11
    rattachees a une entite surveillee. Aucune alerte n'avait pour autant ete
    perdue (verifie en base) : elles avaient ete alertees quand elles etaient
    plus recentes. Le risque reel est la rafale de re-detection, qui remplit le
    plafond en une passe -- le 2026-08-28, 8 120 detections ingerees dont
    244 matchables."""

    def test_filters_to_requested_types(self, db):
        source, document = _make_source_and_document(db)
        detections = [
            _make_detection(
                db,
                document,
                type_=type_,
                value_masked=f"{type_}.example.com",
                value_hash=uuid.uuid4().hex,
            )
            for type_ in ("domain", "email", "organization", "volume")
        ]
        try:
            rows = DetectionRepository(db).list_all(
                limit=100, types_=["domain", "email"]
            )
            found = {r.type for r in rows if r.document_id == document.id}
            assert found == {"domain", "email"}
        finally:
            _cleanup(db, detections=detections, documents=[document], sources=[source])

    def test_non_matchable_types_no_longer_consume_the_limit(self, db):
        """Regression du defaut corrige : la detection matchable est la PLUS
        ANCIENNE des quatre. Avec un plafond de 3 et aucun filtre de type, les
        trois lignes non matchables plus recentes epuisent le budget et elle
        disparait du scan. Avec `types_`, elle est vue.

        Les dates sont volontairement dans le futur : la base d'integration
        contient des dizaines de milliers de detections reelles, et
        `created_from` seul ne suffirait pas a isoler les lignes du test."""
        source, document = _make_source_and_document(db)
        base = datetime.now(timezone.utc) + timedelta(days=1)
        cutoff = datetime.now(timezone.utc) + timedelta(hours=12)

        matchable = _make_detection(
            db,
            document,
            type_="domain",
            value_masked="victime.example.com",
            value_hash=uuid.uuid4().hex,
            created_at=base,
        )
        noisy = [
            _make_detection(
                db,
                document,
                type_="organization",
                value_masked=f"Bruit {i}",
                value_hash=uuid.uuid4().hex,
                created_at=base + timedelta(hours=i + 1),
            )
            for i in range(3)
        ]
        try:
            repo = DetectionRepository(db)

            # Le comportement d'avant le correctif, conserve ici comme temoin :
            # la detection matchable est bel et bien evincee par le plafond.
            without_filter = repo.list_all(limit=3, created_from=cutoff)
            assert matchable.id not in {r.id for r in without_filter}

            with_filter = repo.list_all(
                limit=3, created_from=cutoff, types_=["domain", "email"]
            )
            assert matchable.id in {r.id for r in with_filter}
        finally:
            _cleanup(
                db,
                detections=[matchable, *noisy],
                documents=[document],
                sources=[source],
            )

    def test_empty_sequence_selects_nothing(self, db):
        """Une sequence vide filtre a vide -- « aucun type demande » ne doit pas
        se comporter comme « tous les types », ce qui ferait retomber
        silencieusement dans le defaut corrige ci-dessus."""
        assert DetectionRepository(db).list_all(limit=10, types_=[]) == []

    def test_count_all_honours_types(self, db):
        source, document = _make_source_and_document(db)
        cutoff = datetime.now(timezone.utc) + timedelta(hours=12)
        base = datetime.now(timezone.utc) + timedelta(days=1)
        detections = [
            _make_detection(
                db,
                document,
                type_=type_,
                value_masked=f"{type_}.example.org",
                value_hash=uuid.uuid4().hex,
                created_at=base,
            )
            for type_ in ("domain", "email", "organization")
        ]
        try:
            repo = DetectionRepository(db)
            assert repo.count_all(created_from=cutoff) == 3
            assert repo.count_all(created_from=cutoff, types_=["domain", "email"]) == 2
        finally:
            _cleanup(db, detections=detections, documents=[document], sources=[source])
