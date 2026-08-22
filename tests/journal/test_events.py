from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from trading_system.journal import EventEnvelope, EventType


def make_event(**overrides: object) -> EventEnvelope:
    fields = dict(
        event_id="evt-1",
        event_type=EventType.STRUCTURED_EVENT_CREATED,
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        recorded_at=datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC),
        correlation_id="corr-1",
        actor="document-intelligence-service",
        payload={"issuer_id": "issuer-1"},
        artifact_refs=["src-1"],
        schema_version="1.0",
    )
    fields.update(overrides)
    return EventEnvelope(**fields)


def test_round_trip() -> None:
    event = make_event()
    assert event.event_type is EventType.STRUCTURED_EVENT_CREATED
    assert event.causation_id is None


def test_all_tz_section_20_event_types_are_defined() -> None:
    required = {
        "source_polled",
        "source_document_seen",
        "source_document_amended",
        "document_stored",
        "document_parsed",
        "structured_event_created",
        "structured_event_invalid",
        "structured_event_superseded",
        "signal_generated",
        "intent_created",
        "intents_netted",
        "compliance_checked",
        "manipulation_checked",
        "risk_evaluated",
        "approval_issued",
        "order_submitted",
        "order_acked",
        "order_filled",
        "order_cancelled",
        "protective_policy_activated",
        "protective_policy_failed",
        "position_opened",
        "position_updated",
        "position_closed",
        "reconciliation_performed",
        "reconciliation_mismatch",
        "strategy_state_changed",
        "factor_limit_hit",
        "cash_sweep_performed",
        "policy_envelope_expired",
        "autonomy_level_changed",
        "incident_raised",
    }
    assert required == {member.value for member in EventType}


def test_is_frozen() -> None:
    event = make_event()
    with pytest.raises(ValidationError):
        event.actor = "someone-else"  # type: ignore[misc]
