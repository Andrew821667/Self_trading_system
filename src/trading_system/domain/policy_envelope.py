from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator


class AutonomyLevel(StrEnum):
    """TZ 3, stages A0-A2. Owner-signed; an agent can never raise its own autonomy_level (TZ 2.5)."""

    A0 = "A0"
    A1 = "A1"
    A2 = "A2"


class PolicyEnvelope(BaseModel):
    """TZ 5.10. Owner-signed; only the owner can sign or amend it (TZ 0.3). Safety Plane precedence: no
    agent may widen any field here (capital ceiling, universe, leverage, restricted list, ...) (TZ 2.5).
    """

    model_config = ConfigDict(frozen=True)

    policy_version: str
    autonomy_level: AutonomyLevel
    allowed_markets: list[str]
    allowed_asset_classes: list[str]
    approved_strategy_scope: list[str]
    owner_capital_ceiling: Decimal
    account_id: str
    max_leverage: Decimal
    portfolio_risk_limits: dict[str, Any]
    factor_limits: dict[str, Any]
    capital_scaling_ladder: dict[str, Any]
    cash_management: dict[str, Any]
    restricted_list_version: str
    owner_absence_timeout_days: int
    valid_from: datetime
    expires_at: datetime
    emergency_contacts: list[str]
    signature: str

    @model_validator(mode="after")
    def _validity_window_is_ordered(self) -> PolicyEnvelope:
        if self.expires_at <= self.valid_from:
            raise ValueError("expires_at must be after valid_from")
        return self

    def is_expired(self, at: datetime) -> bool:
        """TZ 3 (A2 acceptance): an expired policy forces A1/no_new_entries, not a fail-open default."""
        return at >= self.expires_at
