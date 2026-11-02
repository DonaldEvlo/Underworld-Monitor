"""Test d'integration de la chaine complete : document collecte -> nettoyage,
dedup, langue, detection -> persistance (voir
RawDocumentRepository.save_new_documents).

Complementaire des tests unitaires de chaque brique : ceux-ci verifient que les
composants fonctionnent isolement, celui-ci qu'ils sont bien cables ensemble.
C'est le seul endroit ou une regression de cablage (un detecteur retire du
registre, un parametre non transmis) serait detectee.

Meme pattern que integration/test_alert_service.py : vraie session, chaque test
cree ses lignes et les supprime en `finally`."""

import uuid
from datetime import datetime, timezone

import pytest

from app.contracts.raw_document import RawDocumentContract
from app.contracts.source import SourceType
from app.db.models.detection import Detection
from app.db.models.raw_document import RawDocument
from app.db.models.source import Source
from app.db.session import SessionLocal
from app.repositories.document_repo import RawDocumentRepository


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def source(db):
    src = Source(
        id=uuid.uuid4(),
        name="Test source (pipeline)",
        type="forum",
        url=f"http://test-{uuid.uuid4().hex}.onion",
        active=False,
        created_at=datetime.now(timezone.utc),
    )
    db.add(src)
    db.commit()
    yield src
    # Les documents (et leurs detections, en cascade applicative) sont nettoyes
    # par chaque test ; il ne reste que la source elle-meme.
    for doc in db.query(RawDocument).filter(RawDocument.source_id == src.id).all():
        db.query(Detection).filter(Detection.document_id == doc.id).delete()
        db.query(RawDocument).filter(RawDocument.id == doc.id).delete()
    db.query(Source).filter(Source.id == src.id).delete()
    db.commit()


def _make_contract(
    source_id: uuid.UUID, content: str, **overrides
) -> RawDocumentContract:
    defaults = {
        "id": uuid.uuid4(),
        "source_id": source_id,
        "url": f"http://test.onion/{uuid.uuid4().hex}",
        "content": content,
        "content_hash": uuid.uuid4().hex,
        "fetched_at": datetime.now(timezone.utc),
        "source_type": SourceType.FORUM,
        "collector": "test",
        "collector_version": "1",
    }
    defaults.update(overrides)
    return RawDocumentContract(**defaults)


class TestSaveNewDocuments:
    def test_persists_document_and_its_detections(self, db, source):
        """Cablage de bout en bout : le document est stocke ET ses detections
        produites dans le meme appel."""
        content = "Leak: contact admin@example-pipeline-test.com for the dump."
        saved = RawDocumentRepository(db).save_new_documents(
            source.id, [_make_contract(source.id, content)]
        )
        assert len(saved) == 1

        detections = (
            db.query(Detection).filter(Detection.document_id == saved[0].id).all()
        )
        types = {d.type for d in detections}
        assert "email" in types
        assert "domain" in types

    def test_never_persists_the_raw_value(self, db, source):
        """Regle non negociable (CONTRIBUTING.md §2) verifiee sur la chaine reelle,
        pas seulement sur masking.py : aucune detection ne doit contenir
        l'adresse complete."""
        content = "Contact: jean.dupont@example-pipeline-test.com"
        saved = RawDocumentRepository(db).save_new_documents(
            source.id, [_make_contract(source.id, content)]
        )
        detections = (
            db.query(Detection).filter(Detection.document_id == saved[0].id).all()
        )
        for detection in detections:
            assert "jean.dupont@" not in detection.value_masked

    def test_ner_does_not_run_during_ingestion(self, db, source):
        """Le NER (patterns/organization.py) est volontairement absent du
        registre : trop lent (~69 ms/document contre ~4 ms pour tous les autres
        reunis) et source d'une fuite de PII constatee (adresses email classees
        ORG, stockees en clair). Il reste disponible a la demande via
        POST /api/entities/backfill-organizations.

        Ce test verrouille ce choix : un texte ou spaCy trouverait une
        organisation ne doit produire aucune detection `organization` a
        l'ingestion, seuls les marqueurs declares par la source en produisent
        (voir test_declared_markers_are_detected_through_the_pipeline)."""
        content = (
            "Microsoft and Google confirmed that Apple was affected by the "
            "incident, according to Reuters."
        )
        saved = RawDocumentRepository(db).save_new_documents(
            source.id, [_make_contract(source.id, content)]
        )
        detections = (
            db.query(Detection).filter(Detection.document_id == saved[0].id).all()
        )
        assert [d for d in detections if d.type == "organization"] == []

    def test_declared_markers_are_detected_through_the_pipeline(self, db, source):
        """Les detecteurs "donnees declarees" (victim, threat_actor, topic,
        announcement) doivent etre cables dans le registre -- un oubli les
        rendrait silencieusement inertes en production."""
        content = (
            "Groupe: TestGang\n"
            "Victime annoncee: Pipeline Test Industries\n"
            "Decouvert le: 2026-08-14T10:00:00Z"
        )
        saved = RawDocumentRepository(db).save_new_documents(
            source.id, [_make_contract(source.id, content)]
        )
        detections = (
            db.query(Detection).filter(Detection.document_id == saved[0].id).all()
        )
        by_type = {d.type: d for d in detections}
        assert by_type["threat_actor"].value_masked == "TestGang"
        assert by_type["organization"].value_masked == "Pipeline Test Industries"
        # Declare par la source, pas infere : voir patterns/victim.py.
        assert by_type["organization"].validated is True

    def test_exact_duplicate_is_skipped(self, db, source):
        """Dedup par content_hash : un document deja vu n'est pas re-persiste."""
        content = "Duplicate content for pipeline test."
        content_hash = uuid.uuid4().hex
        repo = RawDocumentRepository(db)

        first = repo.save_new_documents(
            source.id, [_make_contract(source.id, content, content_hash=content_hash)]
        )
        second = repo.save_new_documents(
            source.id, [_make_contract(source.id, content, content_hash=content_hash)]
        )
        assert len(first) == 1
        assert second == []

    def test_near_duplicate_is_flagged_but_still_stored(self, db, source):
        """Un quasi-doublon est marque `is_duplicate` sans etre perdu : la
        minimisation ne s'applique pas ici, l'analyste doit pouvoir consulter
        l'original comme le repost (voir CONTRIBUTING.md)."""
        base = (
            "Acme Corporation database leaked, including customer names, email "
            "addresses and hashed passwords. Download link available on request "
            "from our dedicated forum thread."
        )
        repo = RawDocumentRepository(db)
        repo.save_new_documents(source.id, [_make_contract(source.id, base)])
        saved = repo.save_new_documents(
            source.id,
            [_make_contract(source.id, "[reposted 2026-08-14] " + base)],
        )
        assert len(saved) == 1
        assert saved[0].is_duplicate is True

    def test_watchlist_match_marks_detections_as_relevant(self, db, source):
        """`is_relevant` se propage du document vers ses detections (voir
        registry.detect_all) -- c'est ce qui alimente la severite."""
        content = "This is a data leak announcement with admin@relevant-test.com"
        saved = RawDocumentRepository(db).save_new_documents(
            source.id,
            [_make_contract(source.id, content)],
            watchlist_terms=["data leak"],
        )
        assert saved[0].matched_keywords == ["data leak"]
        detections = (
            db.query(Detection).filter(Detection.document_id == saved[0].id).all()
        )
        assert detections and all(d.is_relevant for d in detections)

    def test_empty_document_list_is_a_noop(self, db, source):
        assert RawDocumentRepository(db).save_new_documents(source.id, []) == []
