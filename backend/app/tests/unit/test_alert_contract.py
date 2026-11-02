import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.contracts.alert import AlertContract, AlertSeverity


def _make_alert(**overrides):
    defaults = {
        "id": uuid.uuid4(),
        "entity_id": uuid.uuid4(),
        "severity": AlertSeverity.HIGH,
        "created_at": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    return AlertContract(**defaults)


class TestAlertContract:
    def test_creates_with_valid_severity(self):
        alert = _make_alert(severity=AlertSeverity.CRITICAL)
        assert alert.severity == "critical"

    def test_status_defaults_to_open(self):
        assert _make_alert().status == "open"

    def test_summary_defaults_to_none(self):
        assert _make_alert().summary is None

    def test_accepts_an_explicit_summary(self):
        alert = _make_alert(summary="Fuite de 3 identifiants confirmes par checksum.")
        assert alert.summary == "Fuite de 3 identifiants confirmes par checksum."

    def test_rejects_unknown_severity(self):
        with pytest.raises(ValidationError):
            _make_alert(severity="apocalyptic")

    def test_rejects_unknown_status(self):
        with pytest.raises(ValidationError):
            _make_alert(status="ignored")

    def test_rejects_unknown_field(self):
        with pytest.raises(ValidationError):
            _make_alert(priority="high")
