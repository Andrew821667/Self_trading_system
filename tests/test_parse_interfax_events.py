"""Разбор структуры сообщений e-disclosure.ru.

Разбор цены и даты живёт отдельно — см. tests/test_document_facts.py.
Здесь то, что специфично для страниц «Интерфакса»: нумерация пунктов,
семантика pending_fields и штамп публикации.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from parse_interfax_events import clauses, pending_fields, published_at


def test_clauses_split_without_trailing_dot() -> None:
    """Точка после номера пункта ставится не всегда — в одном документе по-разному.

    Раньше требование точки склеивало весь раздел 2 в один пункт, и «дата
    наступления события» отвечала первым, что нашлось после ближайшего
    двоеточия: у Русполимета это была дата госрегистрации выпуска 15.12.2005.
    """
    text = (
        "1.8. Дата наступления события 27.07.2020 "
        "2. Содержание сообщения "
        "2.1 Лицо, направившее предложение: ООО «Мотор-инвест». "
        "2.6 Предлагаемая цена: 61 копейка за 1 акцию."
    )
    assert [num for num, _body in clauses(text)] == ["1.8", "2.1", "2.6"]


def test_clauses_ignore_numbers_that_are_not_clause_marks() -> None:
    """Дата в конце предложения и ссылка на устав — не номера пунктов.

    «27.07.2020. 2.4» содержит «07.2020. », а «п. п. 12.4.2 и 20.1 устава» —
    «20.1 »; обе подстроки внешне неотличимы от номера пункта.
    """
    text = (
        "2.3 Дата получения: 27.07.2020. "
        "2.4 Признаки бумаг: акции обыкновенные. "
        "2.9. В соответствии с п. п. 12.4.2 и 20.1 устава сообщение публикуется."
    )
    assert [num for num, _body in clauses(text)] == ["2.3", "2.4", "2.9"]


def test_pending_marks_unread_facts_not_absent_ones() -> None:
    """pending — «не прочитано», а не «пусто».

    Пункт о цене прочитан целиком, ценовой базы в нём нет — это ответ, а не
    пробел, и `price_basis` в pending не попадает. Прежняя реализация
    помечала pending любое пустое поле, из-за чего к классификации не
    допускалось ни одно событие инвентаря.
    """
    items = clauses(
        "2.6 Предлагаемая цена приобретаемых ценных бумаг: 61 копейка за акцию. "
        "2.8 Полное наименование гаранта, предоставившего банковскую гарантию: ПАО «Сбербанк»."
    )
    row = {
        "procedure_price": "0.61",
        "price_basis": None,
        "guarantor_bank": "ПАО «Сбербанк»",
        "acquirer": None,
    }
    assert pending_fields(row, items, "voluntary_or_mandatory_offer") == ["acquirer"]


def test_pending_flags_a_notice_whose_terms_live_in_an_attachment() -> None:
    """А вот когда пункта о цене нет вовсе, факт действительно не прочитан."""
    items = clauses("2.1 Поступило обязательное предложение. 2.2 Текст предложения — в приложении.")
    row = {"procedure_price": None, "price_basis": None, "guarantor_bank": None, "acquirer": None}
    assert pending_fields(row, items, "voluntary_or_mandatory_offer") == [
        "acquirer",
        "guarantor_bank",
        "price_basis",
        "procedure_price",
    ]


def test_squeeze_out_without_a_guarantee_is_not_pending() -> None:
    """У вытеснения по ст. 84.8 банковская гарантия не требуется по закону.

    Помечать её отсутствие пробелом значило бы дисквалифицировать законную
    процедуру правилом D за неполноту данных, которых там и не должно быть.
    """
    items = clauses("2.6 Цена выкупаемых ценных бумаг: 100 рублей. 2.7 Дата составления списка.")
    row = {
        "procedure_price": "100",
        "price_basis": None,
        "guarantor_bank": None,
        "acquirer": "ООО «Х»",
    }
    assert pending_fields(row, items, "squeeze_out_request_95") == []


def test_published_at_is_the_portal_stamp_not_the_event_date() -> None:
    """`announcement_date` — дата раскрытия; событие датировано днём раньше.

    У 10 сообщений из 33 эти даты расходятся на день. Если брать дату
    события, окно входа открывается раньше, чем новость стала публичной.
    """
    assert (
        published_at("Версия для печати 28.07.2020 08:39 код сообщeния: 3045208 АО") == "2020-07-28"
    )
    assert published_at("сообщение без штампа публикации") is None
