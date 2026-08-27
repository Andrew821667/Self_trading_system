#!/usr/bin/env python3
"""Сверить скачанные документы AZIPI с их же строкой в индексе (Stage E-1).

Найдено 2026-08-27: у события `e1-azipi-4389568` (записано в индексе как
Калужская сбытовая компания, 24.03.2025) текст самого документа — это
«Объединение Орджоникидзе 11», 31.03.2025. Не заглушка: настоящий, полный,
пронумерованный документ, просто про другого эмитента. При этом цена из
этого чужого документа (103 ₽) уже попала в `economic_test.csv` как цена
KLSB и там же «подтверждена по тексту» — верно, но не за то событие.

Первая строка каждого документа — `Эмитент (ИНН: …) / Тип - дата` — и это
не заголовок HTML, а факт, заявленный самим документом. Скрипт сверяет его
с тем, что `azipi_index.jsonl` записал при сборе индекса: тот же ИНН, та
же дата. Расхождение — сигнал, что при сборе индекса или документа что-то
пошло не так (сбойная страница-заглушка, смещение регулярки по таблице,
протухшая ссылка), а не что событие достоверно.

Ничего не исправляет и не удаляет: это отчёт, решение по каждому
расхождению — отдельным шагом, вручную.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

TITLE_RE = re.compile(
    r"^(?P<issuer>.+?)\s*\(ИНН:\s*(?P<inn>\d+)\)\s*/\s*.+?\s*-\s*(?P<date>\d{2}\.\d{2}\.\d{4})\s*$"
)
STUB_MARKER = "Список сообщений"


def normalise(name: str) -> str:
    return re.sub(r"[^0-9а-яёa-z]", "", name.lower())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, default=Path("stage-E-1/inventory/azipi_index.jsonl"))
    parser.add_argument("--documents", type=Path, default=Path("stage-E-1/documents"))
    parser.add_argument(
        "--out", type=Path, default=Path("stage-E-1/inventory/azipi_document_audit.csv")
    )
    args = parser.parse_args()

    index = {
        row["azipi_message_id"]: row
        for row in (
            json.loads(line)
            for line in args.index.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    }

    results: list[dict] = []
    for meta_path in sorted(args.documents.glob("*/azipi-*.meta.json")):
        # meta_path.stem strips only the last suffix, leaving "azipi-<id>.meta"
        # — two dots, one Path.stem call. Strip both explicitly instead.
        message_id = meta_path.name.removesuffix(".meta.json").removeprefix("azipi-")
        text_path = meta_path.with_name(f"azipi-{message_id}.txt")
        indexed = index.get(message_id)
        if indexed is None:
            results.append({"message_id": message_id, "status": "not_in_index"})
            continue
        if not text_path.is_file():
            results.append(
                {
                    "message_id": message_id,
                    "status": "text_missing",
                    "issuer_indexed": indexed["issuer"],
                }
            )
            continue

        first_line = (
            text_path.read_text(encoding="utf-8", errors="replace").splitlines()[0]
            if text_path.stat().st_size
            else ""
        )
        if STUB_MARKER in first_line or not first_line.strip():
            results.append(
                {
                    "message_id": message_id,
                    "status": "stub_page",
                    "issuer_indexed": indexed["issuer"],
                    "date_indexed": indexed["event_date"],
                }
            )
            continue

        match = TITLE_RE.match(first_line.strip())
        if not match:
            results.append(
                {
                    "message_id": message_id,
                    "status": "title_unparsed",
                    "issuer_indexed": indexed["issuer"],
                    "first_line": first_line[:120],
                }
            )
            continue

        inn_matches = match.group("inn") == indexed["inn"]
        # даты в индексе и в документе иногда расходятся на день (раскрытие
        # публикуется на следующие сутки после события) — это не ошибка.
        date_matches = match.group("date") == indexed["event_date"]
        name_matches = normalise(match.group("issuer")) == normalise(indexed["issuer"])

        results.append(
            {
                "message_id": message_id,
                "status": "ok" if inn_matches else "mismatch",
                "issuer_indexed": indexed["issuer"],
                "issuer_in_document": match.group("issuer"),
                "inn_indexed": indexed["inn"],
                "inn_in_document": match.group("inn"),
                "date_indexed": indexed["event_date"],
                "date_in_document": match.group("date"),
                "inn_matches": inn_matches,
                "date_matches": date_matches,
                "name_matches": name_matches,
            }
        )

    fieldnames = sorted({key for row in results for key in row})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    counts: dict[str, int] = {}
    for row in results:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    print(f"документов проверено: {len(results)}")
    for status, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {status}: {count}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
