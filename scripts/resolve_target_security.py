#!/usr/bin/env python3
"""Resolve which security an E-1 offer actually concerns (Stage E-1, Phase A).

Why this exists: the issuer that *files* a disclosure message is not always
the company whose shares are being bought. Two real cases from the collected
set — PAO "Kvadra" filed an offer for shares of PAO "TGK-14" at 0.00289 ₽,
and PAO "EL5-Energo" filed one for shares of AO "HOLDING ERSO" at 613 ₽.
Matching a filer's INN to a MOEX security therefore picks the wrong
instrument, and every price/return computed from it would be nonsense.

The offer's own price clause names the target company, so the target is read
from the document text and matched against MOEX by normalised name. Every
match is then sanity-checked against the market price around the
announcement: an offer price implying a ratio far outside 1 is evidence the
match or the extraction is wrong, and the row is rejected rather than
quietly used.

Blind-protocol note: the market data requested here is the close *on or
before* the announcement date only. Nothing after the event is read, so this
reveals no outcome (see stage-E-1/README.md).
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import socket
import sys
import time
import urllib.request
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

socket.setdefaulttimeout(60)

ISS_HISTORY = (
    "https://iss.moex.com/iss/history/engines/stock/markets/shares/securities/{secid}.json"
    "?iss.meta=off&from={start}&till={end}&limit=100"
)
REQUEST_DELAY_SECONDS = 0.3
MAX_ATTEMPTS = 3

# A procedure price this far from the market price means the security match or
# the extraction is wrong. Offers do trade at a premium or discount, but not
# by an order of magnitude.
MIN_PLAUSIBLE_RATIO = 0.2
MAX_PLAUSIBLE_RATIO = 5.0

PRICE_HINT = "цена приобрет"
# "0,00289 рублей" — kopeck-fraction prices are real in this family, so the
# decimal tail must not be capped at two digits.
# Prices come in two shapes and both must be read whole:
#   "0,00289 (ноль целых ...) рублей"            -> decimal tail
#   "160 (сто шестьдесят) руб. 70 коп."          -> kopecks AFTER the word
# Reading only the rouble part turns 160.70 into 160, which silently biases
# every spread computed from it. The kopeck form is tried first: making that
# group optional inside one pattern lets the lazy match skip it every time.
_ROUBLES = r"(\d[\d\s  ]*(?:[.,]\d{1,6})?)\s*(?:\([^)]*\))?\s*(?:руб|рубл|₽)"
_PRICE_WITH_KOPECKS_RE = re.compile(
    _ROUBLES + r"[^\d]{0,15}(\d{1,2})\s*(?:\([^)]*\))?\s*коп", re.IGNORECASE
)
_PRICE_RE = re.compile(_ROUBLES, re.IGNORECASE)
# The target is named right after the price: "за одну обыкновенную акцию X".
_TARGET_RE = re.compile(
    r"(?:за\s+(?:1|одну)\s*\(?[^)]*\)?\s*(?:обыкновенн|привилегированн)[^\s]*\s+"
    r"(?:именн[^\s]*\s+)?(?:бездокументарн[^\s]*\s+)?акци[юий]\s*)"
    r"((?:ПАО|АО|ОАО|ЗАО|Публичное акционерное общество|Акционерное общество)"
    r"[^.,;\n]{2,70})",
    re.IGNORECASE,
)
_QUOTED_RE = re.compile(r"[\"«]([^\"»]{2,60})[\"»]")


def normalise(name: str) -> str:
    """Comparable form: quoted core if present, letters and digits only."""
    quoted = _QUOTED_RE.search(name)
    core = quoted.group(1) if quoted else name
    return re.sub(r"[^0-9а-яёa-z]", "", core.lower())


def fetch_json(url: str) -> dict | None:
    for attempt in range(MAX_ATTEMPTS):
        try:
            with urllib.request.urlopen(url) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as error:  # noqa: BLE001 - retried, then skipped
            if attempt == MAX_ATTEMPTS - 1:
                print(f"    ISS failed: {error}", file=sys.stderr)
            time.sleep(2 ** (attempt + 1))
    return None


def close_before(secid: str, day: date) -> float | None:
    payload = fetch_json(
        ISS_HISTORY.format(
            secid=secid, start=(day - timedelta(days=30)).isoformat(), end=day.isoformat()
        )
    )
    time.sleep(REQUEST_DELAY_SECONDS)
    if not payload:
        return None
    block = payload.get("history", {})
    bars = [dict(zip(block["columns"], row, strict=True)) for row in block.get("data", [])]
    closes = [bar["CLOSE"] for bar in bars if bar.get("CLOSE")]
    return float(closes[-1]) if closes else None


def price_clause(text: str) -> str | None:
    for line in text.splitlines():
        if PRICE_HINT in line.lower() and re.search(r"\d", line):
            return re.sub(r"\s+", " ", line).strip()
    return None


def parse_price(roubles: str, kopecks: str | None) -> Decimal | None:
    cleaned = re.sub(r"[\s  ]", "", roubles).replace(",", ".")
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    if kopecks:
        value += Decimal(kopecks) / 100
    return value if value > 0 else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--documents", type=Path, required=True)
    parser.add_argument("--moex", type=Path, required=True, help="cached MOEX securities json")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    securities = json.loads(args.moex.read_text(encoding="utf-8"))
    by_name: dict[str, list[dict]] = {}
    for security in securities:
        for field in ("emitent_title", "name", "shortname"):
            key = normalise(str(security.get(field) or ""))
            if key:
                by_name.setdefault(key, []).append(security)

    events = [
        json.loads(line)
        for line in args.inventory.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    results: list[dict] = []
    for event in events:
        doc_id = event["source_document_refs"][0]
        text_path = args.documents / event["event_id"] / f"{doc_id}.txt"
        if not text_path.is_file():
            continue
        clause = price_clause(text_path.read_text(encoding="utf-8"))
        if not clause:
            continue

        with_kopecks = _PRICE_WITH_KOPECKS_RE.search(clause)
        price_match = with_kopecks or _PRICE_RE.search(clause)
        if not price_match:
            continue
        price = parse_price(
            price_match.group(1), price_match.group(2) if with_kopecks else None
        )
        if price is None:
            continue

        # When the clause names a company after the price, the offer concerns
        # *that* company's shares — a holding disclosing about a subsidiary.
        # When it names none, the target is the filer's own shares, which is
        # the ordinary case. Defaulting to the filer instead of skipping is
        # what makes most of the collected offers usable at all.
        target_match = _TARGET_RE.search(clause)
        target_name = (
            re.sub(r"\s+", " ", target_match.group(1)).strip()
            if target_match
            else event["issuer"]
        )
        target_from_document = target_match is not None
        candidates = by_name.get(normalise(target_name), [])
        if not candidates:
            results.append(
                {
                    "event_id": event["event_id"],
                    "announcement_date": event["announcement_date"],
                    "filer": event["issuer"],
                    "target_named_in_document": target_name,
                    "target_source": "document" if target_from_document else "filer",
                    "secid": "",
                    "procedure_price": str(price),
                    "market_close_before": "",
                    "price_to_market": "",
                    "status": "target_not_listed_on_moex",
                }
            )
            continue

        for security in candidates:
            market = close_before(security["secid"], date.fromisoformat(event["announcement_date"]))
            ratio = float(price) / market if market else None
            if ratio is None:
                status = "no_pre_event_market_data"
            elif MIN_PLAUSIBLE_RATIO <= ratio <= MAX_PLAUSIBLE_RATIO:
                status = "ok"
            else:
                status = "implausible_ratio"
            results.append(
                {
                    "event_id": event["event_id"],
                    "announcement_date": event["announcement_date"],
                    "filer": event["issuer"],
                    "target_named_in_document": target_name,
                    "target_source": "document" if target_from_document else "filer",
                    "secid": security["secid"],
                    "procedure_price": str(price),
                    "market_close_before": market if market else "",
                    "price_to_market": round(ratio, 3) if ratio else "",
                    "status": status,
                }
            )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(results[0]))
        writer.writeheader()
        writer.writerows(sorted(results, key=lambda r: r["announcement_date"]))

    usable = [r for r in results if r["status"] == "ok"]
    print(f"documents with a readable price clause and a named target: {len(results)}")
    print(f"  target resolved to a MOEX security and price plausible: {len(usable)}")
    print(f"  target not listed on MOEX: {sum(1 for r in results if r['status'] == 'target_not_listed_on_moex')}")
    print(f"  implausible price/market ratio: {sum(1 for r in results if r['status'] == 'implausible_ratio')}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
