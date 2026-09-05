#!/usr/bin/env python3
"""Resolve which security an E-1 offer actually concerns (Stage E-1, Phase A).

Why this exists: the issuer that *files* a disclosure message is not always
the company whose shares are being bought. Two real cases from the collected
set — PAO "Kvadra" filed an offer for shares of PAO "TGK-14" at 0.00289 ₽,
and PAO "EL5-Energo" filed one for shares of AO "HOLDING ERSO" at 613 ₽.
Matching a filer's INN to a MOEX security therefore picks the wrong
instrument, and every price/return computed from it would be nonsense.

The offer's own price clause names the target company, so the target is read
from the document text and matched against MOEX by normalised name. Every
match is then sanity-checked against the market price around the
announcement: an offer price implying a ratio far outside 1 is evidence the
match or the extraction is wrong, and the row is rejected rather than
quietly used.

Blind-protocol note: the market data requested here is the close *on or
before* the announcement date only. Nothing after the event is read, so this
reveals no outcome (see stage-E-1/README.md).
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import socket
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

socket.setdefaulttimeout(60)

ISS_HISTORY = (
    "https://iss.moex.com/iss/history/engines/stock/markets/shares/securities/{secid}.json"
    "?iss.meta=off&from={start}&till={end}&limit=100"
)
ISS_SEARCH = "https://iss.moex.com/iss/securities.json?q={query}&iss.meta=off"
REQUEST_DELAY_SECONDS = 0.3
MAX_ATTEMPTS = 3

# A procedure price this far from the market price means the security match or
# the extraction is wrong. Offers do trade at a premium or discount, but not
# by an order of magnitude.
MIN_PLAUSIBLE_RATIO = 0.2
MAX_PLAUSIBLE_RATIO = 5.0

# Формулировок пункта о цене несколько, и по одной подстроке "цена приобрет"
# выпадали ВСЕ требования о выкупе: у них написано "цена выкупаемых ценных
# бумаг". Шестнадцать торгуемых событий не попадали в этот файл вовсе —
# молча, потому что событие без пункта о цене просто пропускалось. Набор
# подсказок теперь тот же, что у разборов инвентаря.
PRICE_HINTS = (
    "цена выкупаемых",
    "цена приобретаемых",
    "цена приобретения",
    "цена приобрет",
    "предлагаемая цена",
)
# "0,00289 рублей" — kopeck-fraction prices are real in this family, so the
# decimal tail must not be capped at two digits.
# The target is named right after the price: "за одну обыкновенную акцию X".
_TARGET_RE = re.compile(
    r"(?:за\s+(?:1|одну)\s*\(?[^)]*\)?\s*(?:обыкновенн|привилегированн)[^\s]*\s+"
    r"(?:именн[^\s]*\s+)?(?:бездокументарн[^\s]*\s+)?акци[юий]\s*)"
    r"((?:ПАО|АО|ОАО|ЗАО|Публичное акционерное общество|Акционерное общество)"
    r"[^.,;\n]{2,70})",
    re.IGNORECASE,
)
_QUOTED_RE = re.compile(r"[\"«]([^\"»]{2,60})[\"»]")
_TITLE_INN_RE = re.compile(r"^.+?\(ИНН:\s*(\d+)\)\s*/")


def normalise(name: str) -> str:
    """Comparable form: quoted core if present, letters and digits only."""
    quoted = _QUOTED_RE.search(name)
    core = quoted.group(1) if quoted else name
    return re.sub(r"[^0-9а-яёa-z]", "", core.lower())


def fetch_json(url: str) -> dict | None:
    for attempt in range(MAX_ATTEMPTS):
        try:
            with urllib.request.urlopen(url) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as error:  # noqa: BLE001 - retried, then skipped
            if attempt == MAX_ATTEMPTS - 1:
                print(f"    ISS failed: {error}", file=sys.stderr)
            time.sleep(2 ** (attempt + 1))
    return None


_ALIASES: dict[str, list[str]] = {}


def aliases(regnumber: str) -> list[str]:
    """Тикеры, под которыми торговался один и тот же выпуск.

    Тикер меняется при переименовании эмитента, а история остаётся под
    старым: выпуск 1-01-50077-A торговался как OGKE («Энел Россия»), потом
    ENRU, и только с 29.03.2023 — как ELFV. Справочник MOEX отдаёт по ИНН
    текущий тикер, у которого истории на дату события 09.01.2023 нет вовсе,
    и событие молча выпадало из выборки как «нет рыночных данных». Между тем
    данные есть — под другим именем той же бумаги.

    Ключ поиска — государственный регистрационный номер выпуска: он у бумаги
    один на всю жизнь, в отличие от тикера.
    """
    if regnumber in _ALIASES:
        return _ALIASES[regnumber]
    payload = fetch_json(ISS_SEARCH.format(query=urllib.parse.quote(regnumber)))
    time.sleep(REQUEST_DELAY_SECONDS)
    found: list[str] = []
    if payload:
        block = payload.get("securities", {})
        for row in block.get("data", []):
            item = dict(zip(block["columns"], row, strict=True))
            if item.get("regnumber") == regnumber and item.get("secid"):
                found.append(str(item["secid"]))
    _ALIASES[regnumber] = found
    return found


def close_before(secid: str, day: date) -> tuple[float | None, str]:
    """(последняя цена закрытия до даты события, что именно выяснилось).

    Три исхода различаются намеренно. «Торговых дней не было ни одного» и
    «торговые дни были, но сделок в них не было» — не одно и то же: первое
    означает, что мы смотрим не туда (переименование, другой рынок), второе
    само по себе ответ на признак Д-7 чек-листа (ликвидность не пропускает
    позицию). У Косогорского завода перед предложением 29.10.2021 в
    справочнике 23 торговых дня подряд с VOLUME=0 — позицию там не собрать
    ни за какие деньги, и это факт о событии, а не пробел в данных.
    """
    payload = fetch_json(
        ISS_HISTORY.format(
            secid=secid, start=(day - timedelta(days=30)).isoformat(), end=day.isoformat()
        )
    )
    time.sleep(REQUEST_DELAY_SECONDS)
    if not payload:
        return None, "iss_unavailable"
    block = payload.get("history", {})
    bars = [dict(zip(block["columns"], row, strict=True)) for row in block.get("data", [])]
    if not bars:
        return None, "no_history_rows"
    closes = [bar["CLOSE"] for bar in bars if bar.get("CLOSE")]
    if not closes:
        return None, "no_trades_in_window"
    return float(closes[-1]), "ok"


def price_clause(text: str) -> str | None:
    for line in text.splitlines():
        lowered = line.lower()
        if any(hint in lowered for hint in PRICE_HINTS) and re.search(r"\d", line):
            return re.sub(r"\s+", " ", line).strip()
    return None


def document_inn(text: str) -> str | None:
    """ИНН эмитента из первой строки документа — как в check_tradability.py."""
    first_line = text.splitlines()[0].strip() if text.strip() else ""
    match = _TITLE_INN_RE.match(first_line)
    return match.group(1) if match else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--documents", type=Path, required=True)
    parser.add_argument("--moex", type=Path, required=True, help="cached MOEX securities json")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    securities = json.loads(args.moex.read_text(encoding="utf-8"))
    by_name: dict[str, list[dict]] = {}
    by_inn: dict[str, list[dict]] = {}
    for security in securities:
        for field in ("emitent_title", "name", "shortname"):
            key = normalise(str(security.get(field) or ""))
            if key:
                by_name.setdefault(key, []).append(security)
        inn = str(security.get("emitent_inn") or "").strip()
        if inn:
            by_inn.setdefault(inn, []).append(security)

    events = [
        json.loads(line)
        for line in args.inventory.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    results: list[dict] = []
    for event in events:
        doc_id = event["source_document_refs"][0]
        text_path = args.documents / event["event_id"] / f"{doc_id}.txt"
        if not text_path.is_file():
            continue
        text = text_path.read_text(encoding="utf-8")
        clause = price_clause(text)

        # Цена берётся из инвентаря, а не разбирается здесь заново. Раньше
        # этот скрипт читал её своими шаблонами — то есть в проекте жили две
        # независимые реализации разбора цены, и расходились они молча.
        # Разбор 2026-09-05 нашёл в этой семье шаблонов четыре ошибки
        # (удвоение копеек из расшифровки прописью, цена без слова «рубль»,
        # дробная цена, дата прописью); чинить их пришлось бы дважды, а
        # заметить расхождение — никак. Инвентарь — единственный источник
        # цены; здесь остаётся только то, чего в инвентаре нет: какой
        # компании адресовано предложение.
        if not event.get("procedure_price"):
            continue
        price = Decimal(event["procedure_price"])

        # Обычный случай: предложение адресовано акционерам самого подателя,
        # и тогда бумага находится по его ИНН — точное соединение, без
        # подбора по названию. Именно этим занимается check_tradability.py,
        # и расходиться с ним здесь не за чем.
        #
        # Исключение: холдинг раскрывает о дочерней компании, и тогда
        # название цели стоит прямо в пункте о цене («за одну обыкновенную
        # акцию ПАО „Икс“»). Только в этом случае в ход идёт подбор по
        # названию — с оговоркой, что он ненадёжен: «Красный Октябрь» — это
        # и деревообрабатывающий комбинат (ИНН 7204660270), и московская
        # кондитерская фабрика (7706043263), а «Кристалл» — и владикавказский
        # завод (1500000120), и биржевая «Алкогольная группа» (9731121416).
        # Отношение цены к рынку ниже такие подмены и ловит.
        target_match = _TARGET_RE.search(clause) if clause else None
        target_from_document = target_match is not None
        if target_match:
            target_name = re.sub(r"\s+", " ", target_match.group(1)).strip()
            candidates = by_name.get(normalise(target_name), [])
        else:
            target_name = event["issuer"]
            candidates = by_inn.get(document_inn(text) or "", [])
        if not candidates:
            results.append(
                {
                    "event_id": event["event_id"],
                    "announcement_date": event["announcement_date"],
                    "filer": event["issuer"],
                    "target_named_in_document": target_name,
                    "target_source": "document" if target_from_document else "filer_inn",
                    "secid": "",
                    "secid_in_reference_book": "",
                    "procedure_price": str(price),
                    "market_close_before": "",
                    "price_to_market": "",
                    "status": "target_not_listed_on_moex",
                }
            )
            continue

        for security in candidates:
            day = date.fromisoformat(event["announcement_date"])
            used_secid = security["secid"]
            market, why = close_before(used_secid, day)
            # Истории под текущим тикером нет — значит, на дату события бумага
            # звалась иначе. Пробуем остальные тикеры того же выпуска.
            if why == "no_history_rows" and security.get("regnumber"):
                for alias in aliases(str(security["regnumber"])):
                    if alias == used_secid:
                        continue
                    market, why = close_before(alias, day)
                    if why != "no_history_rows":
                        used_secid = alias
                        break

            ratio = float(price) / market if market else None
            if ratio is None:
                # "нет данных" и "торгов не было" различаются: второе — сам по
                # себе ответ про ликвидность, а не пробел в сборе.
                status = (
                    "no_trades_before_event"
                    if why == "no_trades_in_window"
                    else "no_pre_event_market_data"
                )
            elif MIN_PLAUSIBLE_RATIO <= ratio <= MAX_PLAUSIBLE_RATIO:
                status = "ok"
            else:
                status = "implausible_ratio"
            results.append(
                {
                    "event_id": event["event_id"],
                    "announcement_date": event["announcement_date"],
                    "filer": event["issuer"],
                    "target_named_in_document": target_name,
                    "target_source": "document" if target_from_document else "filer_inn",
                    "secid": used_secid,
                    "secid_in_reference_book": security["secid"],
                    "procedure_price": str(price),
                    "market_close_before": market if market else "",
                    "price_to_market": round(ratio, 3) if ratio else "",
                    "status": status,
                }
            )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as handle:
        columns = list({key: None for row in results for key in row})
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(sorted(results, key=lambda r: r["announcement_date"]))

    usable = [r for r in results if r["status"] == "ok"]
    print(f"documents with a readable price clause and a named target: {len(results)}")
    print(f"  target resolved to a MOEX security and price plausible: {len(usable)}")
    print(f"  target not listed on MOEX: {sum(1 for r in results if r['status'] == 'target_not_listed_on_moex')}")
    print(
        f"  implausible price/market ratio: {sum(1 for r in results if r['status'] == 'implausible_ratio')}"
    )
    renamed = sum(1 for r in results if r["secid"] and r["secid"] != r["secid_in_reference_book"])
    print(
        "  no trades at all in the 30 days before the event (a liquidity fact, not a gap): "
        f"{sum(1 for r in results if r['status'] == 'no_trades_before_event')}"
    )
    print(f"  history found under the security's earlier ticker: {renamed}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
