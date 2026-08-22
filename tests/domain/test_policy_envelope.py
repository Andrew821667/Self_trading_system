from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from trading_system.domain import AutonomyLevel, PolicyEnvelope


def make_policy(**overrides: object) -> PolicyEnvelope:
    fields = dict(
        policy_version="1",
        autonomy_level=AutonomyLevel.A0,
        allowed_markets=["MOEX"],
        allowed_asset_classes=["equity"],
        approved_strategy_scope=["E-1"],
        owner_capital_ceiling=Decimal(1000000),
        account_id="acc-1",
        max_leverage=Decimal(1),
        portfolio_risk_limits={},
        factor_limits={},
        capital_scaling_ladder={},
        cash_management={},
        restricted_list_version="1",
        owner_absence_timeout_days=7,
        valid_from=datetime(2026, 1, 1, tzinfo=UTC),
        expires_at=datetime(2026, 6, 1, tzinfo=UTC),
        emergency_contacts=["owner@example.com"],
        signature="sig",
    )
    fields.update(overrides)
    return PolicyEnvelope(**fields)


def test_valid_window_constructs() -> None:
    policy = make_policy()
    assert policy.is_expired(datetime(2026, 1, 2, tzinfo=UTC)) is False
    assert policy.is_expired(datetime(2026, 6, 1, tzinfo=UTC)) is True


def test_rejects_expires_at_before_valid_from() -> None:
    with pytest.raises(ValidationError):
        make_policy(
            valid_from=datetime(2026, 6, 1, tzinfo=UTC),
            expires_at=datetime(2026, 1, 1, tzinfo=UTC),
        )


def test_rejects_equal_valid_from_and_expires_at() -> None:
    same = datetime(2026, 1, 1, tzinfo=UTC)
    with pytest.raises(ValidationError):
        make_policy(valid_from=same, expires_at=same)


def test_is_frozen() -> None:
    policy = make_policy()
    with pytest.raises(ValidationError):
        policy.owner_capital_ceiling = Decimal(999999999)  # type: ignore[misc]
