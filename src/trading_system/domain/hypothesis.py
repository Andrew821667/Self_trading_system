from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict


class ResearchProtocol(StrEnum):
    """TZ 7: R3-A is parametric/statistical, R3-B is event-study. Fixed before results are seen (TZ E3 acceptance)."""

    R3_A = "R3-A"
    R3_B = "R3-B"


class Hypothesis(BaseModel):
    """TZ 5.2. Any research run requires a hypothesis_id (TZ 7.1); research_protocol is locked at creation."""

    model_config = ConfigDict(frozen=True)

    hypothesis_id: str
    campaign_id: str
    edge_thesis_id: str
    research_protocol: ResearchProtocol
    strategy_spec_id: str
    execution_spec_id: str
    protective_policy_id: str
    universe: list[str]
    timeframe: str
    parameter_space: dict[str, Any]
    planned_trials: int
    economic_gate: dict[str, Any]
    created_by: str
    created_at: datetime
