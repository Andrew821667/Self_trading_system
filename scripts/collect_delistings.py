#!/usr/bin/env python3
"""Collect MOEX share delistings as Art. 75-76 buyback triggers (Stage E-1, Phase A).

Why this exists: family `buyback_art_75_76` came out empty from the disclosure
agencies, because their taxonomy has no direct message type for it — the
buyback right arises from a shareholder-meeting decision (reorganisation,
major transaction, delisting) disclosed in a catch-all category. Delisting is
the one trigger that leaves a precise, dated, machine-readable trace: the
security stops being listed on MOEX.

Two properties make this a better base than the agency route:
  * it covers 2019-2025 in full, including the years before AZIPI's archive
    starts (2021-07-30);
  * every row is by construction a *tradable* security, which is the subset
    that matters after 91% of the agency-sourced inventory turned out to be
    unlisted issuers (see coverage_report.md).

What this is NOT: a delisting date is a trigger, not the E-1 event itself.
The buyback offer with its price and terms is a separate disclosure. These
rows say precisely which issuer and which date to go looking for, so the
document hunt is targeted instead of a blind sweep of the archive.

Source: ISS `history/.../listing` (per-board listing windows) joined with the
securities reference for issuer INN, name and instrument type.
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import socket
import sys
import time
import urllib.request
from pathlib import Path

# ISS occasionally drops a chunked response mid-read; a socket timeout plus
# retries turns that into a delay instead of a failed run.
socket.setdefaulttimeout(60)

ISS_LISTING = (
    "https://iss.moex.com/iss/history/engines/stock/markets/shares/listing.json"
    "?iss.meta=off&limit=100&start={start}"
)
ISS_SECURITIES = (
    "https://iss.moex.com/iss/securities.json"
    "?engine=stock&market=shares&iss.meta=off&limit=100&start={start}"
)
PAGE_DELAY_SECONDS = 0.3
MAX_PAGES = 400

# Only equity can carry an Art. 75-76 buyback right; fund units, depositary
# receipts and mortgage certificates cannot.
SHARE_TYPES = frozenset({"common_share", "preferred_share"})


MAX_ATTEMPTS = 4


def fetch_json(url: str) -> dict:
    last_error: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as error:  # noqa: BLE001 - retried, then reported
            last_error = error
            backoff = 2 ** (attempt + 1)
            print(f"    ISS request failed ({error}); retry in {backoff}s", file=sys.stderr)
            time.sleep(backoff)
    raise RuntimeError(f"giving up on {url}: {last_error}")


def fetch_paged(url_template: str, block: str) -> list[dict]:
    rows: list[dict] = []
    for page in range(MAX_PAGES):
        payload = fetch_json(url_template.format(start=page * 100))
        data = payload[block]
        if not data["data"]:
            break
        rows.extend(dict(zip(data["columns"], row, strict=True)) for row in data["data"])
        time.sleep(PAGE_DELAY_SECONDS)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-date", default="2019-01-01")
    parser.add_argument("--to-date", default="2025-12-31")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    listing = fetch_paged(ISS_LISTING, "securities")
    securities = fetch_paged(ISS_SECURITIES, "securities")
    meta = {row["secid"]: row for row in securities}

    # A security can be listed on several boards; it has left the exchange
    # only after its last board window closes.
    last_seen: dict[str, str] = collections.defaultdict(str)
    for row in listing:
        till = row.get("history_till") or ""
        last_seen[row["SECID"]] = max(last_seen[row["SECID"]], till)

    rows: list[dict] = []
    for secid, till in last_seen.items():
        if not (args.from_date <= till <= args.to_date):
            continue
        info = meta.get(secid, {})
        # Still trading somewhere: the window closing was a board move.
        if info.get("is_traded") == 1:
            continue
        if info.get("type") not in SHARE_TYPES:
            continue
        rows.append(
            {
                "delisted_on": till,
                "secid": secid,
                "isin": info.get("isin") or "",
                "instrument_type": info.get("type") or "",
                "inn": str(info.get("emitent_inn") or ""),
                "issuer": info.get("emitent_title") or info.get("name") or "",
            }
        )

    rows.sort(key=lambda r: (r["delisted_on"], r["secid"]))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    per_year = collections.Counter(row["delisted_on"][:4] for row in rows)
    print(f"share delistings {args.from_date}..{args.to_date}: {len(rows)}")
    for year in sorted(per_year):
        print(f"  {year}: {per_year[year]}")
    print(f"distinct issuers: {len({r['inn'] for r in rows if r['inn']})}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
