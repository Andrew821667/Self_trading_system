#!/usr/bin/env python3
"""Build stage-E-1/inventory/events.jsonl from the AZIPI index + fetched documents.

Fills what the message text states plainly and marks everything else
`pending_fields` rather than guessing. The checklist is explicit that
"недостроение фактов предположением запрещено", so a field this script cannot
read with a deterministic pattern is left unset and named as pending — an
event carrying pending fields is not eligible for classification
(`InventoryEvent.is_ready_for_classification`).

Deliberately regex-based, not LLM-based: Phase A only needs to identify and
index events. The real structured extraction (with schema validation, model
and prompt version pinning, and a golden regression set) is Stage E1 work
under TZ 6.3-6.5, and must not be quietly pre-empted by ad-hoc parsing here.
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
_PRICE_RE = re.compile(
    r"цен[аеуы][^.\n]{0,120}?(?:приобрет|выкуп|покуп)[^.\n]{0,120}?"
    r"(\d[\d\s ]{0,15}(?:[.,]\d{1,2})?)\s*(?:руб|рублей|₽)",
    re.IGNORECASE,
)
_GUARANTOR_RE = re.compile(
    r"банковск[а-я]{0,4}\s+гаранти[а-я]{0,3}[^.\n]{0,200}?"
    r"((?:ПАО|АО|ООО|Банк)[^.,;\n]{2,80})",
    re.IGNORECASE,
)
_ACQUIRER_RE = re.compile(
    r"(?:лицо, направивш|направлено|представлен)[^.\n]{0,80}?"
    r"((?:ПАО|АО|ООО|Публичное акционерное|Акционерное общество)[^.,;\n]{2,90})",
    re.IGNORECASE,
)


def parse_price(raw: str) -> Decimal | None:
    cleaned = raw.replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    # Guard against sweeping up quantities/percentages that happen to sit near
    # the word "цена"; a per-share procedure price above this is not credible
    # for the third-tier issuers this family lives in.
    return value if 0 < value < Decimal(10000000) else None


def first_group(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    if not match:
        return None
    value = re.sub(r"\s+", " ", match.group(1)).strip(" \"'«»")
    return value or None


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
    price_match = _PRICE_RE.search(text)

    row: dict = {
        "event_id": event_id,
        "event_type": index_row["event_type"],
        "issuer": index_row["issuer"],
        "announcement_date": announcement,
        "isin": first_group(_ISIN_RE, text),
        "procedure_price": None,
        "price_basis": None,
        "guarantor_bank": first_group(_GUARANTOR_RE, text),
        "acquirer": first_group(_ACQUIRER_RE, text),
        "source_document_refs": [doc_id],
        "provenance": f"AZIPI message {index_row['azipi_message_id']} "
        f"(type {index_row['azipi_type_code']}: {index_row['message_title']})",
    }
    if price_match:
        price = parse_price(price_match.group(1))
        if price is not None:
            row["procedure_price"] = str(price)

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
        for row in sorted(rows, key=lambda r: (r["event_type"], r["announcement_date"], r["issuer"])):
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    ready = sum(1 for row in rows if not row["pending_fields"])
    print(f"wrote {len(rows)} inventory rows to {args.out}")
    print(f"  ready for classification (no pending fields): {ready}")
    print(f"  still awaiting document facts:                {len(rows) - ready}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
