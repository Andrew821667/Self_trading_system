from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict


class EventType(StrEnum):
    """TZ 20. The minimal set of domain event types the journal must support."""

    SOURCE_POLLED = "source_polled"
    SOURCE_DOCUMENT_SEEN = "source_document_seen"
    SOURCE_DOCUMENT_AMENDED = "source_document_amended"
    DOCUMENT_STORED = "document_stored"
    DOCUMENT_PARSED = "document_parsed"
    STRUCTURED_EVENT_CREATED = "structured_event_created"
    STRUCTURED_EVENT_INVALID = "structured_event_invalid"
    STRUCTURED_EVENT_SUPERSEDED = "structured_event_superseded"
    SIGNAL_GENERATED = "signal_generated"
    INTENT_CREATED = "intent_created"
    INTENTS_NETTED = "intents_netted"
    COMPLIANCE_CHECKED = "compliance_checked"
    MANIPULATION_CHECKED = "manipulation_checked"
    RISK_EVALUATED = "risk_evaluated"
    APPROVAL_ISSUED = "approval_issued"
    ORDER_SUBMITTED = "order_submitted"
    ORDER_ACKED = "order_acked"
    ORDER_FILLED = "order_filled"
    ORDER_CANCELLED = "order_cancelled"
    PROTECTIVE_POLICY_ACTIVATED = "protective_policy_activated"
    PROTECTIVE_POLICY_FAILED = "protective_policy_failed"
    POSITION_OPENED = "position_opened"
    POSITION_UPDATED = "position_updated"
    POSITION_CLOSED = "position_closed"
    RECONCILIATION_PERFORMED = "reconciliation_performed"
    RECONCILIATION_MISMATCH = "reconciliation_mismatch"
    STRATEGY_STATE_CHANGED = "strategy_state_changed"
    FACTOR_LIMIT_HIT = "factor_limit_hit"
    CASH_SWEEP_PERFORMED = "cash_sweep_performed"
    POLICY_ENVELOPE_EXPIRED = "policy_envelope_expired"
    AUTONOMY_LEVEL_CHANGED = "autonomy_level_changed"
    INCIDENT_RAISED = "incident_raised"


class EventEnvelope(BaseModel):
    """TZ 20. Recorded events are never rewritten; a schema change is a new schema_version
    plus an upcaster applied at replay time, not an edit to this model in place.
    """

    model_config = ConfigDict(frozen=True)

    event_id: str
    event_type: EventType
    occurred_at: datetime
    recorded_at: datetime
    correlation_id: str
    causation_id: str | None = None
    actor: str
    payload: dict[str, Any]
    artifact_refs: list[str]
    schema_version: str
