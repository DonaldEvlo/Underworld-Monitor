"""Tests d'integration de services/detection_severity_service.py.

Le point verifie ici est celui qui motive tout le module : une detection qui ne
correspond a AUCUNE entite surveillee doit tout de meme porter une severite.
`alert_service` fait `continue` sur ces detections avant meme d'appeler
`severity_for_detection` -- une institution hors perimetre n'en avait donc
aucune, alors qu'elle peut etre une victime nommee et confirmee par un tiers
(mesure du 2026-09-01 : 61 victimes corroborees non surveillees).

Meme pattern que integration/test_alert_service.py : chaque test cree ses
propres lignes et les supprime en `finally`.


⚠️ REECRIT le 2026-09-15 : la corroboration n'eleve plus la severite --
elle est devenue une marque de VERIFIABILITE (arbitrage de projet). Une
victime corroboree obtient donc `medium` et non plus `high`. Ce qui est
protege ici reste l'essentiel et n'a PAS change : la corroboration LEVE
toujours le plancher LOW, si bien qu'une institution hors perimetre de
surveillance porte une severite et cesse d'etre invisible."""

import uuid
from datetime import datetime, timezone

import pytest

from app.db.models.detection import Detection
from app.db.models.entity import Entity, EntitySelector
from app.db.models.raw_document import RawDocument
from app.db.models.source import Source
from app.db.session import SessionLocal
from app.services.detection_severity_service import refresh_detection_severities


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
        name="Test source (detection_severity)",
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


def _make_entity(db, *, domain: str) -> Entity:
    entity = Entity(
        id=uuid.uuid4(),
        name=f"Entite {domain}",
        active=True,
        created_at=datetime.now(timezone.utc),
    )
    db.add(entity)
    db.commit()
    db.add(
        EntitySelector(
            id=uuid.uuid4(),
            entity_id=entity.id,
            type="domain",
            value=domain,
            created_at=datetime.now(timezone.utc),
        )
    )
    db.commit()
    return entity


def _make_detection(
    db,
    document: RawDocument,
    *,
    value_masked: str,
    type_: str = "domain",
    validated: bool = False,
    is_relevant: bool = False,
    corroboration_status: str | None = None,
) -> Detection:
    detection = Detection(
        id=uuid.uuid4(),
        document_id=document.id,
        type=type_,
        value_masked=value_masked,
        value_hash=uuid.uuid4().hex,
        validated=validated,
        is_relevant=is_relevant,
        created_at=datetime.now(timezone.utc),
        corroboration_status=corroboration_status,
    )
    db.add(detection)
    db.commit()
    return detection


def _cleanup(db, *, entities=(), detections=(), documents=(), sources=()):
    for d in detections:
        db.query(Detection).filter(Detection.id == d.id).delete()
    for doc in documents:
        db.query(RawDocument).filter(RawDocument.id == doc.id).delete()
    for e in entities:
        db.query(EntitySelector).filter(EntitySelector.entity_id == e.id).delete()
        db.query(Entity).filter(Entity.id == e.id).delete()
    for s in sources:
        db.query(Source).filter(Source.id == s.id).delete()
    db.commit()


class TestUnwatchedInstitutionsGetASeverity:
    """Le motif d'existence du module."""

    def test_corroborated_victim_without_any_watched_entity_gets_high(self, db):
        """Aucune entite ne surveille ce domaine, et `is_relevant` est faux --
        exactement le cas des 28 victimes corroborees qui retombaient en LOW,
        donc invisibles. Elles doivent desormais porter une severite."""
        source, document = _make_source_and_document(db)
        detection = _make_detection(
            db,
            document,
            value_masked=f"victime-hors-perimetre-{uuid.uuid4().hex[:8]}.tld",
            is_relevant=False,
            corroboration_status="corroborated",
        )
        try:
            refresh_detection_severities(db, detection_ids=[detection.id])
            db.refresh(detection)
            assert detection.severity == "medium"
        finally:
            _cleanup(db, detections=[detection], documents=[document], sources=[source])

    def test_uncorroborated_unwatched_detection_is_low_not_null(self, db):
        """Temoin : elle porte une severite (LOW), elle n'est pas laissee sans
        evaluation. NULL signifierait « pas evaluee », ce qui est different."""
        source, document = _make_source_and_document(db)
        detection = _make_detection(
            db,
            document,
            value_masked=f"anonyme-{uuid.uuid4().hex[:8]}.tld",
            is_relevant=False,
        )
        try:
            refresh_detection_severities(db, detection_ids=[detection.id])
            db.refresh(detection)
            assert detection.severity == "low"
        finally:
            _cleanup(db, detections=[detection], documents=[document], sources=[source])

    def test_watched_entity_detection_is_at_least_medium(self, db):
        """Le rattachement a une entite surveillee continue de lever LOW,
        independamment de la corroboration."""
        domain = f"surveille-{uuid.uuid4().hex[:8]}.tld"
        entity = _make_entity(db, domain=domain)
        source, document = _make_source_and_document(db)
        detection = _make_detection(
            db, document, value_masked=domain, is_relevant=False
        )
        try:
            refresh_detection_severities(db, detection_ids=[detection.id])
            db.refresh(detection)
            assert detection.severity == "medium"
        finally:
            _cleanup(
                db,
                entities=[entity],
                detections=[detection],
                documents=[document],
                sources=[source],
            )

    def test_non_matchable_types_stay_null(self, db):
        """`organization`, `card`... n'ont pas de severite interpretable ici :
        `matching.py` ne sait pas les rattacher et la corroboration ne porte que
        sur des domaines. NULL se lit « pas evaluee », pas « aucune »."""
        source, document = _make_source_and_document(db)
        detection = _make_detection(
            db,
            document,
            value_masked="Une Organisation",
            type_="organization",
            is_relevant=True,
        )
        try:
            refresh_detection_severities(db, detection_ids=[detection.id])
            db.refresh(detection)
            assert detection.severity is None
        finally:
            _cleanup(db, detections=[detection], documents=[document], sources=[source])

    def test_is_idempotent(self, db):
        """La passe tourne a chaque cycle d'alerting : une seconde execution ne
        doit rien reecrire (compteur `updated` a 0 pour cette detection)."""
        source, document = _make_source_and_document(db)
        detection = _make_detection(
            db,
            document,
            value_masked=f"idem-{uuid.uuid4().hex[:8]}.tld",
            corroboration_status="corroborated",
        )
        try:
            refresh_detection_severities(db, detection_ids=[detection.id])
            db.refresh(detection)
            first = detection.severity
            refresh_detection_severities(db, detection_ids=[detection.id])
            db.refresh(detection)
            assert detection.severity == first
        finally:
            _cleanup(db, detections=[detection], documents=[document], sources=[source])


class TestCollectionInfrastructureIsExcluded:
    """Regression majeure attrapee le 2026-09-01 : en persistant la severite
    pour TOUTES les detections (et plus seulement celles rattachees a une
    entite), la branche `validated` s'est mise a promouvoir des `.onion` en
    HIGH -- **401 sur 467**.

    Ce sont les adresses des forums et sites de fuite que NOUS collectons, pas
    des victimes. `validated` sur un domaine ne signifie que « format .onion
    reconnu » : les 1216 domaines valides du corpus sont tous des `.onion`.

    Le defaut etait invisible dans l'alerting, ou un `.onion` ne matche jamais
    un selecteur clearnet et sortait avant tout calcul."""

    def test_a_validated_onion_never_gets_a_severity(self, db):
        source, document = _make_source_and_document(db)
        detection = _make_detection(
            db,
            document,
            value_masked=f"forum{uuid.uuid4().hex[:8]}.onion",
            validated=True,
            is_relevant=True,
        )
        try:
            refresh_detection_severities(db, detection_ids=[detection.id])
            db.refresh(detection)
            assert detection.severity is None
        finally:
            _cleanup(db, detections=[detection], documents=[document], sources=[source])

    def test_a_previously_scored_onion_is_reset_to_null(self, db):
        """Le correctif doit NETTOYER l'existant, pas seulement cesser de
        produire l'erreur : 1256 lignes portaient deja une severite a tort."""
        source, document = _make_source_and_document(db)
        detection = _make_detection(
            db,
            document,
            value_masked=f"ancien{uuid.uuid4().hex[:8]}.onion",
            validated=True,
            is_relevant=True,
        )
        detection.severity = "high"
        db.commit()
        try:
            refresh_detection_severities(db, detection_ids=[detection.id])
            db.refresh(detection)
            assert detection.severity is None
        finally:
            _cleanup(db, detections=[detection], documents=[document], sources=[source])

    def test_a_clearnet_victim_is_still_scored(self, db):
        """Temoin : l'exclusion vise l'infrastructure, pas le clearnet."""
        source, document = _make_source_and_document(db)
        detection = _make_detection(
            db,
            document,
            value_masked=f"victime-{uuid.uuid4().hex[:8]}.tld",
            corroboration_status="corroborated",
        )
        try:
            refresh_detection_severities(db, detection_ids=[detection.id])
            db.refresh(detection)
            assert detection.severity == "medium"
        finally:
            _cleanup(db, detections=[detection], documents=[document], sources=[source])
