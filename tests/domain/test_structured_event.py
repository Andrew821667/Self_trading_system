from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from trading_system.domain import StructuredEvent, ValidationStatus


def make_event(**overrides: object) -> StructuredEvent:
    fields = dict(
        event_id="ev-1",
        source_id="src-1",
        event_family="E-1",
        schema_version="1.0",
        event_time=datetime(2026, 1, 1, tzinfo=UTC),
        issuer_id="issuer-1",
        facts={"decision_date": "2026-01-01"},
        extraction_model="model-x@2026-01-01",
        prompt_version="v1",
        validation_status=ValidationStatus.VALID,
        confidence=0.9,
        public_source_basis=["src-1"],
    )
    fields.update(overrides)
    return StructuredEvent(**fields)


def test_valid_event_with_source_basis_is_tradable() -> None:
    assert make_event().is_tradable is True


def test_ambiguous_event_is_never_tradable_regardless_of_confidence() -> None:
    event = make_event(validation_status=ValidationStatus.AMBIGUOUS, confidence=0.99)
    assert event.is_tradable is False


def test_invalid_event_is_never_tradable() -> None:
    assert make_event(validation_status=ValidationStatus.INVALID).is_tradable is False


def test_valid_event_without_public_source_basis_is_not_tradable() -> None:
    assert make_event(public_source_basis=[]).is_tradable is False


def test_rejects_unknown_validation_status() -> None:
    with pytest.raises(ValidationError):
        make_event(validation_status="MAYBE")
