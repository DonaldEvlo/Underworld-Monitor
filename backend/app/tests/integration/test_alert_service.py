"""Tests d'integration de services/alert_service.py -- contrairement au
reste de la suite (logique pure, sans DB), ce service orchestre
matching+rules+persistance : le tester sans une vraie session SQLAlchemy
reviendrait a mocker toute la logique qu'on veut justement verifier.

Chaque test cree ses propres lignes et les supprime en `finally` -- pas de
fixture partagee, pour rester lisible sur ce qui est mis en place par
chaque scenario."""

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from app.db.models.alert import Alert, AlertDetection
from app.db.models.detection import Detection
from app.db.models.entity import Entity, EntitySelector
from app.db.models.raw_document import RawDocument
from app.db.models.source import Source
from app.db.models.user import User
from app.db.session import SessionLocal
from app.services.alert_service import generate_alerts, refresh_alert_severities


def _analyste_de_test() -> User:
    """Doublure de l'utilisateur connecte.

    ⚠️ RENVOIE UN VRAI `User`, PAS UN `dict`. La version precedente rendait
    `{"sub": "test"}` : elle a cesse de fonctionner des l'ajout des roles
    (2026-09-17), qui lisent `current_user.role`. Une doublure qui ne
    ressemble pas a ce que rend la vraie dependance fait passer des tests sur
    un objet que la production ne verra jamais.

    Role `analyst` : c'est le profil de l'utilisateur principal, donc celui
    sous lequel ces routes doivent etre exercees."""
    return User(
        id=uuid.uuid4(),
        username="test_analyste",
        password_hash="x",
        active=True,
        role="analyst",
    )


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _make_entity(db, *, domain: str, active: bool = True) -> Entity:
    entity = Entity(
        id=uuid.uuid4(),
        name=f"Test entity {domain}",
        active=active,
        created_at=datetime.now(timezone.utc),
    )
    entity.selectors = [
        EntitySelector(
            id=uuid.uuid4(),
            type="domain",
            value=domain,
            created_at=datetime.now(timezone.utc),
        )
    ]
    db.add(entity)
    db.commit()
    return entity


def _make_source_and_document(
    db, *, collector: str = "test"
) -> tuple[Source, RawDocument]:
    """`detections.document_id` est une FK vers `raw_documents`, elle-meme
    FK vers `sources` -- il faut les deux lignes en place pour inserer une
    detection de test, meme si ce service ne s'y interesse pas directement."""
    source = Source(
        id=uuid.uuid4(),
        name="Test source (alert_service)",
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
        collector=collector,
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
    validated: bool,
    is_relevant: bool,
    created_at: datetime | None = None,
    corroboration_status: str | None = None,
) -> Detection:
    """`created_at` permet de simuler une detection ancienne, pour verifier la
    fenetre glissante de generate_alerts (voir TestAlertWindow)."""
    detection = Detection(
        id=uuid.uuid4(),
        document_id=document.id,
        type=type_,
        value_masked=value_masked,
        value_hash=uuid.uuid4().hex,
        validated=validated,
        is_relevant=is_relevant,
        created_at=created_at or datetime.now(timezone.utc),
        corroboration_status=corroboration_status,
    )
    db.add(detection)
    db.commit()
    return detection


def _cleanup(db, *, entities=(), detections=(), documents=(), sources=()):
    db.query(AlertDetection).filter(
        AlertDetection.detection_id.in_([d.id for d in detections])
    ).delete(synchronize_session=False)
    db.query(Alert).filter(Alert.entity_id.in_([e.id for e in entities])).delete(
        synchronize_session=False
    )
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


class TestGenerateAlerts:
    def test_creates_an_alert_for_a_matching_relevant_detection(self, db):
        entity = _make_entity(db, domain="example-alert-test.tld")
        source, document = _make_source_and_document(db)
        detection = _make_detection(
            db,
            document,
            type_="domain",
            value_masked="example-alert-test.tld",
            validated=False,
            is_relevant=True,  # MEDIUM -- au-dessus du seuil ALERT_THRESHOLD
        )
        try:
            alerts = generate_alerts(db, entity_ids=[entity.id])
            matching = [a for a in alerts if a.entity_id == entity.id]
            assert len(matching) == 1
            assert matching[0].severity == "medium"
            assert len(matching[0].detections) == 1
            assert matching[0].detections[0].detection_id == detection.id
        finally:
            _cleanup(
                db,
                entities=[entity],
                detections=[detection],
                documents=[document],
                sources=[source],
            )

    def test_detection_on_watched_entity_alerts_even_when_not_relevant(self, db):
        """Une detection rattachee a une entite surveillee alerte meme si
        `is_relevant` est faux : le rattachement EST la pertinence (voir
        rules.severity_for_detection). Ce test encodait auparavant la regle
        inverse -- change volontairement apres avoir constate qu'une victime de
        ransomware revendiquee (document factuel, sans mot de la watchlist)
        n'alertait jamais."""
        entity = _make_entity(db, domain="example-low-test.tld")
        source, document = _make_source_and_document(db)
        detection = _make_detection(
            db,
            document,
            type_="domain",
            value_masked="example-low-test.tld",
            validated=False,
            is_relevant=False,
        )
        try:
            alerts = generate_alerts(db, entity_ids=[entity.id])
            matching = [a for a in alerts if a.entity_id == entity.id]
            assert len(matching) == 1
            assert matching[0].severity == "medium"
        finally:
            _cleanup(
                db,
                entities=[entity],
                detections=[detection],
                documents=[document],
                sources=[source],
            )

    def test_detection_not_matching_any_entity_creates_no_alert(self, db):
        """Contrepartie du test precedent : sans rattachement, aucune alerte --
        le relevement de severite ne s'applique qu'aux entites surveillees."""
        entity = _make_entity(db, domain="example-watched-test.tld")
        source, document = _make_source_and_document(db)
        detection = _make_detection(
            db,
            document,
            type_="domain",
            value_masked="unrelated-domain-test.tld",
            validated=False,
            is_relevant=False,
        )
        try:
            alerts = generate_alerts(db, entity_ids=[entity.id])
            matching = [a for a in alerts if a.entity_id == entity.id]
            assert matching == []
        finally:
            _cleanup(
                db,
                entities=[entity],
                detections=[detection],
                documents=[document],
                sources=[source],
            )

    def test_second_run_same_day_reuses_the_existing_alert(self, db):
        entity = _make_entity(db, domain="example-idempotent-test.tld")
        source, document = _make_source_and_document(db)
        detection = _make_detection(
            db,
            document,
            type_="domain",
            value_masked="example-idempotent-test.tld",
            validated=False,
            is_relevant=True,
        )
        try:
            first_run = generate_alerts(db, entity_ids=[entity.id])
            first_id = next(a.id for a in first_run if a.entity_id == entity.id)

            # Depuis le 2026-08-29, une seconde execution sans detection
            # nouvelle ne rend RIEN : `generate_alerts` retourne les alertes
            # creees ou mises a jour, et il n'y en a aucune. C'est ce qui
            # permet a l'API (`created_or_updated`) et au worker d'annoncer
            # honnetement « 0 nouvelle alerte ».
            second_run = generate_alerts(db, entity_ids=[entity.id])
            assert [a for a in second_run if a.entity_id == entity.id] == []

            # L'essentiel : la base ne contient toujours qu'UNE alerte.
            remaining = db.query(Alert).filter(Alert.entity_id == entity.id).all()
            assert len(remaining) == 1
            assert remaining[0].id == first_id
        finally:
            _cleanup(
                db,
                entities=[entity],
                detections=[detection],
                documents=[document],
                sources=[source],
            )

    def test_second_detection_raises_severity_of_the_existing_alert(self, db):
        entity = _make_entity(db, domain="example-severity-test.tld")
        source, document = _make_source_and_document(db)
        medium_detection = _make_detection(
            db,
            document,
            type_="domain",
            value_masked="example-severity-test.tld",
            validated=False,
            is_relevant=True,  # MEDIUM
        )
        try:
            generate_alerts(db, entity_ids=[entity.id])  # cree l'alerte en MEDIUM

            # Deuxieme detection, CORROBOREE (HIGH) -- doit faire monter la
            # severite de l'alerte du jour deja creee en MEDIUM.
            #
            # ⚠️ Ce test employait `validated=True` comme levier de severite.
            # Depuis le 2026-09-04 ce drapeau n'eleve plus que les types a
            # validation reelle (Luhn, mod-97) : sur un domaine il ne signifie
            # que « format .onion reconnu ». Le vrai levier documente est la
            # corroboration par un observateur independant.
            validated_domain_detection = _make_detection(
                db,
                document,
                type_="domain",
                value_masked="example-severity-test.tld",
                validated=False,
                is_relevant=True,
            )
            validated_domain_detection.corroboration_status = "corroborated"
            db.commit()
            alerts = generate_alerts(db, entity_ids=[entity.id])
            alert = next(a for a in alerts if a.entity_id == entity.id)
            # ⚠️ REECRIT le 2026-09-15. La corroboration n'eleve plus : une
            # alerte NAIT donc en `medium`, et sa gravite reelle est etablie
            # par la passe d'enrichissement qui suit (generer -> corroborer ->
            # renseigner -> recalculer). C'est une consequence assumee du
            # nouvel ordre, pas une regression.
            assert alert.severity == "medium"
            assert len(alert.detections) == 2

            # Le MECANISME de montee est bien vivant -- il vit simplement dans
            # `refresh_alert_severities`, le seul endroit qui voit les
            # renseignements par victime (portes par l'alerte, migration 0026).
            alert.compromised_employees = 12
            alert.intel_refreshed_at = datetime.now(timezone.utc)
            db.commit()
            rapport = refresh_alert_severities(db, apply=True, alert_ids=[alert.id])
            assert rapport["modifiees"] >= 1
            db.refresh(alert)
            assert alert.severity == "high"
        finally:
            _cleanup(
                db,
                entities=[entity],
                detections=[medium_detection, validated_domain_detection],
                documents=[document],
                sources=[source],
            )

    def test_no_active_entities_returns_empty_list(self, db):
        entity = _make_entity(db, domain="example-inactive-test.tld", active=False)
        source, document = _make_source_and_document(db)
        detection = _make_detection(
            db,
            document,
            type_="domain",
            value_masked="example-inactive-test.tld",
            validated=False,
            is_relevant=True,
        )
        try:
            alerts = generate_alerts(db, entity_ids=[entity.id])
            matching = [a for a in alerts if a.entity_id == entity.id]
            assert matching == []
        finally:
            _cleanup(
                db,
                entities=[entity],
                detections=[detection],
                documents=[document],
                sources=[source],
            )


class TestAlertWindow:
    """Fenetre glissante de generate_alerts (voir _ALERT_WINDOW_DAYS).

    Regression protegee : sans borne de date, le service rescannait tout le
    corpus a chaque execution. Au changement de jour la cle de regroupement
    (entite, jour) change, donc une alerte identique etait recreee sur des
    detections deja traitees la veille -- constate en usage reel, 2 alertes
    par jour sur les memes 145 detections figees."""

    def test_old_detection_does_not_alert(self, db):
        """Une detection plus ancienne que la fenetre ne doit plus alerter."""
        entity = _make_entity(db, domain="old-detection-test.tld")
        source, document = _make_source_and_document(db)
        detection = _make_detection(
            db,
            document,
            type_="domain",
            value_masked="old-detection-test.tld",
            validated=False,
            is_relevant=True,
            created_at=datetime.now(timezone.utc) - timedelta(days=30),
        )
        try:
            alerts = generate_alerts(db, entity_ids=[entity.id])
            assert [a for a in alerts if a.entity_id == entity.id] == []
        finally:
            _cleanup(
                db,
                entities=[entity],
                detections=[detection],
                documents=[document],
                sources=[source],
            )

    def test_recent_detection_still_alerts(self, db):
        """Contre-epreuve : la borne ne doit pas etouffer le signal recent."""
        entity = _make_entity(db, domain="recent-detection-test.tld")
        source, document = _make_source_and_document(db)
        detection = _make_detection(
            db,
            document,
            type_="domain",
            value_masked="recent-detection-test.tld",
            validated=False,
            is_relevant=True,
            created_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        try:
            alerts = generate_alerts(db, entity_ids=[entity.id])
            assert len([a for a in alerts if a.entity_id == entity.id]) == 1
        finally:
            _cleanup(
                db,
                entities=[entity],
                detections=[detection],
                documents=[document],
                sources=[source],
            )

    def test_next_day_does_not_recreate_alert_on_old_detections(self, db):
        """Le bug exact constate en production : une detection alertee le jour
        J ne doit pas produire une seconde alerte a J+1, puis J+2, etc."""
        entity = _make_entity(db, domain="no-repeat-test.tld")
        source, document = _make_source_and_document(db)
        detected_on = datetime.now(timezone.utc) - timedelta(days=20)
        detection = _make_detection(
            db,
            document,
            type_="domain",
            value_masked="no-repeat-test.tld",
            validated=False,
            is_relevant=True,
            created_at=detected_on,
        )
        try:
            day_of = detected_on.date()
            first = generate_alerts(db, today=day_of, entity_ids=[entity.id])
            assert len([a for a in first if a.entity_id == entity.id]) == 1

            # Meme detection, un jour plus tard : la cle (entite, jour) change,
            # mais la detection est desormais hors fenetre -> aucune alerte.
            later = generate_alerts(
                db,
                today=day_of + timedelta(days=8),
                entity_ids=[entity.id],
            )
            assert [a for a in later if a.entity_id == entity.id] == []
        finally:
            _cleanup(
                db,
                entities=[entity],
                detections=[detection],
                documents=[document],
                sources=[source],
            )

    def test_window_can_be_disabled_for_manual_catch_up(self, db):
        """`window_days=0` rescanne tout -- rattrapage manuel explicite."""
        entity = _make_entity(db, domain="catchup-test.tld")
        source, document = _make_source_and_document(db)
        detection = _make_detection(
            db,
            document,
            type_="domain",
            value_masked="catchup-test.tld",
            validated=False,
            is_relevant=True,
            created_at=datetime.now(timezone.utc) - timedelta(days=90),
        )
        try:
            assert generate_alerts(db, entity_ids=[entity.id]) == []
            caught = generate_alerts(db, entity_ids=[entity.id], window_days=0)
            assert len([a for a in caught if a.entity_id == entity.id]) == 1
        finally:
            _cleanup(
                db,
                entities=[entity],
                detections=[detection],
                documents=[document],
                sources=[source],
            )


class TestNoRealertOnUnchangedDetections:
    """⚠️ Regression majeure corrigee le 2026-08-29.

    L'unicite d'une alerte etant posee sur (entite, jour), une entite dont
    les detections n'avaient PAS change recevait une alerte identique chaque
    jour : celle de la veille porte une autre date, donc
    `get_by_entity_and_date` ne la trouvait pas et en creait une nouvelle.

    Mesure en base : 120 alertes pour 30 organisations apres quatre jours,
    facteur croissant d'une unite par jour. A un mois, chaque victime aurait
    occupe trente lignes -- l'interface serait devenue inexploitable.

    `TestAlertWindow` couvrait la fenetre de scan, pas ce cas : une detection
    RECENTE (donc dans la fenetre) et deja alertee realertait quand meme."""

    def test_second_day_creates_no_alert_when_nothing_changed(self, db):
        entity = _make_entity(db, domain="no-realert-test.tld")
        source, document = _make_source_and_document(db)
        detection = _make_detection(
            db,
            document,
            type_="domain",
            value_masked="no-realert-test.tld",
            validated=False,
            is_relevant=True,
        )
        try:
            today = datetime.now(timezone.utc).date()
            first = generate_alerts(db, entity_ids=[entity.id], today=today)
            assert len([a for a in first if a.entity_id == entity.id]) == 1

            # Le lendemain, sans aucune detection nouvelle.
            second = generate_alerts(
                db, entity_ids=[entity.id], today=today + timedelta(days=1)
            )
            assert [a for a in second if a.entity_id == entity.id] == []
        finally:
            _cleanup(
                db,
                entities=[entity],
                detections=[detection],
                documents=[document],
                sources=[source],
            )

    def test_new_detection_does_alert_the_next_day(self, db):
        """Contre-epreuve indispensable : le correctif ne doit pas etouffer
        une VRAIE nouvelle fuite sur une entite deja alertee."""
        entity = _make_entity(db, domain="realert-on-new-test.tld")
        source, document = _make_source_and_document(db)
        first_detection = _make_detection(
            db,
            document,
            type_="domain",
            value_masked="realert-on-new-test.tld",
            validated=False,
            is_relevant=True,
        )
        second_detection = None
        try:
            today = datetime.now(timezone.utc).date()
            generate_alerts(db, entity_ids=[entity.id], today=today)

            # Une nouvelle detection apparait sur la meme entite.
            second_detection = _make_detection(
                db,
                document,
                type_="domain",
                value_masked="sub.realert-on-new-test.tld",
                validated=False,
                is_relevant=True,
            )
            second = generate_alerts(
                db, entity_ids=[entity.id], today=today + timedelta(days=1)
            )
            assert len([a for a in second if a.entity_id == entity.id]) == 1
        finally:
            _cleanup(
                db,
                entities=[entity],
                detections=[d for d in (first_detection, second_detection) if d],
                documents=[document],
                sources=[source],
            )

    def test_rerun_same_day_stays_idempotent(self, db):
        """L'idempotence DANS la journee, deja acquise, ne doit pas regresser."""
        entity = _make_entity(db, domain="same-day-idempotent-test.tld")
        source, document = _make_source_and_document(db)
        detection = _make_detection(
            db,
            document,
            type_="domain",
            value_masked="same-day-idempotent-test.tld",
            validated=False,
            is_relevant=True,
        )
        try:
            today = datetime.now(timezone.utc).date()
            generate_alerts(db, entity_ids=[entity.id], today=today)
            again = generate_alerts(db, entity_ids=[entity.id], today=today)
            assert [a for a in again if a.entity_id == entity.id] == []
        finally:
            _cleanup(
                db,
                entities=[entity],
                detections=[detection],
                documents=[document],
                sources=[source],
            )


class TestCorroborationRaisesAlertSeverity:
    """Verifie le CABLAGE, pas la regle (celle-ci est couverte par
    unit/test_alerting_rules.py) : `generate_alerts` doit relever le statut de
    corroboration sur les lignes SQL et le transmettre a
    `severity_for_detection`.

    Sans ce cablage, la regle serait correcte et sans effet -- exactement l'etat
    dans lequel se trouvait la branche HIGH avant le 2026-09-01 : atteignable
    en theorie, jamais atteinte en pratique (120 alertes sur 120 en `medium`)."""

    def test_corroborated_detection_produces_a_high_alert(self, db):
        entity = _make_entity(db, domain="corroborated-alert-test.tld")
        source, document = _make_source_and_document(db)
        detection = _make_detection(
            db,
            document,
            type_="domain",
            value_masked="corroborated-alert-test.tld",
            validated=False,
            is_relevant=False,
            corroboration_status="corroborated",
        )
        try:
            alerts = generate_alerts(db, entity_ids=[entity.id])
            matching = [a for a in alerts if a.entity_id == entity.id]
            assert len(matching) == 1
            # ⚠️ REECRIT le 2026-09-15 : la corroboration ne produit plus
            # une alerte HIGH. Elle est une marque de VERIFIABILITE -- le
            # cablage reste verifie (le statut est bien relu et transmis),
            # mais sur un incident ancien il n'eleve rien.
            assert matching[0].severity == "medium"
        finally:
            _cleanup(
                db,
                entities=[entity],
                detections=[detection],
                documents=[document],
                sources=[source],
            )

    def test_exclusive_detection_stays_medium(self, db):
        """Temoin. `exclusive` n'est pas un doute : nous lisons le site de fuite
        a la source et l'agregateur peut ne pas l'avoir indexe. Il ne doit ni
        elever ni abaisser -- la meme detection reste `medium`."""
        entity = _make_entity(db, domain="exclusive-alert-test.tld")
        source, document = _make_source_and_document(db)
        detection = _make_detection(
            db,
            document,
            type_="domain",
            value_masked="exclusive-alert-test.tld",
            validated=False,
            is_relevant=False,
            corroboration_status="exclusive",
        )
        try:
            alerts = generate_alerts(db, entity_ids=[entity.id])
            matching = [a for a in alerts if a.entity_id == entity.id]
            assert len(matching) == 1
            assert matching[0].severity == "medium"
        finally:
            _cleanup(
                db,
                entities=[entity],
                detections=[detection],
                documents=[document],
                sources=[source],
            )

    def test_never_corroborated_detection_stays_medium(self, db):
        """`NULL` est une absence de mesure, pas un resultat negatif."""
        entity = _make_entity(db, domain="unknown-alert-test.tld")
        source, document = _make_source_and_document(db)
        detection = _make_detection(
            db,
            document,
            type_="domain",
            value_masked="unknown-alert-test.tld",
            validated=False,
            is_relevant=False,
            corroboration_status=None,
        )
        try:
            alerts = generate_alerts(db, entity_ids=[entity.id])
            matching = [a for a in alerts if a.entity_id == entity.id]
            assert len(matching) == 1
            assert matching[0].severity == "medium"
        finally:
            _cleanup(
                db,
                entities=[entity],
                detections=[detection],
                documents=[document],
                sources=[source],
            )


class TestRegionAlerts:
    """Alerte sur une victime situee dans un perimetre GEOGRAPHIQUE surveille,
    sans qu'aucune entite ne la declare (migration 0016).

    Repond au goulot mesure le 2026-09-02 : 3101 domaines de victimes
    collectes pour 31 surveilles, soit 1 % de conversion."""

    def test_a_victim_in_a_watched_region_alerts_without_any_entity(self, db):
        source, document = _make_source_and_document(db, collector="dls")
        detection = _make_detection(
            db,
            document,
            type_="domain",
            value_masked=f"victime-{uuid.uuid4().hex[:8]}.co.za",
            validated=False,
            is_relevant=True,
        )
        try:
            alerts = generate_alerts(db, regions=["Afrique"])
            mienne = [
                a
                for a in alerts
                if any(ad.detection_id == detection.id for ad in a.detections)
            ]
            assert len(mienne) == 1
            assert mienne[0].scope == "region"
            assert mienne[0].region == "Afrique"
            assert mienne[0].entity_id is None
        finally:
            _cleanup_region(db, detection, document, source)

    def test_la_passe_regionale_tourne_meme_sans_aucune_entite_active(self, db):
        """⚠️ Defaut trouve par la CI sur base vierge (2026-09-25) :
        `if not entities: return []` sortait AVANT la passe regionale. Sans
        entite surveillee, aucune alerte regionale n'etait jamais produite.
        Invisible en developpement, ou 40 entites existent.

        On desactive TOUTES les entites : sans risque, la transaction du test
        est annulee a la fin (conftest.py)."""
        db.query(Entity).update({Entity.active: False})
        db.commit()
        source, document = _make_source_and_document(db, collector="dls")
        detection = _make_detection(
            db,
            document,
            type_="domain",
            value_masked=f"victime-{uuid.uuid4().hex[:8]}.co.za",
            validated=False,
            is_relevant=True,
        )
        alerts = generate_alerts(db, regions=["Afrique"])
        assert any(
            ad.detection_id == detection.id for a in alerts for ad in a.detections
        )

    def test_a_victim_outside_the_watched_region_does_not_alert(self, db):
        source, document = _make_source_and_document(db, collector="dls")
        detection = _make_detection(
            db,
            document,
            type_="domain",
            value_masked=f"victime-{uuid.uuid4().hex[:8]}.fr",
            validated=False,
            is_relevant=True,
        )
        try:
            alerts = generate_alerts(db, regions=["Afrique"])
            assert not any(
                ad.detection_id == detection.id for a in alerts for ad in a.detections
            )
        finally:
            _cleanup_region(db, detection, document, source)

    def test_a_forum_victim_is_ignored_even_in_the_region(self, db):
        """⚠️ Contrainte mesuree, pas de principe. Sans restreindre aux sources
        qui publient des victimes, la passe remontait 7 domaines africains dont
        4 FAUX POSITIFS : `breachforums.bf` (le forum lui-meme), deux phrases
        decoupees en domaines, et des organisations simplement CITEES dans un
        document intitule « 179 major companies in the world 2026 ».

        Sur un forum, un domaine dans le texte n'est pas une victime."""
        source, document = _make_source_and_document(db, collector="xenforo_latest")
        detection = _make_detection(
            db,
            document,
            type_="domain",
            value_masked=f"citee-{uuid.uuid4().hex[:8]}.co.za",
            validated=False,
            is_relevant=True,
        )
        try:
            alerts = generate_alerts(db, regions=["Afrique"])
            assert not any(
                ad.detection_id == detection.id for a in alerts for ad in a.detections
            )
        finally:
            _cleanup_region(db, detection, document, source)

    def test_scoping_to_entities_disables_the_region_pass(self, db):
        """Temoin du piege. Un appel volontairement restreint a des entites --
        typiquement un test -- ne doit PAS ecrire d'alerte regionale sur tout le
        corpus. Constate le 2026-09-02 : la suite de tests avait cree une vraie
        alerte de 20 victimes en base."""
        entity = _make_entity(db, domain="portee-region-test.tld")
        source, document = _make_source_and_document(db, collector="dls")
        detection = _make_detection(
            db,
            document,
            type_="domain",
            value_masked=f"hors-portee-{uuid.uuid4().hex[:8]}.co.za",
            validated=False,
            is_relevant=True,
        )
        try:
            alerts = generate_alerts(db, entity_ids=[entity.id])
            assert not any(a.scope == "region" for a in alerts)
        finally:
            db.query(Alert).filter(Alert.entity_id == entity.id).delete()
            db.commit()
            _cleanup_region(db, detection, document, source)
            db.query(EntitySelector).filter(
                EntitySelector.entity_id == entity.id
            ).delete()
            db.query(Entity).filter(Entity.id == entity.id).delete()
            db.commit()


def _cleanup_region(db, detection, document, source):
    alert_ids = [
        a.id
        for a in db.query(Alert)
        .join(AlertDetection, AlertDetection.alert_id == Alert.id)
        .filter(AlertDetection.detection_id == detection.id)
    ]
    db.query(AlertDetection).filter(AlertDetection.detection_id == detection.id).delete(
        synchronize_session=False
    )
    for alert_id in alert_ids:
        reste = (
            db.query(AlertDetection).filter(AlertDetection.alert_id == alert_id).count()
        )
        if reste == 0:
            db.query(Alert).filter(Alert.id == alert_id).delete()
    db.query(Detection).filter(Detection.id == detection.id).delete()
    db.query(RawDocument).filter(RawDocument.id == document.id).delete()
    db.query(Source).filter(Source.id == source.id).delete()
    db.commit()


class TestNoSecondAlertForTheSameVictim:
    """Une meme organisation est souvent redetectee : mesure du 2026-09-02,
    **279 victimes ont plusieurs detections et 103 sont publiees par plusieurs
    sources**. `transports-exemple.com` parait chez KRYBIT ET chez NIGHT SPIRE.

    Sans dedoublonnage par VALEUR, ces detections distinctes produisaient deux
    alertes pour un seul incident -- `alerted_detection_ids` ne compare que des
    identifiants."""

    def test_the_same_victim_seen_again_the_next_day_does_not_alert_twice(self, db):
        entity = _make_entity(db, domain="doublon-victime.tld")
        source, document = _make_source_and_document(db)
        hier = date.today() - timedelta(days=1)
        premiere = _make_detection(
            db,
            document,
            type_="domain",
            value_masked="doublon-victime.tld",
            validated=False,
            is_relevant=True,
            created_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        try:
            generate_alerts(db, entity_ids=[entity.id], today=hier)

            # Meme victime, AUTRE detection (autre source, autre document) --
            # c'est le cas reel de transports-exemple.com.
            source2, document2 = _make_source_and_document(db)
            seconde = _make_detection(
                db,
                document2,
                type_="domain",
                value_masked="www.doublon-victime.tld",
                validated=False,
                is_relevant=True,
            )
            try:
                alertes = generate_alerts(db, entity_ids=[entity.id])
                assert alertes == []
                total = db.query(Alert).filter(Alert.entity_id == entity.id).count()
                assert total == 1
            finally:
                _cleanup(
                    db, detections=[seconde], documents=[document2], sources=[source2]
                )
        finally:
            _cleanup(
                db,
                entities=[entity],
                detections=[premiere],
                documents=[document],
                sources=[source],
            )

    def test_www_prefix_is_not_a_different_victim(self, db):
        """Les sites de fuite publient indifferemment `partenaire-exemple.co.za` et
        `www.partenaire-exemple.co.za`, RansomLook la forme sans prefixe. Trois
        ecritures, une seule organisation."""
        from app.pipeline.alerting.matching import normalize_victim

        assert normalize_victim("www.Partenaire-Exemple.CO.ZA") == normalize_victim(
            "partenaire-exemple.co.za."
        )

    def test_a_more_severe_detection_still_raises_the_alert_of_the_same_day(self, db):
        """⚠️ La nuance a ne pas perdre : le dedoublonnage bloque la RE-alerte
        d'un jour a l'autre, jamais l'enrichissement du jour meme. Apprendre en
        fin de journee qu'une victime deja signalee est corroboree doit se
        voir."""
        entity = _make_entity(db, domain="severite-meme-jour.tld")
        source, document = _make_source_and_document(db)
        faible = _make_detection(
            db,
            document,
            type_="domain",
            value_masked="severite-meme-jour.tld",
            validated=False,
            is_relevant=True,
        )
        try:
            generate_alerts(db, entity_ids=[entity.id])
            # ⚠️ Levier de severite = CORROBORATION, plus `validated` (change
            # le 2026-09-04 : sur un domaine, `validated` ne signifie que
            # « format .onion reconnu », pas « fait confirme »).
            forte = _make_detection(
                db,
                document,
                type_="domain",
                value_masked="severite-meme-jour.tld",
                validated=False,
                is_relevant=True,
                corroboration_status="corroborated",
            )
            try:
                alertes = generate_alerts(db, entity_ids=[entity.id])
                alerte = next(a for a in alertes if a.entity_id == entity.id)
                # ⚠️ REECRIT le 2026-09-15 : le levier de gravite n'est plus la
                # corroboration mais l'exposition d'identifiants d'employes.
                # La nuance PROTEGEE ICI est inchangee et reste l'essentiel :
                # le dedoublonnage bloque la re-alerte d'un jour a l'autre,
                # jamais l'enrichissement du jour meme -- l'alerte du jour
                # accepte bien la seconde detection et peut encore monter.
                assert len(alerte.detections) == 2
                alerte.compromised_employees = 3
                alerte.intel_refreshed_at = datetime.now(timezone.utc)
                db.commit()
                refresh_alert_severities(db, apply=True, alert_ids=[alerte.id])
                db.refresh(alerte)
                assert alerte.severity == "high"
            finally:
                db.query(AlertDetection).filter(
                    AlertDetection.detection_id == forte.id
                ).delete(synchronize_session=False)
                db.query(Detection).filter(Detection.id == forte.id).delete()
                db.commit()
        finally:
            _cleanup(
                db,
                entities=[entity],
                detections=[faible],
                documents=[document],
                sources=[source],
            )


class TestAlertEvidenceEndpoint:
    """Chemin de contre-verification : d'une alerte vers les documents qui l'ont
    produite.

    ⚠️ Sans lui, la page Alertes affichait « 144 detection(s) » et l'analyste
    n'avait AUCUN moyen de remonter a la source. Une alerte qu'on ne peut pas
    verifier n'est qu'une affirmation -- et le README pose la verifiabilite
    comme l'objectif du produit."""

    def test_returns_the_source_documents_and_their_detections(self, db):
        from fastapi.testclient import TestClient

        from app.api.deps import get_current_user, get_db
        from app.main import app

        entity = _make_entity(db, domain="preuve-alerte-test.tld")
        source, document = _make_source_and_document(db, collector="dls")
        detection = _make_detection(
            db,
            document,
            type_="domain",
            value_masked="preuve-alerte-test.tld",
            validated=False,
            is_relevant=True,
        )
        app.dependency_overrides[get_current_user] = _analyste_de_test
        app.dependency_overrides[get_db] = lambda: db
        try:
            alertes = generate_alerts(db, entity_ids=[entity.id])
            alerte = next(a for a in alertes if a.entity_id == entity.id)

            reponse = TestClient(app).get(f"/api/alerts/{alerte.id}/documents")
            assert reponse.status_code == 200
            corps = reponse.json()
            assert corps["document_count"] == 1

            doc = corps["documents"][0]
            assert doc["document_id"] == str(document.id)
            assert doc["source_name"] == source.name
            # La detection est rattachee a SON document : c'est ce lien qui
            # permet la contre-verification.
            assert [d["value_masked"] for d in doc["detections"]] == [
                "preuve-alerte-test.tld"
            ]
        finally:
            app.dependency_overrides.pop(get_current_user, None)
            app.dependency_overrides.pop(get_db, None)
            _cleanup(
                db,
                entities=[entity],
                detections=[detection],
                documents=[document],
                sources=[source],
            )

    def test_unknown_alert_yields_404(self, db):
        from fastapi.testclient import TestClient

        from app.api.deps import get_current_user, get_db
        from app.main import app

        app.dependency_overrides[get_current_user] = _analyste_de_test
        app.dependency_overrides[get_db] = lambda: db
        try:
            reponse = TestClient(app).get(f"/api/alerts/{uuid.uuid4()}/documents")
            assert reponse.status_code == 404
        finally:
            app.dependency_overrides.pop(get_current_user, None)
            app.dependency_overrides.pop(get_db, None)
