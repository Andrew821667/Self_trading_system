#!/usr/bin/env python3
"""Свести инвентари двух порталов в один `stage-E-1/inventory/events.jsonl`.

    python scripts/merge_e1_inventory.py \\
        --inputs stage-E-1/inventory/azipi_events.jsonl \\
                 stage-E-1/inventory/interfax_events.jsonl \\
        --documents stage-E-1/documents \\
        --out stage-E-1/inventory/events.jsonl

АЗИПИ и «Интерфакс-ЦРКИ» — два раскрывателя одного и того же рынка, и их
ленты пересекаются частично: из 266 событий АЗИПИ в выдаче «Интерфакса»
нашлось 143. Поэтому объединение — не конкатенация: одно и то же событие
приходит из обоих источников под разными идентификаторами сообщения, и без
схлопывания оно вошло бы в выборку дважды и вдвое утяжелило бы свой вклад в
любую последующую статистику.

## Ключ схлопывания

`(ИНН эмитента, дата события, тип события)`. ИНН, а не наименование: одна и
та же компания пишется в сообщениях и «ПАО «Русполимет»», и «Публичное
акционерное общество «Русполимет»», а ИНН у неё один. ИНН берётся из первой
строки документа — того самого самоописания, которое разбор АЗИПИ и разбор
«Интерфакса» пишут в одном формате именно ради этого.

Тип события в ключе обязателен: 21.11.2022 РОСБАНК раскрыл в один день и
добровольное, и обязательное предложение по одной цене — это два разных
сообщения (коды 3341820 и 3341798) об одной сделке, но одного типа
`voluntary_or_mandatory_offer`, и они схлопываются. А вот предложение и
последующее требование о выкупе по той же бумаге — разные события, и
разными они остаются.

## Кто побеждает при совпадении

Строка с бо́льшим числом прочитанных фактов. Ни одна не «правильнее» другой
по происхождению: обе прочитаны из самоописания документа. При равенстве
берётся первый источник в порядке `--inputs`, чтобы результат не зависел от
порядка файлов на диске.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

FACT_FIELDS = ("isin", "procedure_price", "price_basis", "guarantor_bank", "acquirer")
# Первая строка документа: "Эмитент (ИНН: X) / Тип сообщения - ДД.ММ.ГГГГ".
# Один формат у обоих источников — см. build_e1_inventory.document_identity и
# parse_interfax_events.build.
_TITLE_RE = re.compile(r"^(?P<issuer>.+?)\s*\(ИНН:\s*(?P<inn>\d+)\)\s*/")


def document_inn(documents: Path, row: dict) -> str | None:
    for doc_id in row["source_document_refs"]:
        path = documents / row["event_id"] / f"{doc_id}.txt"
        if not path.is_file():
            continue
        first_line = path.read_text(encoding="utf-8").splitlines()[:1]
        match = _TITLE_RE.match(first_line[0].strip()) if first_line else None
        if match:
            return match.group("inn")
    return None


def facts_read(row: dict) -> int:
    return sum(1 for f in FACT_FIELDS if row.get(f))


def load(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--inputs", type=Path, nargs="+", required=True)
    ap.add_argument("--documents", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    chosen: dict[tuple[str, str, str], dict] = {}
    unkeyed: list[dict] = []
    seen_ids: set[str] = set()
    per_source = Counter()
    merged: list[tuple[str, tuple[str, str, str]]] = []

    for source in args.inputs:
        for row in load(source):
            per_source[source.name] += 1
            if row["event_id"] in seen_ids:
                raise SystemExit(f"duplicate event_id across inputs: {row['event_id']}")
            seen_ids.add(row["event_id"])

            inn = document_inn(args.documents, row)
            if inn is None or not row.get("announcement_date"):
                # Без ИНН или без даты события схлопывать не по чему. Строка
                # не выбрасывается: она попадёт в инвентарь как есть, и
                # возможный дубль лучше видеть, чем потерять событие.
                unkeyed.append(row)
                continue

            key = (inn, row["announcement_date"], row["event_type"])
            rival = chosen.get(key)
            if rival is None:
                chosen[key] = row
                continue
            keep, drop = (rival, row) if facts_read(rival) >= facts_read(row) else (row, rival)
            chosen[key] = keep
            # Победитель запоминается ключом, а не идентификатором: у
            # одного события бывает три сообщения, и промежуточный
            # победитель сам потом проигрывает третьему. Печатать его
            # как «оставлено» значило бы соврать в журнале слияния.
            merged.append((drop["event_id"], key))

    rows = list(chosen.values()) + unkeyed
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        for row in sorted(
            rows, key=lambda r: (r["event_type"], r["announcement_date"] or "", r["issuer"])
        ):
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    ready = sum(1 for r in rows if not r["pending_fields"])
    print("на входе:")
    for name, count in per_source.items():
        print(f"  {name:28} {count}")
    print(f"схлопнуто дублей: {len(merged)}")
    for drop, key in sorted(merged):
        print(f"  {drop} -> {chosen[key]['event_id']}")
    print(f"без ключа (нет ИНН или даты), оставлены как есть: {len(unkeyed)}")
    print(f"записано {len(rows)} строк -> {args.out}")
    print(f"  готовы к классификации: {ready}")
    print(f"  ждут фактов документа:  {len(rows) - ready}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
