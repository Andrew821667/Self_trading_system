import pytest
from pydantic import ValidationError

from trading_system.domain import EdgeThesis, EdgeThesisStatus, StructuralReason


def make_edge_thesis(**overrides: object) -> EdgeThesis:
    fields = dict(
        edge_thesis_id="et-1",
        version="1",
        family="E-1",
        mechanism="forced buyback pricing anomaly",
        structural_reason=StructuralReason.C1,
        counterparty_class="retail sellers",
        counterparty_motivation="forced liquidity event",
        capacity_estimate="low",
        falsification_condition="mean excess return <= 0 net of costs over N events",
        expected_lifetime="regulatory-cycle dependent",
        death_conditions="rule change removing forced pricing mechanism",
        status=EdgeThesisStatus.DRAFT,
    )
    fields.update(overrides)
    return EdgeThesis(**fields)


def test_round_trip_and_defaults() -> None:
    thesis = make_edge_thesis()
    assert thesis.status is EdgeThesisStatus.DRAFT
    assert thesis.approved_at is None


def test_is_frozen_once_constructed() -> None:
    thesis = make_edge_thesis()
    with pytest.raises(ValidationError):
        thesis.status = EdgeThesisStatus.CONFIRMED  # type: ignore[misc]


def test_rejects_unknown_structural_reason() -> None:
    with pytest.raises(ValidationError):
        make_edge_thesis(structural_reason="C5")
