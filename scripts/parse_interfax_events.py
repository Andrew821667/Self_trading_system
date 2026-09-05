#!/usr/bin/env python3
"""Извлечь факты из страниц сообщений e-disclosure.ru, сохранённых владельцем.

Читает `.webarchive` из `stage-E-1/documents/interfax/events/` и строит
JSONL, совместимый с инвентарём Stage E-1.

    python scripts/parse_interfax_events.py \\
        --events stage-E-1/documents/interfax/events \\
        --out stage-E-1/inventory/interfax_events.jsonl

## Что берётся и откуда

Сообщение идёт пронумерованным шаблоном регулятора — тем же по сути, что и
у AZIPI, но нумерация пунктов **зависит от типа сообщения** (у требования о
выкупе цена в 2.6, у предложения — в другом месте). Поэтому привязка идёт к
тексту пункта, а не к его номеру.

Эмитент, ИНН и дата берутся из самого документа — не из имени файла и не из
списка сообщений. Это прямое следствие разбора 2026-08-27: подпись рядом со
ссылкой в выдаче AZIPI принадлежала соседнему сообщению у 71,5% строк, и
из-за этого цена одной компании оказалась приписана другой. Документ —
единственный авторитет о том, про кого он.

Ничего не додумывается: поле, которое не прочиталось детерминированно,
остаётся пустым и попадает в `pending_fields`, как того требует правило D
чек-листа (неполные данные → дисквалифицировано).
"""

from __future__ import annotations

import argparse
import html as htmlmod
import json
import plistlib
import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

CLAUSE_RE = re.compile(r"(?=(\d+\.\d+)\.\s)")
# "RU 0009084214" — в этих документах ISIN пишут с пробелом после RU.
ISIN_RE = re.compile(r"\b(RU\s?[A-Z0-9]{10})\b")
INN_RE = re.compile(r"\b(\d{10}|\d{12})\b")
DATE_RE = re.compile(r"\b(\d{2}\.\d{2}\.\d{4})\b")
# Копейки пишут двумя способами, и оба встречаются в одном наборе из трёх
# документов: "481 (Четыреста восемьдесят один) рубль 68 копеек" и
# "234 (двести тридцать четыре) рубля 75 (семьдесят пять) копеек" — во втором
# между числом копеек и словом стоит расшифровка прописью. Без неё в шаблоне
# 234,75 превращалось в 234, то есть цена занижалась молча.
PRICE_RE = re.compile(
    r"(\d[\d\s ]*(?:[.,]\d{1,6})?)\s*(?:\([^)]*\))?\s*(?:руб|рубл|₽)"
    r"[^\d]{0,25}(?:(\d{1,2})\s*(?:\([^)]*\))?\s*коп)?",
    re.IGNORECASE,
)
EMPTY = ("не применимо", "отсутствует", "нет", "-", "—")

ISSUER_HINT = "полное фирменное наименование эмитента"
INN_HINT = "инн эмитента"
EVENT_DATE_HINTS = ("дата наступления события",)
PRICE_HINTS = (
    "цена выкупаемых ценных бумаг",
    "цена приобретаемых ценных бумаг",
    "цена приобретения",
    "цена, по которой",
)
ACQUIRER_HINTS = (
    "направившего требование о выкупе",
    "направившего добровольное",
    "направившего обязательное",
    "направившего уведомление",
)
GUARANTOR_HINT = "гаранта, предоставившего банковскую гарантию"
RECEIVED_HINTS = ("дата получения эмитентом",)


def read_page(path: Path) -> str:
    if path.suffix.lower() != ".webarchive":
        return path.read_text(encoding="utf-8", errors="replace")
    archive = plistlib.loads(path.read_bytes())
    data = archive.get("WebMainResource", {}).get("WebResourceData")
    return data.decode("utf-8", errors="replace") if isinstance(data, bytes) else ""


def to_text(page: str) -> str:
    body = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", page, flags=re.DOTALL | re.IGNORECASE)
    return re.sub(r"\s+", " ", htmlmod.unescape(re.sub(r"<[^>]+>", " ", body))).strip()


def clauses(text: str) -> list[tuple[str, str]]:
    """Пункты вида ('2.6', 'текст до следующего пункта')."""
    marks = [(m.group(1), m.start()) for m in CLAUSE_RE.finditer(text)]
    out = []
    for i, (num, pos) in enumerate(marks):
        end = marks[i + 1][1] if i + 1 < len(marks) else len(text)
        out.append((num, text[pos:end].strip()))
    return out


NOT_APPLICABLE = "не применимо"


def clause_with(items: list[tuple[str, str]], *hints: str) -> str | None:
    """Ответ пункта; NOT_APPLICABLE, если пункт есть и явно говорит «не применимо».

    Разница существенна для классификации: у вытеснения по ст. 84.8
    банковская гарантия не требуется, и документ так и пишет. Если вернуть
    None, поле попадёт в pending_fields, а правило D чек-листа
    дисквалифицирует событие за неполноту — то есть законная процедура
    отсеется по ошибке. Отсутствие требования и отсутствие данных — разное.
    """
    for _num, body in items:
        low = body.lower()
        if any(h in low for h in hints):
            # Ответ отделяют и двоеточием, и точкой с запятой — в шаблоне
            # требования о выкупе пункт 2.1 идёт через ";", и разбор только
            # по ":" терял приобретателя целиком.
            cut = min(
                (body.index(c) for c in ":;" if c in body),
                default=-1,
            )
            answer = body[cut + 1 :] if cut >= 0 else ""
            answer = answer.strip(" ;.-—")
            if not answer:
                continue
            if answer.lower().startswith(NOT_APPLICABLE):
                return NOT_APPLICABLE
            if answer.lower() not in EMPTY:
                return answer
    return None


def parse_price(text: str) -> str | None:
    m = PRICE_RE.search(text)
    if not m:
        return None
    try:
        value = Decimal(re.sub(r"[\s ]", "", m.group(1)).replace(",", "."))
    except InvalidOperation:
        return None
    if m.group(2):
        value += Decimal(m.group(2)) / 100
    return str(value) if 0 < value < Decimal(10_000_000) else None


def build(path: Path) -> dict | None:
    text = to_text(read_page(path))
    items = clauses(text)
    if not items:
        return None

    issuer = clause_with(items, ISSUER_HINT)
    inn_body = clause_with(items, INN_HINT)
    inn = INN_RE.search(inn_body) if inn_body else None
    if not (issuer and inn):
        return None

    price_body = clause_with(items, *PRICE_HINTS)
    guarantor = clause_with(items, GUARANTOR_HINT)
    acquirer = clause_with(items, *ACQUIRER_HINTS)
    date_body = clause_with(items, *EVENT_DATE_HINTS) or clause_with(items, *RECEIVED_HINTS)
    date_m = DATE_RE.search(date_body) if date_body else None
    isin_m = ISIN_RE.search(text)

    row = {
        "event_id": f"e1-ix-{path.stem}",
        "issuer": re.sub(r"\s+", " ", issuer).strip(),
        "inn": inn.group(1),
        "announcement_date": (
            f"{date_m.group(1)[6:]}-{date_m.group(1)[3:5]}-{date_m.group(1)[:2]}"
            if date_m
            else None
        ),
        "isin": isin_m.group(1).replace(" ", "") if isin_m else None,
        "procedure_price": parse_price(price_body) if price_body else None,
        "guarantor_bank": guarantor,
        "acquirer": acquirer,
        "source_document_refs": [path.name],
        "provenance": "e-disclosure.ru message page saved by the owner; issuer/INN/date read from the document itself",
        "retrieved_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    row["pending_fields"] = sorted(
        f
        for f in ("isin", "procedure_price", "guarantor_bank", "acquirer", "announcement_date")
        if not row.get(f)
    )
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--events", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    files = sorted(
        p for p in args.events.rglob("*") if p.suffix.lower() in {".webarchive", ".html"}
    )
    rows = [r for r in (build(p) for p in files) if r]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )
    filled = {
        f: sum(1 for r in rows if r.get(f))
        for f in (
            "inn",
            "announcement_date",
            "isin",
            "procedure_price",
            "guarantor_bank",
            "acquirer",
        )
    }
    print(f"файлов:   {len(files)}")
    print(f"разобрано: {len(rows)}")
    for f, c in filled.items():
        print(f"  {f:18} {c}/{len(rows)}")
    print(f"записано -> {args.out}")
    return 0 if rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
