import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.contracts.entity import EntityContract, EntitySelector, SelectorType


def _make_entity(**overrides):
    defaults = {
        "id": uuid.uuid4(),
        "name": "Test Org",
        "selectors": [EntitySelector(type=SelectorType.DOMAIN, value="example.test")],
        "created_at": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    return EntityContract(**defaults)


class TestEntityContract:
    def test_creates_with_valid_selectors(self):
        entity = _make_entity(
            selectors=[
                EntitySelector(type=SelectorType.DOMAIN, value="example.test"),
                EntitySelector(type=SelectorType.EMAIL_DOMAIN, value="example.test"),
                EntitySelector(type=SelectorType.KEYWORD, value="ExampleOrg"),
            ]
        )
        assert len(entity.selectors) == 3

    def test_active_defaults_to_true(self):
        assert _make_entity().active is True

    def test_verification_status_defaults_to_pending(self):
        entity = _make_entity()
        assert entity.verification_status == "pending"
        assert entity.verification_method is None
        assert entity.verified_at is None

    def test_rejects_unknown_selector_type(self):
        with pytest.raises(ValidationError):
            EntitySelector(type="ip", value="203.0.113.1")

    def test_rejects_unknown_field_on_entity(self):
        with pytest.raises(ValidationError):
            _make_entity(domain="example.test")

    def test_rejects_unknown_field_on_selector(self):
        with pytest.raises(ValidationError):
            EntitySelector(
                type=SelectorType.DOMAIN, value="example.test", raw_ip="203.0.113.1"
            )
