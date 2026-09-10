"""Разбор цены и даты из текстов российских процедурных сообщений.

Единственная реализация на весь проект. До 2026-09-05 их было три —
в `build_e1_inventory.py`, `parse_interfax_events.py` и
`resolve_target_security.py`, — и расходились они молча: каждая читала одну
и ту же строку по-своему, а сверить их между собой было нечем. Так в
инвентаре появились две ошибки, каждая из которых выглядела правдоподобным
числом:

* «0,592 (ноль целых пятьсот девяносто две тысячных) рубля» → **592**.
  Дробная часть в шаблоне была ограничена двумя знаками, поэтому «0,59» не
  подходило под «рубля», зато подходило «592» из середины числа. Ошибка в
  тысячу раз, у ПАО «ТНС энерго Ростов-на-Дону».
* «1,12 рублей (Один рубль 12 копеек)» → **1,24**. Копейки из расшифровки
  прописью прибавлялись к рублям, которые их уже включали.

Обе — не про то, что парсер упал. Он не падал ни разу; он возвращал число,
которое некому было проверить. Поэтому здесь всё покрыто
`tests/test_document_facts.py` на дословных строках из документов.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

# Дробная часть НЕ ограничена двумя знаками: копеечные и долькопеечные цены
# в этой семье процедур обычны — «0,00289 рублей» у ТГК-14 настоящая цена.
_ROUBLES = r"(\d[\d\s  ]*(?:[.,]\d{1,6})?)"
# Копейки пишут двумя способами, и оба встречаются в одном наборе документов:
# "481 (Четыреста восемьдесят один) рубль 68 копеек" и "234 (двести тридцать
# четыре) рубля 75 (семьдесят пять) копеек" — во втором между числом копеек и
# словом стоит расшифровка прописью.
PRICE_RE = re.compile(
    _ROUBLES + r"\s*(?:\([^)]*\))?\s*(?:руб|рубл|₽)"
    r"[^\d]{0,25}(?:(\d{1,2})\s*(?:\([^)]*\))?\s*коп)?",
    re.IGNORECASE,
)
# Цена ниже рубля пишется вообще без рублей: «61 (шестьдесят одна) копейка».
KOPECK_ONLY_RE = re.compile(r"(\d{1,2})\s*(?:\([^)]*\))?\s*копе", re.IGNORECASE)
# «1,89 (один рубль восемьдесят девять копеек)» — слова «рубль» рядом с
# цифрами нет вовсе, оно только внутри расшифровки прописью.
PRICE_PAREN_RE = re.compile(_ROUBLES + r"\s*\([^)]*рубл[^)]*\)", re.IGNORECASE)
# Вытеснение по ст. 84.8 в ПАО МОСОБЛБАНК после санации: цена записана дробью
# «1 / 4 507 984 112 (...доля) рубля за 1 (одну) акцию». Это действительная
# цена околонулевой акции, а не сбой распознавания.
PRICE_FRACTION_RE = re.compile(r"(\d[\d\s ]*)\s*/\s*(\d[\d\s ]*)\s*\([^)]*\)\s*рубл", re.IGNORECASE)

# Цена за акцию выше этой границы для третьего эшелона неправдоподобна и
# означает, что шаблон зацепился за количество бумаг или за сумму сделки.
MAX_PLAUSIBLE_PRICE = Decimal(10_000_000)

DATE_RE = re.compile(r"\b(\d{2})\.(\d{2})\.(\d{4})\b")
# Дату пишут и цифрами, и прописью — «14 декабря 2020 года», «02 июня 2020 г.»
# — причём в одном документе в шапке одно, а в пункте 2.4 другое.
MONTHS = {
    month: number
    for number, month in enumerate(
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

# Формулировки, которыми эмитент объясняет, откуда взялась цена.
PRICE_BASIS_PATTERNS: tuple[tuple[str, str], ...] = (
    ("средневзвешенн", "биржевая средневзвешенная цена"),
    ("оценщик", "рыночная стоимость по отчёту оценщика"),
    ("организатор", "цена по данным организатора торговли"),
    ("наибольш", "наибольшая из предусмотренных законом величин"),
)


def _number(raw: str) -> Decimal | None:
    """Русская запись числа в Decimal: пробелы-разделители, запятая-точка."""
    try:
        return Decimal(re.sub(r"[\s  ]", "", raw).replace(",", "."))
    except InvalidOperation:
        return None


def _within_range(value: Decimal | None) -> str | None:
    if value is None or not (0 < value < MAX_PLAUSIBLE_PRICE):
        return None
    return format(value, "f")


def parse_price(text: str) -> str | None:
    """Цена за одну акцию из текста пункта, или None.

    Порядок веток важен: дробь проверяется первой, иначе её знаменатель
    прочитается как обычная цена в рублях.
    """
    fraction = PRICE_FRACTION_RE.search(text)
    if fraction:
        numerator, denominator = _number(fraction.group(1)), _number(fraction.group(2))
        if numerator is None or not denominator:
            return None
        # Копеечная точность тут бессмысленна, а деление даёт 28 значащих
        # цифр и запись через E, которую ниже по конвейеру никто не ждёт.
        return format((numerator / denominator).quantize(Decimal("1E-10")).normalize(), "f")

    match = PRICE_RE.search(text)
    if match:
        value = _number(match.group(1))
        if value is None:
            return None
        # Копейки прибавляются, только если рубли записаны целым числом.
        # «0,75 рубля (75 копеек)» — одна и та же цена, названная дважды;
        # сложение давало 1,50, то есть ровно вдвое завышало цену выкупа.
        if match.group(2) and value == value.to_integral_value():
            value += Decimal(match.group(2)) / 100
        return _within_range(value)

    parenthesised = PRICE_PAREN_RE.search(text)
    if parenthesised:
        return _within_range(_number(parenthesised.group(1)))

    kopecks = KOPECK_ONLY_RE.search(text)
    if kopecks:
        return _within_range(Decimal(kopecks.group(1)) / 100)
    return None


def parse_date(text: str) -> str | None:
    """ISO-дата: сперва цифрами, затем прописью."""
    digits = DATE_RE.search(text)
    if digits:
        day, month, year = digits.groups()
        return f"{year}-{month}-{day}"
    words = WORD_DATE_RE.search(text)
    if not words:
        return None
    month = MONTHS[next(k for k in MONTHS if words.group(2).lower().startswith(k))]
    return f"{words.group(3)}-{month:02d}-{int(words.group(1)):02d}"


def price_basis_of(clause_text: str | None) -> str | None:
    if not clause_text:
        return None
    lowered = clause_text.lower()
    return next((label for needle, label in PRICE_BASIS_PATTERNS if needle in lowered), None)
