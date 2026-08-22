from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class ProtectivePolicy(BaseModel):
    """TZ 5.7. Immutable live specification (TZ 2.4). Until activated+broker-verified, a position is not PROTECTED (TZ 14.3)."""

    model_config = ConfigDict(frozen=True)

    protective_policy_id: str
    type: str
    parameters: dict[str, Any]
    broker_side_required: bool
    fallback_policy: str
    max_unprotected_seconds: int
    liquidity_window: str
    hash: str
