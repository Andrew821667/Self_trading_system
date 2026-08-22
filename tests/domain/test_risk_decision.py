from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from trading_system.domain import RiskDecision


def make_decision(**overrides: object) -> RiskDecision:
    fields = dict(
        decision_id="rd-1",
        intent_id="ti-1",
        approved=True,
        max_allowed_quantity=Decimal(10),
        rule_set_version="1",
        policy_envelope_version="1",
        inputs_snapshot={},
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    fields.update(overrides)
    return RiskDecision(**fields)


def test_approved_decision_round_trips() -> None:
    decision = make_decision()
    assert decision.approved is True
    assert decision.max_allowed_quantity == Decimal(10)


def test_rejected_decision_requires_zero_quantity() -> None:
    with pytest.raises(ValidationError):
        make_decision(approved=False, max_allowed_quantity=Decimal(1), rejection_rule_id="R1")


def test_rejected_decision_requires_rule_id() -> None:
    with pytest.raises(ValidationError):
        make_decision(approved=False, max_allowed_quantity=Decimal(0), rejection_rule_id=None)


def test_rejected_decision_with_zero_quantity_and_rule_id_is_valid() -> None:
    decision = make_decision(approved=False, max_allowed_quantity=Decimal(0), rejection_rule_id="R1")
    assert decision.approved is False
