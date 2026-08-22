from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class StructuralReason(StrEnum):
    """Why a counterparty is structurally forced into the other side of the trade (TZ 5.1)."""

    C1 = "C1"
    C2 = "C2"
    C3 = "C3"
    C4 = "C4"


class EdgeThesisStatus(StrEnum):
    """Verdict states from TZ section 31, step 6.

    NEEDS_REVISION permits exactly one reformulation cycle within the same
    campaign (trial counter carries over); it is a continuation of E-1, not
    a new stage. REJECTED closes the family for good; a later family
    restarts E-1 from scratch.
    """

    DRAFT = "draft"
    CONFIRMED = "confirmed"
    NEEDS_REVISION = "needs_revision"
    REJECTED = "rejected"


class EdgeThesis(BaseModel):
    """TZ 5.1. Frozen once approved_at is set; only a CONFIRMED verdict opens E0 (TZ 31)."""

    model_config = ConfigDict(frozen=True)

    edge_thesis_id: str
    version: str
    family: str
    mechanism: str
    structural_reason: StructuralReason
    counterparty_class: str
    counterparty_motivation: str
    capacity_estimate: str
    falsification_condition: str
    expected_lifetime: str
    death_conditions: str
    approved_at: datetime | None = None
    status: EdgeThesisStatus = EdgeThesisStatus.DRAFT
