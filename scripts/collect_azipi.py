#!/usr/bin/env python3
"""Collect the Stage E-1 event index from AZIPI (TZ 31, step 2, Phase A).

AZIPI (`e-disclosure.azipi.ru`) is one of the five disclosure agencies
accredited by the Bank of Russia (see `stage-E-1/coverage_report.md`). Unlike
e-disclosure.ru it serves message lists and message texts without an anti-bot
challenge, so it is the one source this environment can actually collect from.

Scope note, important when reading coverage numbers: AZIPI carries the
issuers that disclose *through AZIPI*. Interfax states it serves ~90% of
listed issuers, so what this script finds is a real but partial slice of the
market, not the full 2019-2025 population. `coverage_report.md` records that
explicitly rather than presenting these counts as complete.

Phase A discipline (see `stage-E-1/README.md`): this collects the message
*index* only — type, issuer, INN, event date, publication date, message URL.
It never fetches outcomes, and `InventoryEvent` has no outcome field to put
them in. Document texts are fetched separately by `fetch_azipi_documents.py`.

Politeness: one request at a time, a delay between requests, exponential
backoff on failure. We are guests on disclosure infrastructure.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

BASE = "https://e-disclosure.azipi.ru"
SEARCH_URL = f"{BASE}/search/index.php"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

# AZIPI's "Существенные факты, касающиеся событий эмитента" group.
FACTS_GROUP = "1078975"

# AZIPI message-type codes -> our E1EventType (scripts/validate_e1_inventory.py).
# Codes read from AZIPI's own type selector, not guessed.
TYPE_CODES: dict[str, tuple[str, str]] = {
    "1079963": ("voluntary_or_mandatory_offer", "Поступление добровольного предложения"),
    "1079964": ("voluntary_or_mandatory_offer", "Поступление обязательного предложения"),
    "1079967": ("squeeze_out_request_95", "Поступление уведомления о праве требовать выкупа"),
    "1079969": ("squeeze_out_request_95", "Поступление требования о выкупе"),
    # Candidates for buyback_art_75_76; kept separate because the mapping is
    # not established from the message texts yet (see coverage_report.md).
    "4005185": ("buyback_art_75_76", "Принятие решения о приобретении размещенных акций"),
    "1080045": ("buyback_art_75_76", "Приобретение эмитентом собственных голосующих акций"),
}

REQUEST_DELAY_SECONDS = 2.0
MAX_ATTEMPTS = 4


@dataclass(frozen=True)
class IndexRow:
    """One row of AZIPI's search results — index metadata, never an outcome."""

    azipi_message_id: str
    message_url: str
    azipi_type_code: str
    event_type: str
    message_title: str
    issuer: str
    inn: str
    event_date: str
    published_at: str


def fetch(url: str, *, delay: float = REQUEST_DELAY_SECONDS) -> str:
    """GET with a polite delay and exponential backoff (2s, 4s, 8s, 16s)."""
    last_error: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=60) as response:
                body = response.read().decode("utf-8", errors="replace")
            time.sleep(delay)
            return body
        except Exception as error:  # noqa: BLE001 - retried, then reported
            last_error = error
            backoff = 2 ** (attempt + 1)
            print(f"    request failed ({error}); retrying in {backoff}s", file=sys.stderr)
            time.sleep(backoff)
    raise RuntimeError(f"giving up on {url}: {last_error}")


def search_url(type_code: str, date_from: str, date_to: str, page: int) -> str:
    params = {
        "msgs": "Y",
        "MESS_FACTS_GROUP": FACTS_GROUP,
        "MESS_FACTS_TYPE": type_code,
        "MESS_FACTS_DATE_FROM": date_from,
        "MESS_FACTS_DATE_TO": date_to,
        "search_messages": "Найти сообщения",
    }
    if page > 1:
        # AZIPI's results pager is PAGEN_2 (PAGEN_1 belongs to another list on
        # the page and is silently ignored — using it caps you at page 1).
        params["PAGEN_2"] = str(page)
    return f"{SEARCH_URL}?{urllib.parse.urlencode(params)}"


_ROW_RE = re.compile(
    r'<a[^>]+href="(?P<href>/messages/(?P<mid>\d+)/[^"]*)"[^>]*>(?P<title>[^<]+)</a>'
    r"(?P<tail>.{0,600}?)"
    r"ИНН:\s*(?P<inn>\d+),\s*(?P<issuer>[^<|]+?)\s*</",
    re.DOTALL,
)
_DATE_RE = re.compile(r"(\d{2}\.\d{2}\.\d{4})(?:\s+(\d{2}:\d{2}:\d{2}))?")


def parse_results(html: str, type_code: str) -> list[IndexRow]:
    event_type, _label = TYPE_CODES[type_code]
    rows: list[IndexRow] = []
    for match in _ROW_RE.finditer(html):
        after = html[match.end() : match.end() + 400]
        dates = _DATE_RE.findall(after)
        event_date = dates[0][0] if dates else ""
        published_at = ""
        if len(dates) > 1:
            published_at = f"{dates[1][0]} {dates[1][1]}".strip()
        rows.append(
            IndexRow(
                azipi_message_id=match.group("mid"),
                message_url=BASE + match.group("href"),
                azipi_type_code=type_code,
                event_type=event_type,
                message_title=re.sub(r"\s+", " ", match.group("title")).strip(),
                issuer=re.sub(r"\s+", " ", match.group("issuer")).strip(),
                inn=match.group("inn"),
                event_date=event_date,
                published_at=published_at,
            )
        )
    return rows


def has_next_page(html: str, page: int) -> bool:
    return f"PAGEN_2={page + 1}" in html


def collect(type_codes: list[str], year_from: int, year_to: int) -> list[IndexRow]:
    collected: dict[str, IndexRow] = {}
    for type_code in type_codes:
        _event_type, label = TYPE_CODES[type_code]
        for year in range(year_from, year_to + 1):
            page = 1
            while True:
                url = search_url(type_code, f"01.01.{year}", f"31.12.{year}", page)
                html = fetch(url)
                rows = parse_results(html, type_code)
                new = 0
                for row in rows:
                    if row.azipi_message_id not in collected:
                        collected[row.azipi_message_id] = row
                        new += 1
                print(f"  {label[:42]:44} {year} p{page}: {len(rows):3} rows (+{new})")
                if not rows or not has_next_page(html, page) or page >= 60:
                    break
                page += 1
    return list(collected.values())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-year", type=int, default=2019)
    parser.add_argument("--to-year", type=int, default=2025)
    parser.add_argument("--types", nargs="*", default=sorted(TYPE_CODES))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    rows = collect(args.types, args.from_year, args.to_year)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        for row in sorted(rows, key=lambda r: (r.event_type, r.event_date, r.issuer)):
            handle.write(json.dumps(asdict(row), ensure_ascii=False) + "\n")
    print(f"\nwrote {len(rows)} index rows to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
