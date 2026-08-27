#!/usr/bin/env python3
"""Liquidity/tradability check for the Stage E-1 inventory (TZ, Stage E-1 acceptance).

TZ's Stage E-1 acceptance requires "оценена реализуемость по ликвидности при
капитале владельца" — an event whose shares cannot be bought on an exchange
is untradeable for this thesis no matter how sound the legal mechanism is.

Matching is by issuer INN against MOEX's own securities reference (ISS API
exposes `emitent_inn`), so it is an exact join rather than name similarity.

The INN comes from each document's own title line, not from
azipi_index.jsonl: found 2026-08-27 that AZIPI's search-results page
mispairs the ИНН/issuer caption with the wrong link for ~70% of rows (a
template bug on their side, reproducible — see
scripts/validate_azipi_documents.py), so the index's `inn` field cannot be
trusted for this join. The document a link points to is authoritative about
itself.

Reads the inventory and its downloaded documents, writes a CSV of the
matched events and prints the headline split.
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import re
import time
import urllib.request
from pathlib import Path

ISS_SECURITIES = (
    "https://iss.moex.com/iss/securities.json"
    "?engine=stock&market=shares&iss.meta=off&limit=100&start={start}"
)
PAGE_DELAY_SECONDS = 0.4
MAX_PAGES = 60

# Same pattern as scripts/build_e1_inventory.py's _TITLE_RE / document_identity —
# the document's own declared identity, not the index row.
_TITLE_RE = re.compile(r"^(?P<issuer>.+?)\s*\(ИНН:\s*(?P<inn>\d+)\)\s*/")
STUB_MARKER = "Список сообщений"


def document_inn(text: str) -> str | None:
    first_line = text.splitlines()[0].strip() if text.strip() else ""
    if not first_line or STUB_MARKER in first_line:
        return None
    match = _TITLE_RE.match(first_line)
    return match.group("inn") if match else None


def fetch_moex_shares() -> list[dict]:
    """Every share in MOEX's reference book, traded or not."""
    rows: list[dict] = []
    for page in range(MAX_PAGES):
        url = ISS_SECURITIES.format(start=page * 100)
        with urllib.request.urlopen(url, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
        block = payload["securities"]
        if not block["data"]:
            break
        rows.extend(dict(zip(block["columns"], row, strict=True)) for row in block["data"])
        time.sleep(PAGE_DELAY_SECONDS)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--documents", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    shares = fetch_moex_shares()
    by_inn: dict[str, list[dict]] = collections.defaultdict(list)
    for share in shares:
        inn = str(share.get("emitent_inn") or "").strip()
        if inn:
            by_inn[inn].append(share)

    events = [
        json.loads(line)
        for line in args.inventory.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    matched: list[dict] = []
    listed = unlisted = no_inn = 0
    for event in events:
        doc_id = event["source_document_refs"][0]
        text_path = args.documents / event["event_id"] / f"{doc_id}.txt"
        text = text_path.read_text(encoding="utf-8") if text_path.is_file() else ""
        inn = document_inn(text)
        if inn is None:
            no_inn += 1
            continue
        securities = by_inn.get(inn, [])
        if not securities:
            unlisted += 1
            continue
        listed += 1
        for security in securities:
            matched.append(
                {
                    "event_id": event["event_id"],
                    "announcement_date": event["announcement_date"],
                    "event_type": event["event_type"],
                    "issuer": event["issuer"],
                    "inn": inn,
                    "secid": security["secid"],
                    "isin": security.get("isin") or "",
                    "is_traded_now": security.get("is_traded"),
                }
            )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(matched[0]) if matched else ["event_id"])
        writer.writeheader()
        writer.writerows(sorted(matched, key=lambda r: (r["announcement_date"], r["secid"])))

    total = len(events)
    distinct_events = len({row["event_id"] for row in matched})
    print(f"MOEX shares reference: {len(shares)} securities, {len(by_inn)} issuer INNs")
    print(f"inventory events:      {total}")
    print(f"  no readable ИНН in own document: {no_inn}  ({no_inn * 100 // total}%)")
    print(f"  issuer listed on MOEX:      {listed}  ({listed * 100 // total}%)")
    print(f"  issuer absent from MOEX:    {unlisted}  ({unlisted * 100 // total}%)")
    print(f"  distinct tradable events:   {distinct_events}")
    print(f"wrote {len(matched)} event-security pairs to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
