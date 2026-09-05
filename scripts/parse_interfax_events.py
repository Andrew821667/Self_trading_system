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

# Нумерация пункта: "1.8." в шапке и "2.6" в теле — точка после второго числа
# ставится не всегда, и в одном и том же документе по-разному. Требование
# точки склеивало весь раздел 2 в один пункт, и тогда «дата наступления
# события» отвечала первым, что нашлось после ближайшего двоеточия, — у
# Русполимета это была дата госрегистрации выпуска 15.12.2005.
# Лишние условия: номер начинается после пробела (иначе «07.2020. » из даты
# читается как номер пункта) и первое число однозначное (иначе «20.1 устава»
# внутри 2.9 рвёт пункт пополам).
CLAUSE_RE = re.compile(r"(?<![^\s])([1-9]\.\d{1,2})\.?(?=\s)")
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
KOPECK_ONLY_RE = re.compile(r"(\d{1,2})\s*(?:\([^)]*\))?\s*копе", re.IGNORECASE)
# "1,89 (один рубль восемьдесят девять копеек) за одну акцию" — слова "рубль"
# рядом с цифрами нет вовсе, оно только внутри расшифровки прописью.
PRICE_PAREN_RE = re.compile(r"(\d[\d\s ]*(?:[.,]\d{1,6})?)\s*\([^)]*рубл[^)]*\)", re.IGNORECASE)
# Вытеснение по ст. 84.8 в ПАО МОСОБЛБАНК после санации: цена выкупа записана
# дробью — "1 / 4 507 984 112 (...доля) рубля за 1 (одну) акцию". Это не сбой
# распознавания, а действительная цена: акции после докапитализации стоят
# околонулевую долю рубля. Без этой ветки поле осталось бы пустым и правило D
# чек-листа выбросило бы законное событие как «неполные данные».
PRICE_FRACTION_RE = re.compile(r"(\d[\d\s ]*)\s*/\s*(\d[\d\s ]*)\s*\([^)]*\)\s*рубл", re.IGNORECASE)
EMPTY = ("не применимо", "отсутствует", "нет", "-", "—")

# Дату пишут и цифрами, и прописью — "14 декабря 2020 года", "02 июня 2020 г."
# — причём в одном документе в шапке одно, в пункте 2.4 другое. Два сообщения
# из 33 остались без даты именно поэтому.
MONTHS = {
    m: i
    for i, m in enumerate(
        (
            "январ",
            "феврал",
            "март",
            "апрел",
            "мая",
            "июн",
            "июл",
            "август",
            "сентябр",
            "октябр",
            "ноябр",
            "декабр",
        ),
        start=1,
    )
}
WORD_DATE_RE = re.compile(
    r"\b(\d{1,2})\s+(" + "|".join(MONTHS) + r")[а-я]*\s+(\d{4})", re.IGNORECASE
)

# Шаблон сообщения существует минимум в двух редакциях, и расходятся они не
# только нумерацией пунктов, но и формулировками. В ранней ИНН стоит как
# "ИНН эмитента", в поздней — "Идентификационный номер налогоплательщика
# (ИНН) эмитента (при наличии)"; наименование в поздней разорвано вставкой
# "(для коммерческой организации) или наименование (для некоммерческой
# организации)". На подстроках 12 документов из 33 не разобрались вовсе,
# поэтому подсказки — шаблоны.
ISSUER_HINT = re.compile(r"полное фирменное наименование.{0,90}эмитента", re.IGNORECASE)
INN_HINT = re.compile(
    r"(?:идентификационный номер налогоплательщика|\bинн\b).{0,30}эмитента", re.IGNORECASE
)
EVENT_DATE_HINTS = (re.compile(r"дата наступления события", re.IGNORECASE),)
PRICE_HINTS = (
    re.compile(r"цена\s+(?:выкупаемых|приобретаемых|приобретения)", re.IGNORECASE),
    re.compile(r"предлагаемая цена", re.IGNORECASE),
    re.compile(r"цена,\s+по которой", re.IGNORECASE),
)
ACQUIRER_HINTS = (
    re.compile(
        r"направившего\s+(?:требование о выкупе|добровольное|обязательное|уведомление)",
        re.IGNORECASE,
    ),
)
GUARANTOR_HINT = re.compile(r"гаранта,\s+предоставившего банковскую гарантию", re.IGNORECASE)
RECEIVED_HINTS = (re.compile(r"дата получения эмитентом", re.IGNORECASE),)


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


def clause_with(items: list[tuple[str, str]], *hints: re.Pattern[str]) -> str | None:
    """Ответ пункта; NOT_APPLICABLE, если пункт есть и явно говорит «не применимо».

    Разница существенна для классификации: у вытеснения по ст. 84.8
    банковская гарантия не требуется, и документ так и пишет. Если вернуть
    None, поле попадёт в pending_fields, а правило D чек-листа
    дисквалифицирует событие за неполноту — то есть законная процедура
    отсеется по ошибке. Отсутствие требования и отсутствие данных — разное.
    """
    for _num, body in items:
        match = next((h.search(body) for h in hints if h.search(body)), None)
        if match:
            # Ответ отделяют двоеточием, точкой с запятой — или ничем: в части
            # шаблонов он просто идёт следом за вопросом. Разбор только по ":"
            # терял приобретателя у требований о выкупе, а отсутствие
            # разделителя роняло пять документов целиком.
            # Разделитель ищется после вопроса, а не в начале пункта: в
            # пункте 2.1 двоеточие стоит и внутри перечисления реквизитов.
            tail = body[match.start() :]
            cut = min((tail.index(c) for c in ":;" if c in tail), default=-1)
            answer = tail[cut + 1 :] if cut >= 0 else body[match.end() :]
            # Хвост вопроса бывает в скобках: "...эмитента (при наличии) 7104002774".
            answer = re.sub(r"^\s*(?:\([^)]*\)\s*)+", "", answer)
            answer = answer.strip(" ;.-—")
            if not answer:
                continue
            if answer.lower().startswith(NOT_APPLICABLE):
                return NOT_APPLICABLE
            if answer.lower() not in EMPTY:
                return answer
    return None


def parse_date(text: str) -> str | None:
    """ISO-дата из ответа пункта: сперва цифрами, затем прописью."""
    m = DATE_RE.search(text)
    if m:
        d, mo, y = m.group(1).split(".")
        return f"{y}-{mo}-{d}"
    w = WORD_DATE_RE.search(text)
    if not w:
        return None
    month = MONTHS[next(k for k in MONTHS if w.group(2).lower().startswith(k))]
    return f"{w.group(3)}-{month:02d}-{int(w.group(1)):02d}"


def _number(raw: str) -> Decimal | None:
    try:
        return Decimal(re.sub(r"[\s  ]", "", raw).replace(",", "."))
    except InvalidOperation:
        return None


def parse_price(text: str) -> str | None:
    frac = PRICE_FRACTION_RE.search(text)
    if frac:
        num, den = _number(frac.group(1)), _number(frac.group(2))
        if num is None or not den:
            return None
        # Копеечная точность тут бессмысленна, а деление даёт 28 значащих
        # цифр и запись через E, которую ниже по конвейеру никто не ждёт.
        return format((num / den).quantize(Decimal("1E-10")).normalize(), "f")

    m = PRICE_RE.search(text)
    if m:
        value = _number(m.group(1))
        if value is None:
            return None
        # Копейки прибавляются, только если рубли записаны целым числом.
        # "0,75 рубля (75 копеек)" — это одна и та же цена, названная дважды;
        # сложение давало 1,50, то есть ровно вдвое завышало цену выкупа.
        if m.group(2) and value == value.to_integral_value():
            value += Decimal(m.group(2)) / 100
        return format(value, "f") if 0 < value < Decimal(10_000_000) else None

    par = PRICE_PAREN_RE.search(text)
    if par:
        value = _number(par.group(1))
        if value is not None and 0 < value < Decimal(10_000_000):
            return format(value, "f")
    # Цена ниже рубля пишется вообще без рублей: «61 (шестьдесят одна)
    # копейка за 1 (одну) акцию». Копеечные номиналы на этом рынке не
    # экзотика — у Русполимета в 2020 акция стоила меньше рубля, — и без
    # этой ветки такое предложение молча оставалось без цены.
    k = KOPECK_ONLY_RE.search(text)
    if not k:
        return None
    try:
        return format(Decimal(k.group(1)) / 100, "f")
    except InvalidOperation:
        return None


def build(path: Path) -> dict | None:
    text = to_text(read_page(path))
    items = clauses(text)
    if not items:
        return None

    issuer = clause_with(items, ISSUER_HINT)
    # ИНН ищется во всём пункте, а не в «ответе»: разделителя может не быть
    # вовсе, а десяти- или двенадцатизначное число в этом пункте одно.
    inn_clause = next((b for _n, b in items if INN_HINT.search(b)), None)
    inn = INN_RE.search(inn_clause) if inn_clause else None
    if not (issuer and inn):
        return None

    price_body = clause_with(items, *PRICE_HINTS)
    guarantor = clause_with(items, GUARANTOR_HINT)
    acquirer = clause_with(items, *ACQUIRER_HINTS)
    date_body = clause_with(items, *EVENT_DATE_HINTS) or clause_with(items, *RECEIVED_HINTS)
    isin_m = ISIN_RE.search(text)

    row = {
        "event_id": f"e1-ix-{path.stem}",
        "issuer": re.sub(r"\s+", " ", issuer).strip(),
        "inn": inn.group(1),
        "announcement_date": parse_date(date_body) if date_body else None,
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
