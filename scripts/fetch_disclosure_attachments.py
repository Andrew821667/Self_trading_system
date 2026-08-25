#!/usr/bin/env python3
"""Fetch and render E-1 offer attachments from disclosure.ru (Stage E-1, Phase A).

The AZIPI message says an offer arrived; the offer's terms are in the files
attached to it. AK&M's archive serves those files for its own clients at
``disclosure.ru/issuer/<INN>/`` without an anti-bot, as RAR5 archives that
usually contain the offer itself, the appraiser's report and the board's
recommendation.

This script does Phase A work only: fetch the raw file, record its provenance,
and render a readable text version. It does **not** parse facts into the
inventory. Structured extraction is Stage E1 (ТЗ 6.3-6.5), where the
extraction model and prompt version are pinned and checked against a golden
set; ad-hoc regexes here would put unrecorded, unverifiable extraction under
the whole study.

Rendering has two paths and the one used is recorded per file, because they
are not equally trustworthy:

* ``text_layer`` — pdftotext on a PDF that has real text. Exact.
* ``ocr`` — the document is a scan, so it is rasterised and run through
  tesseract. Digits are misread: in the very document this pipeline was
  built on, OCR turned INN 0264011929 into 09264011929 while reading the
  price correctly. Russian procedure documents write every amount twice —
  "8,09 (Восемь рублей) 09 копеек" — so the words are available as a
  checksum on the numeral. Nothing downstream may take an OCR'd number
  without one.

Raw binaries are not committed (see .gitignore); the ``.meta.json`` carries
the URL and sha256, so any committed rendition can be traced back to a file
that can be re-fetched and verified byte-for-byte.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

socket.setdefaulttimeout(120)

FILE_URL = "https://www.disclosure.ru/issuer/GetFileMD5?md5={md5}"
ISSUER_URL = "https://www.disclosure.ru/issuer/{inn}/"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
REQUEST_DELAY_SECONDS = 2.0
MAX_ATTEMPTS = 4

# A PDF whose text layer yields less than this is a scan, not a document with
# selectable text; the few bytes are page-break artefacts.
TEXT_LAYER_MIN_CHARS = 200
OCR_DPI = 300
OCR_MAX_PAGES = 40
REQUIRED_TOOLS = ("bsdtar", "pdftotext", "pdftoppm", "tesseract")


def require_tools() -> None:
    missing = [tool for tool in REQUIRED_TOOLS if shutil.which(tool) is None]
    if missing:
        raise SystemExit(
            f"missing native tools: {', '.join(missing)}\n"
            "run scripts/setup_document_toolchain.sh first"
        )


def sniff_suffix(payload: bytes) -> str:
    """File type from magic bytes. Titles are not a reliable source."""
    if payload.startswith(b"%PDF"):
        return ".pdf"
    if payload.startswith(b"PK\x03\x04"):
        return ".docx"  # OOXML; render_member reads it as a zip either way
    if payload.startswith(b"{\\rtf"):
        return ".rtf"
    if payload.startswith(b"\xd0\xcf\x11\xe0"):
        return ".doc"  # legacy OLE2 — recorded, not renderable here
    return ".bin"


def download(url: str, referer: str) -> bytes | None:
    for attempt in range(MAX_ATTEMPTS):
        request = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Referer": referer}
        )
        try:
            with urllib.request.urlopen(request) as response:
                return response.read()
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


def render_pdf(pdf: Path, workdir: Path) -> tuple[str, str]:
    """Return (text, method). Falls back to OCR when there is no text layer."""
    plain = workdir / f"{pdf.stem}.txt"
    subprocess.run(
        ["pdftotext", "-layout", str(pdf), str(plain)],
        check=False,
        capture_output=True,
    )
    text = plain.read_text(encoding="utf-8", errors="replace") if plain.is_file() else ""
    if len(text.strip()) >= TEXT_LAYER_MIN_CHARS:
        return text, "text_layer"

    pages = workdir / "pages"
    pages.mkdir(exist_ok=True)
    subprocess.run(
        [
            "pdftoppm",
            "-r",
            str(OCR_DPI),
            "-png",
            "-f",
            "1",
            "-l",
            str(OCR_MAX_PAGES),
            str(pdf),
            str(pages / "p"),
        ],
        check=False,
        capture_output=True,
    )
    chunks: list[str] = []
    for image in sorted(pages.glob("p-*.png")):
        result = subprocess.run(
            ["tesseract", str(image), "stdout", "-l", "rus", "--psm", "6"],
            check=False,
            capture_output=True,
        )
        chunks.append(result.stdout.decode("utf-8", errors="replace"))
        image.unlink()
    return "\n".join(chunks), "ocr"


def render_member(member: Path, workdir: Path) -> tuple[str, str]:
    suffix = member.suffix.lower()
    if suffix == ".pdf":
        return render_pdf(member, workdir)
    if suffix in {".txt", ".htm", ".html", ".xml"}:
        return member.read_text(encoding="utf-8", errors="replace"), "text_layer"
    if suffix in {".docx", ".xlsx"}:
        # OOXML is a zip of XML; the document text is recoverable without a
        # converter, tags stripped. Good enough to read, not to lay out.
        result = subprocess.run(
            ["bsdtar", "-xOf", str(member), "word/document.xml", "xl/sharedStrings.xml"],
            check=False,
            capture_output=True,
        )
        raw = result.stdout.decode("utf-8", errors="replace")
        text = re.sub(r"<[^>]+>", " ", raw)
        return re.sub(r"[ \t]+", " ", text), "ooxml"
    return "", "unsupported"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--documents", type=Path, required=True, help="probe output CSV")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--max-total-mb",
        type=int,
        default=1500,
        help="stop before filling the session's disk allowance",
    )
    args = parser.parse_args()
    require_tools()

    rows = list(csv.DictReader(args.documents.open(encoding="utf-8")))
    if args.limit:
        rows = rows[: args.limit]

    downloaded_bytes = 0
    manifest: list[dict] = []
    for position, row in enumerate(rows, start=1):
        md5 = row["md5"]
        target = args.out_dir / row["inn"] / md5
        meta_path = target.with_suffix(".meta.json")
        if meta_path.is_file():
            manifest.append(json.loads(meta_path.read_text(encoding="utf-8")))
            continue
        if downloaded_bytes > args.max_total_mb * 1024 * 1024:
            print(f"stopping at {args.max_total_mb} MB budget", file=sys.stderr)
            break

        url = FILE_URL.format(md5=md5)
        payload = download(url, ISSUER_URL.format(inn=row["inn"]))
        time.sleep(REQUEST_DELAY_SECONDS)
        if payload is None:
            continue
        downloaded_bytes += len(payload)

        target.parent.mkdir(parents=True, exist_ok=True)
        archive = target.with_suffix(".bin")
        archive.write_bytes(payload)

        workdir = target
        workdir.mkdir(exist_ok=True)
        subprocess.run(
            ["bsdtar", "-xf", str(archive), "-C", str(workdir)],
            check=False,
            capture_output=True,
        )
        members = [p for p in workdir.rglob("*") if p.is_file()]
        if not members:
            # Not every entry is an archive; some are a bare PDF or DOCX. The
            # extension cannot come from the title — these titles end in a
            # date ("Требование о выкупе акций АО НКГФ 23.10.2024"), so
            # Path(title).suffix yields ".2024" and the renderer skips a real
            # 14-page document as an unsupported type. Sniff magic bytes.
            single = workdir / f"{md5}{sniff_suffix(payload)}"
            single.write_bytes(payload)
            members = [single]

        renditions = []
        for member in sorted(members):
            text, method = render_member(member, workdir)
            if not text.strip():
                renditions.append({"member": member.name, "method": method, "chars": 0})
                continue
            rendition = target.parent / f"{md5}--{member.stem[:60]}.txt"
            rendition.write_text(text, encoding="utf-8")
            renditions.append(
                {
                    "member": member.name,
                    "method": method,
                    "chars": len(text),
                    "rendition": rendition.name,
                }
            )

        meta = {
            "md5_from_index": md5,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "bytes": len(payload),
            "url": url,
            "source_type": "disclosure_agency_akm",
            "inn": row["inn"],
            "issuer": row["issuer"],
            "title": row["title"],
            "published_at": row.get("published_at", ""),
            "retrieved_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "legal_use_status": "public_disclosure",
            "renditions": renditions,
        }
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        manifest.append(meta)
        print(
            f"[{position}/{len(rows)}] {row['inn']} {len(payload) // 1024:6d} KB "
            f"{len(renditions)} member(s)",
            file=sys.stderr,
        )

    ocr = sum(1 for m in manifest for r in m["renditions"] if r["method"] == "ocr")
    layer = sum(1 for m in manifest for r in m["renditions"] if r["method"] == "text_layer")
    print(f"documents on disk:      {len(manifest)}")
    print(f"  renditions от text layer: {layer}")
    print(f"  renditions от OCR:        {ocr}  (numbers need the words checksum)")
    print(f"downloaded this run:    {downloaded_bytes // (1024 * 1024)} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
