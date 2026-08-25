#!/usr/bin/env python3
"""Collect the Interfax (e-disclosure.ru) E-1 message archive — RUN THIS ON YOUR OWN MACHINE.

Why it lives here but does not run here: e-disclosure.ru answers this
project's sandbox with a JavaScript anti-bot challenge instead of data. That
challenge is written for a person with a real browser, and a real browser
satisfies it normally — so the collection has to happen on a machine with an
ordinary browser. Nothing in this script defeats or works around the
challenge; Playwright drives a real Chromium that executes the page's own
JavaScript exactly as the site intends.

Interfax serves roughly 90% of listed issuers, which is precisely the
population the AZIPI-sourced inventory is missing (91% of its issuers are not
traded). This archive is the one blocker between the collected work and a
signable E-1 verdict.

Two modes, and the first one is not optional:

  --explore   Opens the search page, saves its HTML and a screenshot, and
              stops. Send those two files back; the selectors below are
              written from a page I have never been able to load, so they
              are a starting guess, and the exploration output is what turns
              them into correct ones.

  --collect   Runs the search year by year and saves every results page plus
              a JSONL index of the messages found.

Be a polite guest. The defaults pause between page loads and run one request
at a time on purpose. Please do not lower them: this is public disclosure
infrastructure serving other people, and the whole job is a few thousand page
loads spread over an evening, not a race.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

SEARCH_URL = "https://www.e-disclosure.ru/poisk-po-soobshheniyam"

# Bank of Russia message-type numbering (the same codes appear at every
# accredited agency — it is regulatory numbering, not an Interfax internal id).
# Confirmed present in the live search form; see stage-E-1/coverage_report.md.
MESSAGE_TYPES = {
    181: "Поступление эмитенту добровольного предложения о приобретении его эмиссионных ценных бумаг",
    182: "Поступление эмитенту обязательного предложения о приобретении его эмиссионных ценных бумаг",
    184: "Поступление эмитенту уведомления о праве требовать выкупа эмиссионных ценных бумаг эмитента",
    185: "Поступление эмитенту требования о выкупе эмиссионных ценных бумаг эмитента",
}
YEARS = range(2019, 2026)

PAGE_PAUSE_SECONDS = 3.0
YEAR_PAUSE_SECONDS = 10.0
MAX_PAGES_PER_YEAR = 400


def stamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def explore(out_dir: Path) -> int:
    from playwright.sync_api import sync_playwright

    out_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        page = browser.new_page()
        print(f"opening {SEARCH_URL} — let the page finish loading", file=sys.stderr)
        page.goto(SEARCH_URL, wait_until="networkidle", timeout=120_000)
        page.wait_for_timeout(5_000)
        (out_dir / "search_page.html").write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(out_dir / "search_page.png"), full_page=True)
        browser.close()
    print(f"saved {out_dir / 'search_page.html'} and {out_dir / 'search_page.png'}")
    print("send both back — the selectors get written from them")
    return 0


def collect(out_dir: Path, years: list[int]) -> int:
    from playwright.sync_api import sync_playwright

    raw_dir = out_dir / "pages"
    raw_dir.mkdir(parents=True, exist_ok=True)
    index_path = out_dir / "messages.jsonl"
    seen: set[str] = set()
    if index_path.is_file():
        for line in index_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                seen.add(json.loads(line)["event_id"])
        print(f"resuming: {len(seen)} messages already indexed", file=sys.stderr)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        page = browser.new_page()
        page.goto(SEARCH_URL, wait_until="networkidle", timeout=120_000)
        page.wait_for_timeout(5_000)

        for year in years:
            print(f"=== {year}", file=sys.stderr)
            try:
                select_message_types(page)
                set_date_range(page, f"01.01.{year}", f"31.12.{year}")
                submit_search(page)
            except Exception as error:  # noqa: BLE001 - report, do not guess
                shot = out_dir / f"failed_{year}.png"
                page.screenshot(path=str(shot), full_page=True)
                (out_dir / f"failed_{year}.html").write_text(page.content(), encoding="utf-8")
                print(
                    f"could not drive the form for {year}: {error}\n"
                    f"saved {shot} and the page HTML next to it — send them back "
                    f"and the selectors get corrected",
                    file=sys.stderr,
                )
                browser.close()
                return 1

            for page_number in range(1, MAX_PAGES_PER_YEAR + 1):
                html = page.content()
                (raw_dir / f"{year}_p{page_number:03d}.html").write_text(html, encoding="utf-8")
                new = 0
                with index_path.open("a", encoding="utf-8") as handle:
                    for event_id, title in parse_results(html):
                        if event_id in seen:
                            continue
                        seen.add(event_id)
                        new += 1
                        handle.write(
                            json.dumps(
                                {
                                    "event_id": event_id,
                                    "title": title,
                                    "year_searched": year,
                                    "url": f"https://www.e-disclosure.ru/portal/event.aspx?EventId={event_id}",
                                    "retrieved_at": stamp(),
                                },
                                ensure_ascii=False,
                            )
                            + "\n"
                        )
                print(f"  page {page_number}: {new} new", file=sys.stderr)
                time.sleep(PAGE_PAUSE_SECONDS)
                if not go_to_next_page(page):
                    break
            time.sleep(YEAR_PAUSE_SECONDS)
        browser.close()

    print(f"indexed {len(seen)} messages -> {index_path}")
    print(f"raw pages -> {raw_dir}")
    return 0


# --- form driving -----------------------------------------------------------
# Written blind against a page this environment cannot load. Each helper is
# separate so that when --explore comes back, only the failing one changes.


def select_message_types(page) -> None:
    for code, label in MESSAGE_TYPES.items():
        box = page.get_by_label(label, exact=False)
        if box.count() == 0:
            box = page.locator(f'input[type=checkbox][value="{code}"]')
        box.first.check(timeout=15_000)


def set_date_range(page, start: str, finish: str) -> None:
    page.locator('input[name*="dateStart" i], input#dateStart').first.fill(start)
    page.locator('input[name*="dateFinish" i], input#dateFinish').first.fill(finish)


def submit_search(page) -> None:
    page.get_by_role("button", name=re.compile("Найти|Искать|Поиск", re.IGNORECASE)).first.click()
    page.wait_for_load_state("networkidle", timeout=120_000)
    page.wait_for_timeout(3_000)


def go_to_next_page(page) -> bool:
    nxt = page.get_by_role("link", name=re.compile(r"^\s*(Следующая|Далее|»|>)\s*$", re.IGNORECASE))
    if nxt.count() == 0 or not nxt.first.is_enabled():
        return False
    nxt.first.click()
    page.wait_for_load_state("networkidle", timeout=120_000)
    page.wait_for_timeout(2_000)
    return True


def parse_results(html: str) -> list[tuple[str, str]]:
    """EventId plus link text for every message row on a results page."""
    out: list[tuple[str, str]] = []
    for match in re.finditer(
        r'href="[^"]*event\.aspx\?EventId=(\d+)[^"]*"[^>]*>(.*?)</a>', html, re.DOTALL
    ):
        title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", match.group(2))).strip()
        out.append((match.group(1), title))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--explore", action="store_true", help="run this first")
    parser.add_argument("--collect", action="store_true")
    parser.add_argument("--out-dir", type=Path, default=Path("stage-E-1/documents/interfax"))
    parser.add_argument("--years", type=int, nargs="*", default=list(YEARS))
    args = parser.parse_args()

    if args.explore:
        return explore(args.out_dir)
    if args.collect:
        return collect(args.out_dir, args.years)
    parser.error("pass --explore (first) or --collect")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
