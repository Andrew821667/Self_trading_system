from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict


class ValidationStatus(StrEnum):
    """TZ 6.3 / 6.4. AMBIGUOUS and INVALID both forbid trade usage; only VALID may reach Strategy Engine."""

    VALID = "VALID"
    INVALID = "INVALID"
    AMBIGUOUS = "AMBIGUOUS"


class StructuredEvent(BaseModel):
    """TZ 5.4. Output of extraction; append-only once created (superseding creates a new event, TZ 6.6)."""

    model_config = ConfigDict(frozen=True)

    event_id: str
    source_id: str
    event_family: str
    schema_version: str
    event_time: datetime
    effective_time: datetime | None = None
    issuer_id: str
    facts: dict[str, Any]
    extraction_model: str
    prompt_version: str
    validation_status: ValidationStatus
    # Recorded for QC sampling only (TZ 6.4): LLM self-reported confidence is
    # uncalibrated and must never gate a trading decision.
    confidence: float
    public_source_basis: list[str]

    @property
    def is_tradable(self) -> bool:
        return self.validation_status == ValidationStatus.VALID and bool(self.public_source_basis)
