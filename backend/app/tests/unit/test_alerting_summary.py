import uuid
from datetime import datetime, timedelta, timezone

from app.contracts.detection import DetectionContract, DetectionType
from app.contracts.entity import EntityContract, EntitySelector, SelectorType
from app.pipeline.alerting.summary import RECENT_DETECTIONS_LIMIT, summarize_entity


def _make_detection(**overrides):
    defaults = {
        "id": uuid.uuid4(),
        "document_id": uuid.uuid4(),
        "type": DetectionType.DOMAIN,
        "value_masked": "operateur.sn",
        "value_hash": "deadbeef",
        "validated": True,
        "is_relevant": False,
        "created_at": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    return DetectionContract(**defaults)


def _make_entity(**overrides):
    defaults = {
        "id": uuid.uuid4(),
        "name": "Operateur Senegal",
        "selectors": [EntitySelector(type=SelectorType.DOMAIN, value="operateur.sn")],
        "created_at": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    return EntityContract(**defaults)


class TestSummarizeEntity:
    def test_counts_only_matching_detections(self):
        entity = _make_entity()
        matching = _make_detection(value_masked="operateur.sn")
        unrelated = _make_detection(value_masked="unrelated.example")
        summary = summarize_entity(entity, [matching, unrelated])
        assert summary.total_detections == 1

    def test_entity_id_and_name_are_reported(self):
        entity = _make_entity(name="Operateur Senegal")
        summary = summarize_entity(entity, [])
        assert summary.entity_id == str(entity.id)
        assert summary.entity_name == "Operateur Senegal"

    def test_counts_by_type_aggregates_matching_detections(self):
        detections = [
            _make_detection(value_masked="operateur.sn", type=DetectionType.DOMAIN),
            _make_detection(
                value_masked="mail.operateur.sn", type=DetectionType.DOMAIN
            ),
            _make_detection(
                value_masked="j***@operateur.sn",
                type=DetectionType.EMAIL,
            ),
        ]
        entity_with_email_selector = _make_entity(
            selectors=[
                EntitySelector(type=SelectorType.DOMAIN, value="operateur.sn"),
                EntitySelector(type=SelectorType.EMAIL_DOMAIN, value="operateur.sn"),
            ]
        )
        summary = summarize_entity(entity_with_email_selector, detections)
        assert summary.counts_by_type == {"domain": 2, "email": 1}

    def test_counts_by_severity_uses_the_same_rules_as_rules_py(self):
        entity = _make_entity()
        # ⚠️ MEDIUM et non HIGH depuis le 2026-09-04 : `validated` n'eleve plus
        # que les types a validation reelle (Luhn, mod-97). Sur un domaine il
        # ne signifie que « format .onion reconnu ». Le test verifie l'accord
        # avec rules.py, pas une valeur en particulier.
        moyenne = _make_detection(
            value_masked="operateur.sn",
            type=DetectionType.DOMAIN,
            validated=True,
            is_relevant=True,
        )
        # ⚠️ Correction du 2026-09-04 : `summarize_entity` ne traite QUE des
        # detections deja rattachees a l'entite, il doit donc calculer la
        # severite avec `matches_watched_entity=True` -- comme l'alerting.
        # Auparavant la page Statistiques affichait LOW la ou l'alerte disait
        # MEDIUM, sur exactement la meme detection.
        #
        # Consequence directe : une detection rattachee ne peut plus retomber
        # en LOW du seul fait que la watchlist de vocabulaire n'a pas matche.
        rattachee_sans_mot_cle = _make_detection(
            value_masked="operateur.sn", is_relevant=False
        )
        summary = summarize_entity(entity, [moyenne, rattachee_sans_mot_cle])
        assert summary.counts_by_severity == {"medium": 2}

    def test_recent_detections_are_sorted_by_created_at_descending(self):
        entity = _make_entity()
        now = datetime.now(timezone.utc)
        older = _make_detection(
            value_masked="operateur.sn", created_at=now - timedelta(days=1)
        )
        newer = _make_detection(value_masked="operateur.sn", created_at=now)
        summary = summarize_entity(entity, [older, newer])
        assert [d.id for d in summary.recent_detections] == [
            str(newer.id),
            str(older.id),
        ]

    def test_recent_detections_are_capped(self):
        entity = _make_entity()
        detections = [
            _make_detection(value_masked="operateur.sn")
            for _ in range(RECENT_DETECTIONS_LIMIT + 5)
        ]
        summary = summarize_entity(entity, detections)
        assert summary.total_detections == RECENT_DETECTIONS_LIMIT + 5
        assert len(summary.recent_detections) == RECENT_DETECTIONS_LIMIT

    def test_no_matching_detections_returns_empty_summary(self):
        entity = _make_entity()
        summary = summarize_entity(
            entity, [_make_detection(value_masked="unrelated.example")]
        )
        assert summary.total_detections == 0
        assert summary.counts_by_type == {}
        assert summary.counts_by_severity == {}
        assert summary.recent_detections == []
