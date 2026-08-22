from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator


class RiskDecision(BaseModel):
    """TZ 5.9. Output of Risk Engine.evaluate (TZ 9.1); approved intents never exceed max_allowed_quantity (TZ 22.2)."""

    model_config = ConfigDict(frozen=True)

    decision_id: str
    intent_id: str
    approved: bool
    max_allowed_quantity: Decimal
    rejection_rule_id: str | None = None
    rule_set_version: str
    policy_envelope_version: str
    inputs_snapshot: dict[str, Any]
    created_at: datetime

    @model_validator(mode="after")
    def _rejection_requires_zero_quantity(self) -> RiskDecision:
        if not self.approved and self.max_allowed_quantity != 0:
            raise ValueError("a rejected RiskDecision must carry max_allowed_quantity == 0")
        if not self.approved and self.rejection_rule_id is None:
            raise ValueError("a rejected RiskDecision must carry rejection_rule_id")
        return self
