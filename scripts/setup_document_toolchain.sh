#!/usr/bin/env bash
# Native tools needed to read E-1 offer attachments. Not Python packages, so
# uv does not manage them and a fresh container will not have them.
#
# Why each one:
#   libarchive-tools  bsdtar reads RAR5, which is how disclosure.ru serves
#                     offer attachments. There is no unrar in this image and
#                     no pure-Python RAR5 decoder, so this is the only door.
#   poppler-utils     pdftotext for PDFs that have a text layer, pdftoppm to
#                     rasterise the ones that do not.
#   tesseract-ocr-rus most offers are scans. Without the Russian model,
#                     Cyrillic OCR is unusable.
#
# Read prices from OCR only with the numeral/words cross-check (Russian
# procedure documents always write the amount twice: "8,09 (Восемь рублей)
# 09 копеек"). OCR misreads digits — it read this issuer's INN as
# 09264011929 instead of 0264011929 in the same document it got the price
# right in. The words are the checksum; a price without one is not a fact.
set -euo pipefail

apt-get update -qq || echo "apt-get update reported errors; continuing with cached index" >&2
apt-get install -y --no-install-recommends \
    libarchive-tools \
    poppler-utils \
    tesseract-ocr \
    tesseract-ocr-rus

for tool in bsdtar pdftotext pdftoppm tesseract; do
    command -v "$tool" >/dev/null || { echo "missing after install: $tool" >&2; exit 1; }
done
tesseract --list-langs 2>&1 | grep -qx rus || { echo "missing Russian OCR model" >&2; exit 1; }
echo "document toolchain ready: bsdtar, pdftotext, pdftoppm, tesseract(rus)"
