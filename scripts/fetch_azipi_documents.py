#!/usr/bin/env python3
"""Fetch raw AZIPI message documents for the Stage E-1 inventory (TZ 31, step 2).

Saves each message exactly as served, plus a `DocumentRecord` sidecar
(`scripts/validate_e1_inventory.py`) carrying url, published_at, retrieved_at,
sha256 and legal_use_status — the chain of custody TZ 5.3/6.1 requires before
a document may back a trading decision.

Phase A discipline: this fetches the message published *at the event*, nothing
later. It does not follow links to subsequent messages about the same issuer,
so nothing here reveals how a procedure ended (see `stage-E-1/README.md`).

Politeness: sequential, delayed, backed off — same as the index collector.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
REQUEST_DELAY_SECONDS = 2.0
MAX_ATTEMPTS = 4

# AZIPI is an accredited public-disclosure agency: the messages are published
# for public access. Recorded per TZ 6.1 so ingestion can enforce it later.
LEGAL_USE_STATUS = "attribution_required"


def fetch_bytes(url: str) -> bytes:
    last_error: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=60) as response:
                body = response.read()
            time.sleep(REQUEST_DELAY_SECONDS)
            return body
        except Exception as error:  # noqa: BLE001 - retried, then reported
            last_error = error
            backoff = 2 ** (attempt + 1)
            print(f"    failed ({error}); retry in {backoff}s", file=sys.stderr)
            time.sleep(backoff)
    raise RuntimeError(f"giving up on {url}: {last_error}")


def to_iso_date(russian_date: str) -> str:
    """'05.10.2023' -> '2023-10-05'; empty string when AZIPI left it blank."""
    match = re.match(r"(\d{2})\.(\d{2})\.(\d{4})", russian_date or "")
    if not match:
        return ""
    day, month, year = match.groups()
    return f"{year}-{month}-{day}"


def extract_text(html: str) -> str:
    """Readable message text, for eyeballing and for the extractor's input."""
    body = re.sub(r"<script[\s\S]*?</script>", " ", html)
    body = re.sub(r"<style[\s\S]*?</style>", " ", body)
    body = re.sub(r"<[^>]+>", "\n", body)
    body = body.replace("&nbsp;", " ").replace("&quot;", '"').replace("&amp;", "&")
    body = re.sub(r"\n\s*\n+", "\n", body)
    return "\n".join(line.strip() for line in body.splitlines() if line.strip())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0, help="0 = all")
    args = parser.parse_args()

    rows = [
        json.loads(line)
        for line in args.index.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if args.limit:
        rows = rows[: args.limit]

    saved = 0
    for index, row in enumerate(rows, start=1):
        event_id = f"e1-azipi-{row['azipi_message_id']}"
        target_dir = args.out_dir / event_id
        doc_id = f"azipi-{row['azipi_message_id']}"
        html_path = target_dir / f"{doc_id}.html"
        meta_path = target_dir / f"{doc_id}.meta.json"
        if meta_path.exists():
            continue

        print(f"[{index}/{len(rows)}] {row['issuer'][:56]}")
        raw = fetch_bytes(row["message_url"])
        target_dir.mkdir(parents=True, exist_ok=True)
        html_path.write_bytes(raw)
        (target_dir / f"{doc_id}.txt").write_text(
            extract_text(raw.decode("utf-8", errors="replace")), encoding="utf-8"
        )

        meta = {
            "doc_id": doc_id,
            "event_id": event_id,
            "url": row["message_url"],
            "source_type": "disclosure_agency_azipi",
            "published_at": to_iso_date(row["published_at"]) or to_iso_date(row["event_date"]),
            "retrieved_at": datetime.now(UTC).isoformat(),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "legal_use_status": LEGAL_USE_STATUS,
            "local_filename": html_path.name,
        }
        meta_path.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        saved += 1

    print(f"\nsaved {saved} new documents into {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
