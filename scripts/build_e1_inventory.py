#!/usr/bin/env python3
"""Build stage-E-1/inventory/events.jsonl from the AZIPI index + fetched documents.

Fills what the message text states plainly and marks everything else
`pending_fields` rather than guessing. The checklist is explicit that
"недостроение фактов предположением запрещено", so a field this script cannot
read with a deterministic pattern is left unset and named as pending — an
event carrying pending fields is not eligible for classification
(`InventoryEvent.is_ready_for_classification`).

Extraction is anchored on the regulator's own numbered clause template
(1.1 acquirer, 1.7 price, 1.9 guarantor bank, ...), which issuers follow
closely. That is far less error-prone than hunting for keywords loose in the
prose, where "цена" also shows up in boilerplate about how a price was
determined and inside issuer names.

Deliberately rule-based, not LLM-based: Phase A only needs to identify and
index events. The real structured extraction (schema validation, model and
prompt version pinning, golden regression set) is Stage E1 work under
TZ 6.3-6.5 and must not be quietly pre-empted by ad-hoc parsing here.
"""

from __future__ import annotations

import argparse
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

# Fields that can only come from the document body; anything not extracted
# below is reported as pending under one of these names.
DOCUMENT_DERIVED_FIELDS = ("isin", "procedure_price", "price_basis", "guarantor_bank", "acquirer")

_ISIN_RE = re.compile(r"\b(RU[A-Z0-9]{10})\b")
_CLAUSE_RE = re.compile(r"^\s*(\d+\.\d+)\.?\s*(.+)$")

ACQUIRER_HINT = "направившего добровольное"
PRICE_HINT = "цена приобретаемых ценных бумаг"
GUARANTOR_HINT = "гаранта, предоставившего банковскую гарантию"

# "3 387 (Три тысячи триста восемьдесят семь) рублей 77 коп." — the digits are
# separated from "руб" by the amount spelled out in words, and the kopeck part
# trails after it, so both are captured rather than assumed away.
_PRICE_VALUE_RE = re.compile(
    r"(\d[\d\s  ]*(?:[.,]\d{1,2})?)(?:\s*\([^)]*\))?\s*(?:руб|рубл|₽)[^\d]{0,25}(?:(\d{1,2})\s*коп)?",
    re.IGNORECASE,
)
_ORG_RE = re.compile(
    r"((?:Публичное акционерное общество|Акционерное общество|"
    r"Общество с ограниченной ответственностью|ПАО|АО|ООО)"
    r"\s*[\"«][^\"»]{2,80}[\"»])"
)
# The person on the other side of an offer is often an individual, not a
# company — "Кустов Илья Михайлович". Treated as an equally valid acquirer
# rather than dropped as an extraction miss.
_PERSON_RE = re.compile(r"^([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+){1,2})\s*[.,]?\s*$")
# Phrases issuers use in clause 1.7 to say how the price was arrived at.
PRICE_BASIS_PATTERNS: tuple[tuple[str, str], ...] = (
    ("средневзвешенн", "биржевая средневзвешенная цена"),
    ("оценщик", "рыночная стоимость по отчёту оценщика"),
    ("организатор", "цена по данным организатора торговли"),
    ("наибольш", "наибольшая из предусмотренных законом величин"),
)


def parse_price(digits: str, kopecks: str | None) -> Decimal | None:
    # Russian texts write the decimal separator as a comma ("22,18 рубля");
    # Decimal only accepts a period and rejects the whole value otherwise.
    cleaned = re.sub(r"[\s  ]", "", digits).replace(",", ".")
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    if kopecks:
        value += Decimal(kopecks) / 100
    # A per-share procedure price beyond this is not credible for the
    # third-tier issuers this family lives in, and would signal the pattern
    # latched onto a share count or a total consideration instead.
    return value if 0 < value < Decimal(10_000_000) else None


def clause_body(text: str, hint: str) -> str | None:
    """Answer part of the first numbered clause whose text contains `hint`."""
    for line in text.splitlines():
        match = _CLAUSE_RE.match(line)
        if not match:
            continue
        body = match.group(2)
        if hint.lower() not in body.lower():
            continue
        _label, _sep, answer = body.partition(":")
        answer = re.sub(r"\s+", " ", answer).strip()
        if answer and answer.rstrip(".").lower() not in ("отсутствует", "-", "—", "нет"):
            return answer
    return None


def first_org(value: str | None) -> str | None:
    """Organisation name, or an individual's name when the party is a person."""
    if not value:
        return None
    match = _ORG_RE.search(value)
    if match:
        return match.group(1).strip()
    person = _PERSON_RE.match(value.strip())
    return person.group(1).strip() if person else None


def price_basis_of(clause_text: str | None) -> str | None:
    if not clause_text:
        return None
    lowered = clause_text.lower()
    for needle, label in PRICE_BASIS_PATTERNS:
        if needle in lowered:
            return label
    return None


def to_iso(russian_date: str) -> str | None:
    match = re.match(r"(\d{2})\.(\d{2})\.(\d{4})", russian_date or "")
    if not match:
        return None
    day, month, year = match.groups()
    return f"{year}-{month}-{day}"


def build_row(index_row: dict, documents_dir: Path) -> dict | None:
    event_id = f"e1-azipi-{index_row['azipi_message_id']}"
    doc_id = f"azipi-{index_row['azipi_message_id']}"
    text_path = documents_dir / event_id / f"{doc_id}.txt"
    announcement = to_iso(index_row["event_date"]) or to_iso(index_row["published_at"])
    if announcement is None:
        return None

    text = text_path.read_text(encoding="utf-8") if text_path.is_file() else ""
    price_clause = clause_body(text, PRICE_HINT)

    procedure_price: str | None = None
    if price_clause:
        match = _PRICE_VALUE_RE.search(price_clause)
        if match:
            price = parse_price(match.group(1), match.group(2))
            if price is not None:
                procedure_price = str(price)

    isin_match = _ISIN_RE.search(text)
    row: dict = {
        "event_id": event_id,
        "event_type": index_row["event_type"],
        "issuer": index_row["issuer"],
        "announcement_date": announcement,
        "isin": isin_match.group(1) if isin_match else None,
        "procedure_price": procedure_price,
        "price_basis": price_basis_of(price_clause),
        "guarantor_bank": first_org(clause_body(text, GUARANTOR_HINT)),
        "acquirer": first_org(clause_body(text, ACQUIRER_HINT)),
        "source_document_refs": [doc_id],
        "provenance": (
            f"AZIPI message {index_row['azipi_message_id']} "
            f"(type {index_row['azipi_type_code']}: {index_row['message_title']})"
        ),
    }
    row["pending_fields"] = sorted(
        field for field in DOCUMENT_DERIVED_FIELDS if row.get(field) in (None, "", [])
    )
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--documents", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    index_rows = [
        json.loads(line)
        for line in args.index.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    rows = [row for row in (build_row(r, args.documents) for r in index_rows) if row]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        for row in sorted(
            rows, key=lambda r: (r["event_type"], r["announcement_date"], r["issuer"])
        ):
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    ready = sum(1 for row in rows if not row["pending_fields"])
    filled = {field: sum(1 for r in rows if r.get(field)) for field in DOCUMENT_DERIVED_FIELDS}
    print(f"wrote {len(rows)} inventory rows to {args.out}")
    print(f"  fully extracted (no pending fields): {ready}")
    print(f"  still awaiting document facts:       {len(rows) - ready}")
    print("  per-field extraction:")
    for field, count in filled.items():
        print(f"    {field:16} {count:4}/{len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
