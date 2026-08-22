#!/usr/bin/env python3
"""Schema and blind-protocol guard for the Stage E-1 event inventory (TZ 31, step 2).

The owner's step-2 protocol runs in two phases, enforced by git tags on this
repository (see ``stage-E-1/README.md`` for the full description):

* **Phase A** (``stage-E-1/inventory/events.jsonl`` + ``stage-E-1/documents/``):
  facts about each candidate event available *as of that event's own
  announcement_date*. No outcome field exists anywhere in this module by
  construction (every model uses ``extra="forbid"``, so one smuggled in
  through hand-edited JSON is rejected, not silently accepted) — frozen at
  git tag ``e1-inventory-frozen``.
* **Classification** (``stage-E-1/classification/``): the frozen checklist
  (``docs/artifacts/event_checklist_E1_v1.md``) applied to each event using
  only documents published on or before that event's announcement_date —
  frozen at git tag ``e1-classified-frozen``. The verdict is derived from
  checklist section D, not hand-asserted: ``ClassificationRecord`` rejects a
  verdict that doesn't match the rule.
* **Phase B** (outcomes, quotes, controls) only starts after
  ``e1-classified-frozen`` exists and lives outside this module's scope.

Run standalone to check whatever has been collected so far:

.. code-block:: sh

    uv run python scripts/validate_e1_inventory.py

This never fails just because the inventory is still empty or partial —
partial, honestly-reported coverage is the expected state of Phase A in
progress (see the owner's coverage-reporting requirement). It fails only on
an actual schema violation or a leakage risk (a classification citing a
document published after the event it classifies).
"""

from __future__ import annotations

import sys
from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

REPO_ROOT = Path(__file__).resolve().parent.parent
STAGE_DIR = REPO_ROOT / "stage-E-1"
INVENTORY_FILE = STAGE_DIR / "inventory" / "events.jsonl"
DOCUMENTS_DIR = STAGE_DIR / "documents"
CLASSIFICATION_DIR = STAGE_DIR / "classification"

# event_checklist_E1_v1.md sections B and C.
CHECKLIST_CRITERIA = tuple(f"П-{i}" for i in range(1, 10))
CHECKLIST_DISQUALIFIERS = tuple(f"Д-{i}" for i in range(1, 11))
MIN_CRITERIA_FOR_ELIGIBLE = 7


class E1EventType(StrEnum):
    """The four families named in TZ 31 step 2, grouped as the owner grouped them."""

    VOLUNTARY_OR_MANDATORY_OFFER = "voluntary_or_mandatory_offer"
    SQUEEZE_OUT_REQUEST_95 = "squeeze_out_request_95"
    FORCED_BUYBACK = "forced_buyback"
    BUYBACK_ART_75_76 = "buyback_art_75_76"


class InventoryEvent(BaseModel):
    """One row of stage-E-1/inventory/events.jsonl. Phase A: facts only, no outcomes.

    announcement_date is "дата события" for the classification cutoff rule:
    classification may only cite documents published on or before it.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    event_type: E1EventType
    issuer: str
    isin: str
    announcement_date: date
    submission_date: date | None = None
    window_start: date | None = None
    window_end: date | None = None
    procedure_price: Decimal | None = None
    price_basis: str
    guarantor_bank: str | None = None
    acquirer: str
    source_document_refs: list[str]

    @model_validator(mode="after")
    def _has_at_least_one_source(self) -> InventoryEvent:
        if not self.source_document_refs:
            raise ValueError("source_document_refs must not be empty: no public source, no event (TZ 6.1)")
        return self


class DocumentRecord(BaseModel):
    """stage-E-1/documents/<event_id>/<doc_id>.meta.json sidecar next to the raw fetched file."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    doc_id: str
    event_id: str
    url: str
    source_type: str
    published_at: date
    retrieved_at: datetime
    sha256: str
    legal_use_status: Literal["allowed", "attribution_required", "metadata_only", "prohibited"]
    local_filename: str


class CriterionFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    satisfied: bool
    grounds: str
    source_doc_refs: list[str] = []


class DisqualifierFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    triggered: bool
    grounds: str
    source_doc_refs: list[str] = []


class ClassificationRecord(BaseModel):
    """stage-E-1/classification/<event_id>.json. Produced only after `e1-inventory-frozen`.

    verdict is validated against event_checklist_E1_v1.md section D rather
    than trusted as entered: eligible iff A-0 holds, no disqualifier fired,
    and at least 7 of the 9 criteria are satisfied. Anything else —
    including incomplete data — is disqualified (fail-closed, per the
    checklist's own "недостроение фактов предположением запрещено").
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    checklist_version: str
    a0_satisfied: bool
    a0_grounds: str
    criteria: dict[str, CriterionFinding]
    disqualifiers: dict[str, DisqualifierFinding]
    verdict: Literal["eligible", "disqualified"]
    verdict_grounds: str
    classified_at: datetime

    @model_validator(mode="after")
    def _covers_full_checklist(self) -> ClassificationRecord:
        if set(self.criteria) != set(CHECKLIST_CRITERIA):
            raise ValueError(f"criteria must cover exactly {CHECKLIST_CRITERIA}")
        if set(self.disqualifiers) != set(CHECKLIST_DISQUALIFIERS):
            raise ValueError(f"disqualifiers must cover exactly {CHECKLIST_DISQUALIFIERS}")
        return self

    @model_validator(mode="after")
    def _verdict_matches_checklist_rule_d(self) -> ClassificationRecord:
        any_disqualifier_triggered = any(f.triggered for f in self.disqualifiers.values())
        criteria_met = sum(1 for f in self.criteria.values() if f.satisfied)
        eligible = (
            self.a0_satisfied
            and not any_disqualifier_triggered
            and criteria_met >= MIN_CRITERIA_FOR_ELIGIBLE
        )
        expected = "eligible" if eligible else "disqualified"
        if self.verdict != expected:
            raise ValueError(
                f"verdict={self.verdict!r} contradicts checklist rule D for {self.event_id} "
                f"(a0={self.a0_satisfied}, disqualifier_triggered={any_disqualifier_triggered}, "
                f"criteria_met={criteria_met}/9) -> rule D requires {expected!r}"
            )
        return self


def load_events(path: Path = INVENTORY_FILE) -> dict[str, InventoryEvent]:
    if not path.is_file():
        return {}
    events: dict[str, InventoryEvent] = {}
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        event = InventoryEvent.model_validate_json(line)
        if event.event_id in events:
            raise ValueError(f"duplicate event_id {event.event_id!r} at line {line_no}")
        events[event.event_id] = event
    return events


def load_documents(directory: Path = DOCUMENTS_DIR) -> dict[str, DocumentRecord]:
    if not directory.is_dir():
        return {}
    documents: dict[str, DocumentRecord] = {}
    for meta_path in sorted(directory.glob("*/*.meta.json")):
        record = DocumentRecord.model_validate_json(meta_path.read_text(encoding="utf-8"))
        documents[record.doc_id] = record
    return documents


def load_classifications(directory: Path = CLASSIFICATION_DIR) -> dict[str, ClassificationRecord]:
    if not directory.is_dir():
        return {}
    classifications: dict[str, ClassificationRecord] = {}
    for path in sorted(directory.glob("*.json")):
        record = ClassificationRecord.model_validate_json(path.read_text(encoding="utf-8"))
        classifications[record.event_id] = record
    return classifications


def check_leakage(
    events: dict[str, InventoryEvent],
    documents: dict[str, DocumentRecord],
    classifications: dict[str, ClassificationRecord],
) -> list[str]:
    """Return human-readable problems; empty means no leakage risk detected."""
    problems: list[str] = []
    for event_id, record in classifications.items():
        event = events.get(event_id)
        if event is None:
            problems.append(f"{event_id}: classification exists but no inventory event found")
            continue
        cited_doc_ids: set[str] = set()
        for finding in (*record.criteria.values(), *record.disqualifiers.values()):
            cited_doc_ids.update(finding.source_doc_refs)
        for doc_id in cited_doc_ids:
            doc = documents.get(doc_id)
            if doc is None:
                problems.append(f"{event_id}: classification cites unknown document {doc_id!r}")
                continue
            if doc.published_at > event.announcement_date:
                problems.append(
                    f"{event_id}: cites {doc_id!r} published {doc.published_at}, after "
                    f"announcement_date {event.announcement_date} — outcome leakage risk"
                )
    return problems


def coverage_report(events: dict[str, InventoryEvent]) -> str:
    counts: Counter[tuple[str, int]] = Counter(
        (event.event_type.value, event.announcement_date.year) for event in events.values()
    )
    lines = ["event_type,year,count"]
    for (event_type, year), count in sorted(counts.items()):
        lines.append(f"{event_type},{year},{count}")
    return "\n".join(lines)


def main() -> int:
    events = load_events()
    documents = load_documents()
    classifications = load_classifications()

    problems = check_leakage(events, documents, classifications)
    if problems:
        print("Stage E-1 leakage guard FAILED:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1

    print(
        f"{len(events)} inventory events, {len(documents)} documents, "
        f"{len(classifications)} classifications — no leakage detected."
    )
    print()
    print(coverage_report(events))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
