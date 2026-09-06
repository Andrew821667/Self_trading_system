#!/usr/bin/env python3
"""Measure pre-event liquidity for tradable Stage E-1 events (checklist Д-7).

Checklist disqualifier Д-7 rejects an event when entering or exiting the
position would take more than a few daily volumes at the owner's capital.
This measures the median daily rouble turnover over the trading days
*strictly before* each event's announcement_date and reports how many days
of turnover a target position would consume.

Blind-protocol note: only pre-announcement market data is requested. Nothing
here looks at prices or volumes on or after the event date, so it reveals
nothing about how a procedure ended (see stage-E-1/README.md). This is an
input available to a decision-maker at announcement time, not an outcome.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import time
import urllib.request
from datetime import date, timedelta
from pathlib import Path

ISS_HISTORY = (
    "https://iss.moex.com/iss/history/engines/stock/markets/shares/securities/{secid}.json"
    "?iss.meta=off&from={start}&till={end}&limit=100"
)
LOOKBACK_DAYS = 90
REQUEST_DELAY_SECONDS = 0.4
# "Несколько дневных объёмов" from Д-7, read as a hard ceiling of 3.
MAX_ACCEPTABLE_DAYS = 3.0


def fetch_history(secid: str, start: date, end: date) -> list[dict]:
    url = ISS_HISTORY.format(secid=secid, start=start.isoformat(), end=end.isoformat())
    with urllib.request.urlopen(url, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))
    block = payload.get("history", {})
    columns = block.get("columns", [])
    return [dict(zip(columns, row, strict=True)) for row in block.get("data", [])]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tradability", type=Path, required=True)
    parser.add_argument("--capital", type=float, default=1_000_000.0)
    parser.add_argument(
        "--position-share",
        type=float,
        default=0.2,
        help="fraction of capital in one position; 0.2 = five positions",
    )
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    position_size = args.capital * args.position_share
    rows = list(csv.DictReader(args.tradability.open(encoding="utf-8")))

    results: list[dict] = []
    for row in rows:
        announced = date.fromisoformat(row["announcement_date"])
        # Strictly before the announcement: the day itself is excluded.
        end = announced - timedelta(days=1)
        start = end - timedelta(days=LOOKBACK_DAYS)
        try:
            history = fetch_history(row["secid"], start, end)
        except Exception as error:  # noqa: BLE001 - reported per row, not fatal
            print(f"  {row['secid']}: history unavailable ({error})")
            history = []
        time.sleep(REQUEST_DELAY_SECONDS)

        turnovers = [
            float(bar["VALUE"])
            for bar in history
            if bar.get("VALUE") not in (None, "") and float(bar["VALUE"]) > 0
        ]
        median_turnover = statistics.median(turnovers) if turnovers else 0.0
        days_to_fill = position_size / median_turnover if median_turnover else float("inf")
        results.append(
            {
                **row,
                "trading_days_sampled": len(turnovers),
                "median_daily_turnover_rub": round(median_turnover),
                "days_of_volume_for_position": (
                    round(days_to_fill, 2) if days_to_fill != float("inf") else ""
                ),
                "passes_d7": "yes" if days_to_fill <= MAX_ACCEPTABLE_DAYS else "no",
            }
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(results[0]))
        writer.writeheader()
        writer.writerows(results)

    passing = {r["event_id"] for r in results if r["passes_d7"] == "yes"}
    no_data = [r for r in results if r["trading_days_sampled"] == 0]
    print(f"\nposition size: {position_size:,.0f} ₽ ({args.position_share:.0%} of {args.capital:,.0f} ₽)")
    print(f"event-security pairs checked: {len(results)}")
    print(f"  no pre-event trading data at all: {len(no_data)}")
    print(f"  distinct events passing Д-7 (<= {MAX_ACCEPTABLE_DAYS} daily volumes): {len(passing)}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
