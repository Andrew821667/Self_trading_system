from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class ExecutionSpecification(BaseModel):
    """TZ 5.6. Immutable live specification (TZ 2.4); shared verbatim between backtest and paper/live (TZ E2)."""

    model_config = ConfigDict(frozen=True)

    execution_spec_id: str
    version: str
    entry_order_type: str
    limit_price_formula: str
    order_ttl: str
    min_order_lifetime: str
    entry_window: str
    partial_fill_policy: str
    repricing_policy: str
    max_reprice_attempts: int
    chase_price_allowed: bool
    planned_exit_policy: str
    emergency_exit_policy: str
    slippage_model: dict[str, Any]
    hash: str
