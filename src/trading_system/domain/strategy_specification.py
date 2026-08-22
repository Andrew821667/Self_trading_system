from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class StrategySpecification(BaseModel):
    """TZ 5.5. Immutable live specification (TZ 2.4): a change is a new version, not a mutation."""

    model_config = ConfigDict(frozen=True)

    strategy_id: str
    version: str
    edge_thesis_id: str
    event_family: str
    entry_rules: dict[str, Any]
    exit_rules: dict[str, Any]
    disqualifiers: list[str]
    required_public_sources: list[str]
    factor_profile: dict[str, Any]
    capacity_policy: dict[str, Any]
    execution_spec_id: str
    protective_policy_id: str
    spec_hash: str
