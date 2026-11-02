"""Test d'integration de GET /api/entities/candidates (voir
api/routers/entities.py::list_organization_candidates) -- appelle directement
la fonction du routeur avec une vraie session, comme le fait deja
integration/test_alert_service.py pour la logique metier (pas de TestClient
HTTP dans ce projet, la fonction du routeur est deja testable telle quelle)."""

import uuid
from datetime import datetime, timezone

import pytest

from app.api.routers.entities import list_organization_candidates
from app.db.models.detection import Detection
from app.db.models.entity import Entity, EntitySelector
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
        name="Test source (candidates endpoint)",
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
    db, document: RawDocument, *, value_masked: str, value_hash: str
) -> Detection:
    detection = Detection(
        id=uuid.uuid4(),
        document_id=document.id,
        type="organization",
        value_masked=value_masked,
        value_hash=value_hash,
        validated=False,
        is_relevant=False,
        created_at=datetime.now(timezone.utc),
    )
    db.add(detection)
    db.commit()
    return detection


def _cleanup(db, *, entities=(), detections=(), documents=(), sources=()):
    for e in entities:
        db.query(EntitySelector).filter(EntitySelector.entity_id == e.id).delete()
        db.query(Entity).filter(Entity.id == e.id).delete()
    for d in detections:
        db.query(Detection).filter(Detection.id == d.id).delete()
    for doc in documents:
        db.query(RawDocument).filter(RawDocument.id == doc.id).delete()
    for s in sources:
        db.query(Source).filter(Source.id == s.id).delete()
    db.commit()


def _occurrences_to_reach_top(db) -> int:
    """Nombre d'occurrences necessaires pour qu'une valeur de test remonte en
    tete de `top_organization_candidates` (borne par `limit`, trie par
    frequence) -- sans quoi le test dependrait du contenu reel de la base, qui
    compte deja des milliers de detections `organization`."""
    top = DetectionRepository(db).top_organization_candidates(limit=1)
    return max((count for _masked, _hash, count in top), default=0) + 1


class TestListOrganizationCandidates:
    def test_returns_organization_detection_not_covered_by_an_entity(self, db):
        occurrences = _occurrences_to_reach_top(db)
        source, document = _make_source_and_document(db)
        value_hash = uuid.uuid4().hex
        detections = [
            _make_detection(
                db, document, value_masked="Candidate Org Test", value_hash=value_hash
            )
            for _ in range(occurrences)
        ]
        try:
            results = list_organization_candidates(db)
            match = next((r for r in results if r.name == "Candidate Org Test"), None)
            assert match is not None
            assert match.count == occurrences
        finally:
            _cleanup(db, detections=detections, documents=[document], sources=[source])

    def test_excludes_candidate_already_covered_by_active_entity(self, db):
        # Meme volume que le test precedent : sans cela le candidat serait
        # absent du resultat parce qu'il est hors du top, pas parce que
        # l'entite existante l'a exclu -- le test passerait pour la mauvaise
        # raison (voir pipeline/alerting/candidates.py::filter_new_candidates).
        occurrences = _occurrences_to_reach_top(db)
        source, document = _make_source_and_document(db)
        value_hash = uuid.uuid4().hex
        detections = [
            _make_detection(
                db, document, value_masked="Covered Org Test", value_hash=value_hash
            )
            for _ in range(occurrences)
        ]
        entity = Entity(
            id=uuid.uuid4(),
            name="Covered Org Test",
            active=True,
            created_at=datetime.now(timezone.utc),
        )
        db.add(entity)
        db.commit()
        try:
            results = list_organization_candidates(db)
            assert all(r.name != "Covered Org Test" for r in results)
        finally:
            _cleanup(
                db,
                entities=[entity],
                detections=detections,
                documents=[document],
                sources=[source],
            )
