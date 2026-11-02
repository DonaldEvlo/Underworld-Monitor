import uuid
from datetime import datetime, timezone

from app.contracts.entity import EntityContract, EntitySelector, SelectorType
from app.pipeline.alerting.candidates import filter_new_candidates


def _make_entity(**overrides):
    defaults = {
        "id": uuid.uuid4(),
        "name": "Test Org",
        "selectors": [],
        "created_at": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    return EntityContract(**defaults)


class TestFilterNewCandidates:
    def test_candidate_matching_no_entity_is_kept(self):
        candidates = [("Telco", "hash1", 5)]
        assert filter_new_candidates(candidates, []) == candidates

    def test_candidate_matching_entity_name_is_excluded(self):
        candidates = [("Telco", "hash1", 5), ("Acme", "hash2", 3)]
        entity = _make_entity(name="Telco")
        result = filter_new_candidates(candidates, [entity])
        assert result == [("Acme", "hash2", 3)]

    def test_candidate_matching_keyword_selector_is_excluded(self):
        candidates = [("Telco", "hash1", 5)]
        entity = _make_entity(
            name="Autre nom",
            selectors=[EntitySelector(type=SelectorType.KEYWORD, value="Telco")],
        )
        assert filter_new_candidates(candidates, [entity]) == []

    def test_candidate_matching_domain_label_is_excluded(self):
        candidates = [("Telco", "hash1", 5)]
        entity = _make_entity(
            name="Autre nom",
            selectors=[EntitySelector(type=SelectorType.DOMAIN, value="telco.sn")],
        )
        assert filter_new_candidates(candidates, [entity]) == []

    def test_candidate_matching_email_domain_label_is_excluded(self):
        candidates = [("Telco", "hash1", 5)]
        entity = _make_entity(
            name="Autre nom",
            selectors=[
                EntitySelector(type=SelectorType.EMAIL_DOMAIN, value="telco.sn")
            ],
        )
        assert filter_new_candidates(candidates, [entity]) == []

    def test_comparison_is_case_insensitive(self):
        candidates = [("TELCO", "hash1", 5)]
        entity = _make_entity(name="telco")
        assert filter_new_candidates(candidates, [entity]) == []

    def test_inactive_entity_does_not_exclude_candidate(self):
        candidates = [("Telco", "hash1", 5)]
        entity = _make_entity(name="Telco", active=False)
        assert filter_new_candidates(candidates, [entity]) == candidates

    def test_unrelated_domain_selector_does_not_exclude_candidate(self):
        candidates = [("Telco", "hash1", 5)]
        entity = _make_entity(
            name="Autre nom",
            selectors=[EntitySelector(type=SelectorType.DOMAIN, value="operateur.sn")],
        )
        assert filter_new_candidates(candidates, [entity]) == candidates
