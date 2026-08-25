#!/usr/bin/env python3
"""Economic falsification test for edge thesis E-1 (edge_thesis_R0_v1.md, §5).

The frozen thesis states two falsification conditions, either of which closes
it. This script tests the **economic** one:

    "медианная годовая доходность на связанный капитал после издержек и
     налога не превышает безрисковую ставку за сопоставимый период удержания"

It is deliberately run in the thesis's **best case**: the procedure is assumed
to complete, to pay the full announced price, and to pay on schedule. No
completion probability is applied, no failed procedures are modelled. If the
best case already fails to clear the risk-free rate, the thesis fails on this
condition regardless of how good the checklist is at picking winners — which
is exactly what makes the test decisive on a small sample.

Entry is the market close on the first trading day *after* the announcement:
you cannot buy before the news is out. Only events where the procedure price
is above that entry are tradable at all; the rest are reported as
"no spread to capture", which is itself part of the result.

Risk-free comparison uses the Bank of Russia key rate on the announcement
date (cached from cbr.ru).
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import socket
import statistics
import sys
import time
import urllib.request
from datetime import date, timedelta
from pathlib import Path

socket.setdefaulttimeout(60)

ISS_HISTORY = (
    "https://iss.moex.com/iss/history/engines/stock/markets/shares/securities/{secid}.json"
    "?iss.meta=off&from={start}&till={end}&limit=100"
)
REQUEST_DELAY_SECONDS = 0.3
MAX_ATTEMPTS = 3

# Offer acceptance windows in the collected documents run 70-80 days, plus
# settlement. Held as an explicit assumption rather than hidden in a formula;
# --holding-days makes the sensitivity visible.
DEFAULT_HOLDING_DAYS = 90
# Round-trip retail brokerage cost. Only the buy leg is charged in practice
# (the sell is a tender, not an exchange trade), but both are charged here so
# the estimate errs against the thesis rather than for it.
BROKER_COMMISSION = 0.0005 * 2
TAX_RATE = 0.13


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


def close_after(secid: str, day: date) -> tuple[date, float] | None:
    """First close strictly after `day` — the earliest price you could pay."""
    payload = fetch_json(
        ISS_HISTORY.format(
            secid=secid,
            start=(day + timedelta(days=1)).isoformat(),
            end=(day + timedelta(days=20)).isoformat(),
        )
    )
    time.sleep(REQUEST_DELAY_SECONDS)
    if not payload:
        return None
    block = payload.get("history", {})
    for row in (dict(zip(block["columns"], r, strict=True)) for r in block.get("data", [])):
        if row.get("CLOSE"):
            return date.fromisoformat(row["TRADEDATE"]), float(row["CLOSE"])
    return None


def load_key_rates(path: Path) -> dict[date, float]:
    rates: dict[date, float] = {}
    for day, value in re.findall(
        r"<td[^>]*>\s*(\d{2}\.\d{2}\.\d{4})\s*</td>\s*<td[^>]*>\s*([\d,.]+)\s*</td>",
        path.read_text(encoding="utf-8", errors="replace"),
    ):
        d, m, y = day.split(".")
        rates[date(int(y), int(m), int(d))] = float(value.replace(",", "."))
    return rates


def key_rate_on(rates: dict[date, float], day: date) -> float | None:
    for back in range(30):
        hit = rates.get(day - timedelta(days=back))
        if hit is not None:
            return hit
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--targets", type=Path, required=True)
    parser.add_argument("--key-rates", type=Path, required=True)
    parser.add_argument("--holding-days", type=int, default=DEFAULT_HOLDING_DAYS)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    rates = load_key_rates(args.key_rates)
    candidates = [
        row
        for row in csv.DictReader(args.targets.open(encoding="utf-8"))
        if row["status"] == "ok"
    ]

    seen: set[tuple[str, str]] = set()
    results: list[dict] = []
    for row in candidates:
        key = (row["announcement_date"], row["secid"])
        if key in seen:
            continue
        seen.add(key)

        announced = date.fromisoformat(row["announcement_date"])
        entry = close_after(row["secid"], announced)
        if entry is None:
            continue
        entry_date, entry_price = entry
        procedure_price = float(row["procedure_price"])

        gross = procedure_price / entry_price - 1
        record = {
            "announcement_date": row["announcement_date"],
            "secid": row["secid"],
            "target": row["target_named_in_document"],
            "entry_date": entry_date.isoformat(),
            "entry_price": round(entry_price, 4),
            "procedure_price": procedure_price,
            "gross_spread_pct": round(gross * 100, 2),
        }

        if gross <= 0:
            record.update(
                {
                    "net_annualised_pct": "",
                    "key_rate_pct": key_rate_on(rates, announced) or "",
                    "beats_risk_free": "",
                    "note": "no spread to capture — procedure price at or below market",
                }
            )
            results.append(record)
            continue

        after_costs = gross - BROKER_COMMISSION
        net = after_costs * (1 - TAX_RATE)
        annualised = net * 365 / args.holding_days
        rate = key_rate_on(rates, announced)
        record.update(
            {
                "net_annualised_pct": round(annualised * 100, 1),
                "key_rate_pct": rate if rate is not None else "",
                "beats_risk_free": (
                    "yes" if rate is not None and annualised * 100 > rate else "no"
                ),
                "note": "",
            }
        )
        results.append(record)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(results[0]))
        writer.writeheader()
        writer.writerows(sorted(results, key=lambda r: r["announcement_date"]))

    tradable = [r for r in results if r["net_annualised_pct"] != ""]
    beating = [r for r in tradable if r["beats_risk_free"] == "yes"]
    print(f"events assessed:                     {len(results)}")
    print(f"  no spread to capture:              {len(results) - len(tradable)}")
    print(f"  tradable (procedure above market): {len(tradable)}")
    if tradable:
        median = statistics.median(float(r["net_annualised_pct"]) for r in tradable)
        print(f"  median net annualised return:      {median:.1f}%  (holding {args.holding_days}d)")
        print(f"  beating the key rate:              {len(beating)} of {len(tradable)}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
