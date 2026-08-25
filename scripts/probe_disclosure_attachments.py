#!/usr/bin/env python3
"""Find which E-1 events have their offer attachments reachable on disclosure.ru.

The AZIPI disclosure message announces that an offer arrived; it does not
carry the offer's terms. Those live in the attached files — the offer itself,
the bank guarantee, the appraiser's report — and without them checklist
criteria П-2 (guarantee), П-3 (price basis) and П-5 (acquirer history) cannot
be assessed, which under rule D fails every event closed.

AK&M's archive at ``disclosure.ru/issuer/<INN>/`` serves those attachments as
RAR archives with no anti-bot. It only covers AK&M's own clients, so the
question this script answers is a factual one: **for how many of the collected
events is the attachment actually there?** It probes, it does not download —
the answer decides whether a download pass is worth running at all.

Output is one row per issuer INN, plus one row per matching document found, so
the coverage claim can be recomputed from the file rather than trusted.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

socket.setdefaulttimeout(60)

ISSUER_URL = "https://www.disclosure.ru/issuer/{inn}/"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
# We are guests on disclosure infrastructure: one request at a time, spaced.
REQUEST_DELAY_SECONDS = 1.5
MAX_ATTEMPTS = 4

# Titles of the documents that carry E-1 procedure terms. Deliberately broad —
# a false positive costs one download, a false negative loses an event.
PROCEDURE_TITLE_RE = re.compile(
    r"(обязательн\w*\s+предложени|добровольн\w*\s+предложени"
    r"|требовани\w*\s+о\s+выкупе|уведомлени\w*\s+о\s+нали\w*\s+прав"
    r"|прав\w*\s+требовать\s+выкупа|отчет\w*\s+об\s+оценке)",
    re.IGNORECASE,
)
_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL)
_LINK_RE = re.compile(r"GetFileMD5\?md5=([a-f0-9]+)")
_DATE_RE = re.compile(r"(\d{2}\.\d{2}\.\d{4})")


def fetch(url: str) -> str | None:
    for attempt in range(MAX_ATTEMPTS):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request) as response:
                return response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            if attempt == MAX_ATTEMPTS - 1:
                print(f"    HTTP {error.code} on {url}", file=sys.stderr)
        except Exception as error:  # noqa: BLE001 - retried, then reported
            if attempt == MAX_ATTEMPTS - 1:
                print(f"    failed {url}: {error}", file=sys.stderr)
        time.sleep(2 ** (attempt + 1))
    return None


def documents_on_page(page: str) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    for match in _ROW_RE.finditer(page):
        row = match.group(1)
        link = _LINK_RE.search(row)
        if not link:
            continue
        text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", row))).strip()
        title = re.sub(r"^\d+\.\s*", "", text)
        title = re.sub(r"\s*СКАЧАТЬ.*$", "", title).strip()
        dates = _DATE_RE.findall(text)
        found.append(
            {"md5": link.group(1), "title": title, "published_at": dates[-1] if dates else ""}
        )
    return found


def issuers_from_inventory(inventory: Path, index: Path) -> dict[str, str]:
    by_message = {
        str(row["azipi_message_id"]): row
        for row in (
            json.loads(line)
            for line in index.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    }
    issuers: dict[str, str] = {}
    for line in inventory.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        message_id = event["source_document_refs"][0].removeprefix("azipi-")
        indexed = by_message.get(message_id)
        inn = str((indexed or {}).get("inn") or "").strip()
        if inn:
            issuers.setdefault(inn, event["issuer"])
    return issuers


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--out-issuers", type=Path, required=True)
    parser.add_argument("--out-documents", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0, help="probe only the first N issuers")
    args = parser.parse_args()

    issuers = issuers_from_inventory(args.inventory, args.index)
    inns = sorted(issuers)
    if args.limit:
        inns = inns[: args.limit]

    issuer_rows: list[dict] = []
    document_rows: list[dict] = []
    for position, inn in enumerate(inns, start=1):
        page = fetch(ISSUER_URL.format(inn=inn))
        time.sleep(REQUEST_DELAY_SECONDS)
        if page is None:
            issuer_rows.append(
                {
                    "inn": inn,
                    "issuer": issuers[inn],
                    "status": "not_a_client",
                    "documents": 0,
                    "procedure_documents": 0,
                }
            )
            continue
        documents = documents_on_page(page)
        matching = [d for d in documents if PROCEDURE_TITLE_RE.search(d["title"])]
        issuer_rows.append(
            {
                "inn": inn,
                "issuer": issuers[inn],
                "status": "has_documents" if documents else "empty_page",
                "documents": len(documents),
                "procedure_documents": len(matching),
            }
        )
        for document in matching:
            document_rows.append({"inn": inn, "issuer": issuers[inn], **document})
        print(
            f"[{position}/{len(inns)}] {inn} {len(documents):4d} docs, "
            f"{len(matching):2d} procedure",
            file=sys.stderr,
        )

    for path, rows in ((args.out_issuers, issuer_rows), (args.out_documents, document_rows)):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=list(rows[0])
                if rows
                else ["inn", "issuer", "md5", "title", "published_at"],
            )
            writer.writeheader()
            writer.writerows(rows)

    with_documents = [r for r in issuer_rows if r["procedure_documents"]]
    print(f"issuers probed:                 {len(issuer_rows)}")
    print(
        f"  not AK&M clients (404):       {sum(1 for r in issuer_rows if r['status'] == 'not_a_client')}"
    )
    print(
        f"  page present but empty:       {sum(1 for r in issuer_rows if r['status'] == 'empty_page')}"
    )
    print(f"  with E-1 procedure documents: {len(with_documents)}")
    print(f"procedure documents found:      {len(document_rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
