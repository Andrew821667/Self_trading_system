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
import hashlib
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

# "код сообщeния: 3045208" — на странице портала буква "e" в слове латинская;
# шаблон намеренно принимает обе, чтобы опечатка в вёрстке не стоила нам
# устойчивого идентификатора сообщения.
MESSAGE_CODE_RE = re.compile(r"код сообщ[еe]ния:\s*(\d+)", re.IGNORECASE)
# Штамп публикации портала прямо над кодом сообщения: "28.07.2020 08:39".
PUBLISHED_RE = re.compile(
    r"(\d{2})\.(\d{2})\.(\d{4})\s+(\d{2}:\d{2})\s+код сообщ[еe]ния", re.IGNORECASE
)
SOURCE_TYPE = "disclosure_center_interfax"
# Заголовок сообщения → семейство события. Соответствие взято один в один из
# TYPE_CODES в scripts/collect_azipi.py, чтобы событие получало один и тот же
# event_type независимо от того, из какого портала оно пришло.
MESSAGE_TYPES: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"Поступление эмитенту (?:добровольного|обязательного|конкурирующего) предложения"
            r"[^.]{0,80}?ценных бумаг",
            re.IGNORECASE,
        ),
        "voluntary_or_mandatory_offer",
    ),
    (
        re.compile(
            r"Поступление эмитенту (?:требования о выкупе|уведомления о праве требовать)"
            r"[^.]{0,80}?ценных бумаг",
            re.IGNORECASE,
        ),
        "squeeze_out_request_95",
    ),
)
# Формулировки, которыми эмитент объясняет, откуда взялась цена. Совпадают со
# scripts/build_e1_inventory.py: price_basis должен значить одно и то же в
# обеих половинах инвентаря, иначе классификация читает разные шкалы.
PRICE_BASIS_PATTERNS: tuple[tuple[str, str], ...] = (
    ("средневзвешенн", "биржевая средневзвешенная цена"),
    ("оценщик", "рыночная стоимость по отчёту оценщика"),
    ("организатор", "цена по данным организатора торговли"),
    ("наибольш", "наибольшая из предусмотренных законом величин"),
)


def published_at(text: str) -> str | None:
    """ISO-дата публикации сообщения по штампу портала."""
    m = PUBLISHED_RE.search(text)
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def price_basis_of(clause_text: str | None) -> str | None:
    if not clause_text:
        return None
    lowered = clause_text.lower()
    return next((label for needle, label in PRICE_BASIS_PATTERNS if needle in lowered), None)


def read_page(path: Path) -> str:
    if path.suffix.lower() != ".webarchive":
        return path.read_text(encoding="utf-8", errors="replace")
    archive = plistlib.loads(path.read_bytes())
    data = archive.get("WebMainResource", {}).get("WebResourceData")
    return data.decode("utf-8", errors="replace") if isinstance(data, bytes) else ""


def page_url(path: Path) -> str:
    """Адрес, с которого страница сохранена — из самого `.webarchive`.

    Safari кладёт исходный URL внутрь архива, поэтому его не нужно ни
    угадывать по коду сообщения, ни спрашивать у владельца: сохранённый файл
    сам знает, откуда он.
    """
    if path.suffix.lower() != ".webarchive":
        return ""
    archive = plistlib.loads(path.read_bytes())
    return str(archive.get("WebMainResource", {}).get("WebResourceURL") or "")


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


def has_clause(items: list[tuple[str, str]], *hints: re.Pattern[str]) -> bool:
    """Есть ли в документе пункт, который такой факт вообще несёт.

    Это не то же самое, что «факт прочитан». Пункт про ценовую базу
    существует почти всегда, но почти никогда её не называет — там просто
    число. Прочитать пункт и увидеть, что базы в нём нет, — это результат,
    а не пробел; такое поле остаётся пустым, но НЕ попадает в
    `pending_fields`. Пустое поле при отсутствующем пункте — другое дело:
    факт может лежать в приложении, которого мы не открывали, и вот он
    действительно pending.
    """
    return any(h.search(body) for _num, body in items for h in hints)


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


def pending_fields(row: dict, items: list[tuple[str, str]], event_type: str) -> list[str]:
    """Факты, которые документ несёт, но этот проход их не прочитал.

    Схема `InventoryEvent` требует различать «ещё не прочитано» и «прочитано,
    факта в документе нет» — правило D чек-листа дисквалифицирует событие за
    первое, но не за второе. Прежняя реализация помечала pending любое пустое
    поле и тем самым смешивала эти два состояния: `price_basis` оказывался
    pending у 265 событий из 270, хотя пункт о цене прочитан целиком и базы в
    нём просто не названо — она в приложенном отчёте оценщика. При таком
    счёте к классификации не допускался вообще никто.

    Правило здесь буквальное: pending — там, где не прочитан сам носитель
    факта.

    * цена и ценовая база — pending, если пункта о цене в документе не нашлось
      (короткое уведомление со ссылкой на приложение). Если пункт найден и
      прочитан, базы в нём нет — это ответ, а не пробел;
    * гарант — pending только у предложений (ст. 84.1/84.2), где гарантия
      обязательна. У вытеснения по ст. 84.8 она не требуется, и её отсутствие
      не пробел;
    * ISIN — не факт документа в смысле чек-листа, а идентификатор бумаги;
      если сообщение называет только госномер выпуска, бумага находится по
      ИНН через справочник MOEX (scripts/check_tradability.py), поэтому
      pending здесь не ставится.
    """
    pending: list[str] = []
    price_clause_read = has_clause(items, *PRICE_HINTS)
    if not row.get("procedure_price") and not price_clause_read:
        pending.append("procedure_price")
    if not row.get("price_basis") and not price_clause_read:
        pending.append("price_basis")
    if (
        not row.get("guarantor_bank")
        and event_type == "voluntary_or_mandatory_offer"
        and not has_clause(items, GUARANTOR_HINT)
    ):
        pending.append("guarantor_bank")
    if not row.get("acquirer") and not has_clause(items, *ACQUIRER_HINTS):
        pending.append("acquirer")
    return sorted(pending)


def event_type_of(text: str) -> tuple[str, str] | None:
    """(event_type, заголовок сообщения) по типу сообщения на странице.

    Соответствие ровно то же, что TYPE_CODES в scripts/collect_azipi.py: у
    АЗИПИ разные коды на добровольное и обязательное предложение сведены в
    одно семейство, и здесь так же — иначе одно и то же событие получило бы
    разный event_type в зависимости от того, через какой портал оно пришло.
    """
    for pattern, event_type in MESSAGE_TYPES:
        m = pattern.search(text)
        if m:
            return event_type, m.group(0)
    return None


def build(path: Path) -> tuple[dict, str, dict] | None:
    """(строка инвентаря, текст документа, метаданные) или None, если не читается."""
    text = to_text(read_page(path))
    items = clauses(text)
    if not items:
        return None

    issuer = clause_with(items, ISSUER_HINT)
    # ИНН ищется во всём пункте, а не в «ответе»: разделителя может не быть
    # вовсе, а десяти- или двенадцатизначное число в этом пункте одно.
    inn_clause = next((b for _n, b in items if INN_HINT.search(b)), None)
    inn = INN_RE.search(inn_clause) if inn_clause else None
    kind = event_type_of(text)
    if not (issuer and inn and kind):
        return None
    event_type, title = kind

    price_body = clause_with(items, *PRICE_HINTS)
    guarantor = clause_with(items, GUARANTOR_HINT)
    acquirer = clause_with(items, *ACQUIRER_HINTS)
    date_body = clause_with(items, *EVENT_DATE_HINTS) or clause_with(items, *RECEIVED_HINTS)
    isin_m = ISIN_RE.search(text)

    # `announcement_date` — дата **раскрытия**, а не дата наступления события.
    # Так её определяет stage-E-1/README.md ("дата первого раскрытия"), и это
    # не формальность: у 10 из 33 сообщений событие датировано одним днём, а
    # опубликовано следующим. Если взять дату события, окно входа откроется
    # на день раньше, чем новость стала публичной, — то есть в основании
    # исследования появится заглядывание вперёд, ровно то, что этап E-1
    # обязан исключить.
    published = published_at(text)
    submission = parse_date(date_body) if date_body else None
    announcement = published or submission

    # Идентификатор — код сообщения самого портала, а не имя файла: имена
    # владелец давал вручную (event_01…event_33) и они ничего не значат за
    # пределами одной папки, а код 3045208 однозначно указывает на сообщение
    # и переживает любое переименование.
    code_m = MESSAGE_CODE_RE.search(text)
    ident = code_m.group(1) if code_m else path.stem
    event_id = f"e1-ix-{ident}"
    doc_id = f"ix-{ident}"

    row = {
        "event_id": event_id,
        "event_type": event_type,
        "issuer": re.sub(r"\s+", " ", issuer).strip(),
        "announcement_date": announcement,
        # Дата, которой датировано само событие: получение эмитентом
        # предложения или требования. Отличается от даты раскрытия на 0-1
        # день и хранится отдельно, чтобы разницу можно было проверить, а не
        # выбирать между двумя датами вслепую.
        "submission_date": submission,
        "isin": isin_m.group(1).replace(" ", "") if isin_m else None,
        "procedure_price": parse_price(price_body) if price_body else None,
        "price_basis": price_basis_of(price_body),
        "guarantor_bank": guarantor,
        "acquirer": acquirer,
        "source_document_refs": [doc_id],
        "provenance": (
            f"e-disclosure.ru message {ident} ({title}); saved as {path.name} by the owner; "
            "issuer/INN/date read from the document itself, not from the search listing"
        ),
    }
    row["pending_fields"] = pending_fields(row, items, event_type)

    # Первая строка — ровно в том формате, который читают
    # scripts/check_tradability.py и scripts/resolve_target_security.py у
    # документов АЗИПИ. Так объединённый инвентарь идёт дальше по конвейеру
    # без развилок «а откуда эта строка пришла».
    ru_date = f"{announcement[8:]}.{announcement[5:7]}.{announcement[:4]}" if announcement else "??"
    document = f"{row['issuer']} (ИНН: {inn.group(1)}) / {title} - {ru_date}\n{text}\n"

    meta = {
        "doc_id": doc_id,
        "event_id": event_id,
        "url": page_url(path),
        "source_type": SOURCE_TYPE,
        # Штамп публикации портала. Именно его читает проверка утечки в
        # scripts/validate_e1_inventory.py: классификация вправе ссылаться
        # только на документы, опубликованные не позже даты события.
        "published_at": announcement,
        "retrieved_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "sha256": hashlib.sha256(document.encode("utf-8")).hexdigest(),
        "legal_use_status": "attribution_required",
        "local_filename": f"{doc_id}.txt",
    }
    return row, document, meta


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--events", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument(
        "--documents",
        type=Path,
        required=True,
        help="куда положить текст документа: <documents>/<event_id>/<doc_id>.txt",
    )
    args = ap.parse_args()

    files = sorted(
        p for p in args.events.rglob("*") if p.suffix.lower() in {".webarchive", ".html"}
    )
    built = [(p, build(p)) for p in files]
    unread = [p.name for p, r in built if r is None]
    rows = []
    for _p, result in built:
        if result is None:
            continue
        row, document, meta = result
        rows.append(row)
        folder = args.documents / row["event_id"]
        folder.mkdir(parents=True, exist_ok=True)
        (folder / meta["local_filename"]).write_text(document, encoding="utf-8")
        (folder / f"{meta['doc_id']}.meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        "\n".join(
            json.dumps(r, ensure_ascii=False)
            for r in sorted(rows, key=lambda r: (r["event_type"], r["announcement_date"] or ""))
        )
        + ("\n" if rows else ""),
        encoding="utf-8",
    )
    filled = {
        f: sum(1 for r in rows if r.get(f))
        for f in (
            "announcement_date",
            "isin",
            "procedure_price",
            "price_basis",
            "guarantor_bank",
            "acquirer",
        )
    }
    print(f"файлов:   {len(files)}")
    print(f"разобрано: {len(rows)}")
    for f, c in filled.items():
        print(f"  {f:18} {c}/{len(rows)}")
    if unread:
        print(f"не прочитано ({len(unread)}): {', '.join(unread)}")
    print(f"записано -> {args.out}, документы -> {args.documents}")
    return 0 if rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
