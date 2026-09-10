#!/usr/bin/env python3
"""Прочитать документы пилота, отсекая всё опубликованное после даты события.

    python scripts/read_pilot_documents.py \\
        --pilot stage-E-1/documents/pilot --cutoff 2022-06-21

## Зачем отсечка живёт в коде

Чек-лист применяется вслепую: только по документам, доступным на дату
события. Владелец сохраняет страницу целиком — выставлять период в форме
портала он не может, — поэтому внутри файла лежат и послесобытийные строки.

Отсекать их глазами нельзя: человек, который листает ленту и решает, что
читать, успевает прочитать заголовки из будущего раньше, чем решит их не
читать. Поэтому отсечка здесь механическая и **до** любого показа: строка с
датой позже `--cutoff` не печатается, не возвращается и не попадает ни в
какой отчёт. Печатается только их количество — чтобы факт наличия был
зафиксирован, а содержимое осталось непрочитанным.

Строка без распознанной даты считается послесобытийной и отбрасывается:
неизвестная дата на этом шаге опаснее пропущенного факта.
"""

from __future__ import annotations

import argparse
import html as htmlmod
import plistlib
import re
from datetime import date
from pathlib import Path

ROW_DATE_RE = re.compile(r"\b(\d{2})\.(\d{2})\.(\d{4})\b")
# Признаки чек-листа, которые ищутся в тексте самого предложения.
EVIDENCE = {
    "П-1 отметка Банка России": re.compile(
        r"отметк[а-я]* о представлении|представлен[а-я]{0,3} в Банк Росси|"
        r"Банк России[^.]{0,80}(?:представлен|уведомлен)",
        re.IGNORECASE,
    ),
    "П-2 сумма гарантии": re.compile(
        r"(?:сумм[аы]|размер)[^.]{0,80}банковской гарантии|"
        r"банковск[а-я]+ гаранти[а-я]+[^.]{0,80}(?:сумм|размер)",
        re.IGNORECASE,
    ),
    "П-2 срок гарантии": re.compile(
        r"срок действия[^.]{0,60}гаранти|гарантия действует", re.IGNORECASE
    ),
    "П-2 безотзывность": re.compile(r"безотзывн", re.IGNORECASE),
    "П-3 средневзвешенная": re.compile(r"средневзвешенн", re.IGNORECASE),
    "П-3 отчёт оценщика": re.compile(r"оценщик", re.IGNORECASE),
    "П-8 конфликт/суд": re.compile(
        r"обеспечительн[а-я]+ мер|судебн[а-я]+ (?:спор|акт|разбирател)|исков[а-я]+ заявлен",
        re.IGNORECASE,
    ),
}


def read_webarchive(path: Path) -> str:
    data = plistlib.loads(path.read_bytes()).get("WebMainResource", {}).get("WebResourceData")
    return data.decode("utf-8", errors="replace") if isinstance(data, bytes) else ""


def to_text(page: str) -> str:
    body = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", page, flags=re.DOTALL | re.IGNORECASE)
    return htmlmod.unescape(re.sub(r"<[^>]+>", "\n", body))


def rows_before(text: str, cutoff: date) -> tuple[list[str], int]:
    """(строки не позже отсечки, сколько отброшено). Отброшенные не возвращаются."""
    kept: list[str] = []
    dropped = 0
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if len(line) < 12:
            continue
        match = ROW_DATE_RE.search(line)
        if not match:
            continue
        day, month, year = match.groups()
        try:
            when = date(int(year), int(month), int(day))
        except ValueError:
            dropped += 1
            continue
        if when <= cutoff:
            kept.append(f"{when.isoformat()}  {line[:150]}")
        else:
            dropped += 1
    return kept, dropped


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pilot", type=Path, required=True)
    ap.add_argument("--cutoff", required=True, help="дата события, ISO")
    args = ap.parse_args()
    cutoff = date.fromisoformat(args.cutoff)

    for path in sorted(args.pilot.glob("*.webarchive*")):
        text = to_text(read_webarchive(path))
        name = path.name.replace(".webarchive.webarchive", "").replace(".webarchive", "")
        print(f"\n{'=' * 70}\n{name}   ({len(text):,} знаков)\n{'=' * 70}")

        if "feed" in name:
            kept, dropped = rows_before(text, cutoff)
            print(
                f"строк не позже {cutoff}: {len(kept)};  отброшено как послесобытийные: {dropped}"
            )
            for line in kept[:60]:
                print(f"  {line}")
            if len(kept) > 60:
                print(f"  … ещё {len(kept) - 60}")
            continue

        flat = re.sub(r"\s+", " ", text)
        for label, pattern in EVIDENCE.items():
            match = pattern.search(flat)
            if not match:
                print(f"  {label:28} — нет")
                continue
            start = max(0, match.start() - 90)
            print(f"  {label:28} ЕСТЬ: …{flat[start : match.end() + 180].strip()}…")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
