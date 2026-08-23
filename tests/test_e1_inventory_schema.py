from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError
from scripts.validate_e1_inventory import (
    ClassificationRecord,
    CriterionFinding,
    DisqualifierFinding,
    DocumentRecord,
    E1EventType,
    InventoryEvent,
    check_leakage,
    coverage_report,
)


def make_event(**overrides: object) -> InventoryEvent:
    fields = dict(
        event_id="e1-0001",
        event_type=E1EventType.VOLUNTARY_OR_MANDATORY_OFFER,
        issuer="ПАО Пример",
        isin="RU000A0EXAMPLE",
        announcement_date=date(2023, 6, 1),
        price_basis="биржевая средневзвешенная за 6 мес.",
        acquirer="ООО Приобретатель",
        source_document_refs=["doc-1"],
    )
    fields.update(overrides)
    return InventoryEvent(**fields)


def make_document(**overrides: object) -> DocumentRecord:
    fields = dict(
        doc_id="doc-1",
        event_id="e1-0001",
        url="https://e-disclosure.ru/example",
        source_type="disclosure_center",
        published_at=date(2023, 6, 1),
        retrieved_at=datetime(2026, 8, 22, tzinfo=UTC),
        sha256="a" * 64,
        legal_use_status="allowed",
        local_filename="doc-1.pdf",
    )
    fields.update(overrides)
    return DocumentRecord(**fields)


def make_classification(**overrides: object) -> ClassificationRecord:
    satisfied_criteria = {f"П-{i}": CriterionFinding(satisfied=True, grounds="ok") for i in range(1, 8)}
    unsatisfied_criteria = {f"П-{i}": CriterionFinding(satisfied=False, grounds="n/a") for i in range(8, 10)}
    fields = dict(
        event_id="e1-0001",
        checklist_version="event_checklist_E1_v1",
        a0_satisfied=True,
        a0_grounds="предложение направлено, комплект документов раскрыт",
        criteria={**satisfied_criteria, **unsatisfied_criteria},
        disqualifiers={f"Д-{i}": DisqualifierFinding(triggered=False, grounds="n/a") for i in range(1, 11)},
        verdict="eligible",
        verdict_grounds="A-0 выполнено, дисквалификаторов нет, 7/9 признаков",
        classified_at=datetime(2026, 8, 22, tzinfo=UTC),
    )
    fields.update(overrides)
    return ClassificationRecord(**fields)


def test_inventory_event_round_trips() -> None:
    event = make_event()
    assert event.event_type is E1EventType.VOLUNTARY_OR_MANDATORY_OFFER


def test_inventory_event_rejects_outcome_like_field() -> None:
    with pytest.raises(ValidationError):
        InventoryEvent.model_validate(
            {
                "event_id": "e1-0002",
                "event_type": "voluntary_or_mandatory_offer",
                "issuer": "X",
                "isin": "RU000A0EXAMPLE",
                "announcement_date": "2023-06-01",
                "price_basis": "n/a",
                "acquirer": "Y",
                "source_document_refs": ["doc-1"],
                "final_outcome": "completed",
            }
        )


def test_inventory_event_requires_source_document() -> None:
    with pytest.raises(ValidationError):
        make_event(source_document_refs=[])


def test_classification_verdict_must_match_checklist_rule_d() -> None:
    with pytest.raises(ValidationError):
        make_classification(verdict="disqualified")


def test_classification_eligible_requires_seven_of_nine_criteria() -> None:
    only_six = {f"П-{i}": CriterionFinding(satisfied=True, grounds="ok") for i in range(1, 7)}
    only_six.update({f"П-{i}": CriterionFinding(satisfied=False, grounds="n/a") for i in range(7, 10)})
    with pytest.raises(ValidationError):
        make_classification(criteria=only_six, verdict="eligible")


def test_classification_any_disqualifier_forces_disqualified() -> None:
    disqualifiers = {f"Д-{i}": DisqualifierFinding(triggered=False, grounds="n/a") for i in range(1, 11)}
    disqualifiers["Д-10"] = DisqualifierFinding(triggered=True, grounds="сектор АПК")
    with pytest.raises(ValidationError):
        make_classification(disqualifiers=disqualifiers, verdict="eligible")
    record = make_classification(disqualifiers=disqualifiers, verdict="disqualified")
    assert record.verdict == "disqualified"


def test_classification_must_cover_full_checklist() -> None:
    incomplete = {f"П-{i}": CriterionFinding(satisfied=True, grounds="ok") for i in range(1, 9)}
    with pytest.raises(ValidationError):
        make_classification(criteria=incomplete)


def test_check_leakage_flags_document_published_after_event() -> None:
    event = make_event(announcement_date=date(2023, 6, 1))
    late_doc = make_document(published_at=date(2023, 6, 15))
    classification = make_classification(
        criteria={
            **{f"П-{i}": CriterionFinding(satisfied=True, grounds="ok", source_doc_refs=["doc-1"]) for i in range(1, 8)},
            **{f"П-{i}": CriterionFinding(satisfied=False, grounds="n/a") for i in range(8, 10)},
        }
    )
    problems = check_leakage(
        {event.event_id: event}, {late_doc.doc_id: late_doc}, {classification.event_id: classification}
    )
    assert len(problems) == 1
    assert "leakage" in problems[0]


def test_check_leakage_clean_when_documents_predate_event() -> None:
    event = make_event()
    doc = make_document()
    classification = make_classification()
    problems = check_leakage({event.event_id: event}, {doc.doc_id: doc}, {classification.event_id: classification})
    assert problems == []


def test_coverage_report_counts_by_type_and_year() -> None:
    events = {
        "e1-0001": make_event(event_id="e1-0001", announcement_date=date(2023, 6, 1)),
        "e1-0002": make_event(event_id="e1-0002", announcement_date=date(2023, 9, 1)),
        "e1-0003": make_event(
            event_id="e1-0003",
            event_type=E1EventType.FORCED_BUYBACK,
            announcement_date=date(2024, 1, 1),
        ),
    }
    report = coverage_report(events)
    assert "event_type,year,source,count,pending_documents" in report
    assert "voluntary_or_mandatory_offer,2023,unknown,2,0" in report
    assert "forced_buyback,2024,unknown,1,0" in report


def test_coverage_report_breaks_down_by_source_and_counts_pending() -> None:
    doc = make_document(doc_id="doc-1", source_type="disclosure_agency_azipi")
    events = {
        "e1-0001": make_event(event_id="e1-0001", source_document_refs=["doc-1"]),
        "e1-0002": make_event(
            event_id="e1-0002",
            source_document_refs=["doc-1"],
            isin=None,
            pending_fields=["isin"],
        ),
    }
    report = coverage_report(events, {doc.doc_id: doc})
    assert "voluntary_or_mandatory_offer,2023,disclosure_agency_azipi,2,1" in report


def test_pending_fields_must_name_real_fields() -> None:
    with pytest.raises(ValidationError):
        make_event(pending_fields=["not_a_field"])


def test_pending_field_cannot_be_already_filled() -> None:
    with pytest.raises(ValidationError):
        make_event(isin="RU000A0EXAMPLE", pending_fields=["isin"])


def test_event_with_pending_fields_is_not_ready_for_classification() -> None:
    event = make_event(isin=None, pending_fields=["isin"])
    assert event.is_ready_for_classification is False
    assert make_event().is_ready_for_classification is True


def test_check_leakage_flags_classification_of_event_with_pending_fields() -> None:
    event = make_event(isin=None, pending_fields=["isin"])
    doc = make_document()
    classification = make_classification()
    problems = check_leakage(
        {event.event_id: event}, {doc.doc_id: doc}, {classification.event_id: classification}
    )
    assert any("pending_fields" in p for p in problems)
