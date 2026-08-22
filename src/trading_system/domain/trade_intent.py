from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


class TradeIntent(BaseModel):
    """TZ 5.8. Produced by the Strategy Engine; must carry public_source_basis for the Risk Engine gate (TZ 9.2)."""

    model_config = ConfigDict(frozen=True)

    intent_id: str
    strategy_id: str
    event_id: str
    instrument: str
    side: Side
    requested_quantity: Decimal
    signal_price: Decimal
    stop_or_protection_reference: Decimal | None = None
    factor_exposures: dict[str, Any]
    public_source_basis: list[str]
    created_at: datetime
