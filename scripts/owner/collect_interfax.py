#!/usr/bin/env python3
"""Собрать архив сообщений e-disclosure.ru по семейству E-1. ЗАПУСКАТЬ НА СВОЕЙ МАШИНЕ.

Одна команда, без предварительных шагов:

    python scripts/owner/collect_interfax.py

Скрипт сам доставит playwright и chromium, если их нет, откроет видимое окно
браузера, найдёт на странице поиска нужные галочки и поля дат, и постранично
сохранит выдачу за 2019-2025 в stage-E-1/documents/interfax/.

Почему на твоей машине, а не в облачной сессии: e-disclosure.ru отвечает
песочнице проекта JS-заглушкой антибота вместо данных. Проверка рассчитана на
человека с браузером, и обычный браузер проходит её штатно. Здесь ничего не
подделывается и не обходится: Playwright запускает настоящий Chromium, который
выполняет JS страницы ровно так, как задумал сайт.

Интерфакс обслуживает ~90% листингованных эмитентов - именно ту часть рынка,
которой нет в собранном инвентаре (91% его эмитентов не торгуется на бирже).

Прерывать можно в любой момент: уже проиндексированные сообщения при следующем
запуске пропускаются.

Паузы между запросами стоят намеренно. Это инфраструктура раскрытия, которой
пользуются другие люди; вся работа - несколько тысяч загрузок страниц за вечер,
а не гонка. Пожалуйста, не уменьшай их.

Селекторы формы не проверялись на живой странице (из песочницы она не
открывается), поэтому скрипт не полагается на конкретные имена полей, а ищет
элементы по смыслу: галочки - по тексту рядом с ними, даты - по формату, кнопку
- по надписи. Если что-то всё же не нашлось, он сохранит скриншот и HTML
страницы и назовёт файлы - пришли их, и я поправлю поиск.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

SEARCH_URL = "https://www.e-disclosure.ru/poisk-po-soobshheniyam"

# Нумерация Банка России, одинаковая у всех аккредитованных агентств.
# Ключ - код, значение - как отличить нужную галочку по тексту рядом с ней.
MESSAGE_TYPES: dict[int, re.Pattern[str]] = {
    181: re.compile(r"добровольн\w*\s+предложени", re.IGNORECASE),
    182: re.compile(r"обязательн\w*\s+предложени", re.IGNORECASE),
    184: re.compile(r"уведомлени\w*\s+о\s+прав\w*\s+требовать\s+выкупа", re.IGNORECASE),
    # 185 тоже про "требование о выкупе", но без слова "уведомление" -
    # иначе он поймает галочку 184.
    185: re.compile(r"(?!.*уведомлени)требовани\w*\s+о\s+выкупе\s+эмиссионн", re.IGNORECASE),
}
FIRST_YEAR, LAST_YEAR = 2019, 2025

PAGE_PAUSE_SECONDS = 3.0
YEAR_PAUSE_SECONDS = 10.0
MAX_PAGES_PER_YEAR = 500
NAV_TIMEOUT_MS = 120_000

NEXT_PAGE_RE = re.compile(r"^\s*(следующая|далее|вперед|вперёд|»|>>|>)\s*$", re.IGNORECASE)
SUBMIT_RE = re.compile(r"(найти|искать|поиск|показать|применить)", re.IGNORECASE)
EVENT_LINK_RE = re.compile(
    r'href="([^"]*event\.aspx\?EventId=(\d+)[^"]*)"[^>]*>(.*?)</a>', re.DOTALL
)


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def ensure_playwright() -> None:
    """Доставить playwright и chromium, если их нет. Один раз на машину."""
    try:
        import playwright  # noqa: F401
    except ImportError:
        log("playwright не найден, ставлю (один раз)...")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet", "playwright"], check=True
        )
    try:
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as error:
        log(f"не удалось доставить chromium: {error}")
        raise


def stamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def save_debug(page, out_dir: Path, tag: str) -> tuple[Path, Path]:
    """Сохранить, что браузер видит сейчас — это единственное, что мне нужно для починки."""
    out_dir.mkdir(parents=True, exist_ok=True)
    shot, html = out_dir / f"debug_{tag}.png", out_dir / f"debug_{tag}.html"
    try:
        page.screenshot(path=str(shot), full_page=True)
        html.write_text(page.content(), encoding="utf-8")
    except Exception as error:  # noqa: BLE001 - диагностика не должна ронять сбор
        log(f"  не удалось сохранить диагностику: {error}")
    return shot, html


def check_message_types(page) -> list[int]:
    """Отметить четыре галочки. Сначала по value, потом по тексту рядом."""
    checked: list[int] = []
    for code, label_re in MESSAGE_TYPES.items():
        box = page.locator(f'input[type="checkbox"][value="{code}"]')
        if box.count() == 0:
            box = page.locator('input[type="checkbox"]').filter(has_text=label_re)
        if box.count() == 0:
            # Текст обычно не внутри input, а в соседнем label — идём от него.
            label = page.locator("label").filter(has_text=label_re)
            if label.count():
                try:
                    label.first.click(timeout=10_000)
                    checked.append(code)
                    continue
                except Exception:  # noqa: BLE001,S110 - клик мимо, пробуем следующий
                    pass
            continue
        try:
            box.first.check(timeout=10_000)
            checked.append(code)
        except Exception as error:  # noqa: BLE001 - пробуем следующий код
            log(f"  галочка {code} не отметилась: {str(error).splitlines()[0][:80]}")
    return checked


def fill_dates(page, start: str, finish: str) -> bool:
    """Найти два поля дат по имени/подсказке и заполнить их."""
    candidates = page.locator(
        'input[name*="date" i], input[id*="date" i], input[placeholder*="."], input[type="date"]'
    )
    filled = 0
    for index in range(min(candidates.count(), 8)):
        field = candidates.nth(index)
        try:
            if field.is_visible():
                field.fill(start if filled == 0 else finish, timeout=10_000)
                filled += 1
        except Exception:  # noqa: BLE001,S112 - поле не то, пробуем следующее
            continue
        if filled == 2:
            return True
    return False


def submit(page) -> None:
    button = page.get_by_role("button", name=SUBMIT_RE)
    if button.count() == 0:
        button = page.locator('input[type="submit"], button[type="submit"]')
    button.first.click(timeout=15_000)
    page.wait_for_load_state("networkidle", timeout=NAV_TIMEOUT_MS)
    page.wait_for_timeout(3_000)


def next_page(page) -> bool:
    link = page.get_by_role("link", name=NEXT_PAGE_RE)
    if link.count() == 0 or not link.first.is_visible():
        return False
    link.first.click(timeout=15_000)
    page.wait_for_load_state("networkidle", timeout=NAV_TIMEOUT_MS)
    page.wait_for_timeout(2_000)
    return True


def parse_results(html: str) -> list[dict[str, str]]:
    rows = []
    for href, event_id, inner in EVENT_LINK_RE.findall(html):
        title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", inner)).strip()
        rows.append({"event_id": event_id, "title": title, "href": href})
    return rows


def collect(out_dir: Path, years: list[int], push: bool) -> int:
    ensure_playwright()
    from playwright.sync_api import sync_playwright

    pages_dir = out_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    index_path = out_dir / "messages.jsonl"

    seen: set[str] = set()
    if index_path.is_file():
        for line in index_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                seen.add(json.loads(line)["event_id"])
        log(f"продолжаю: уже собрано {len(seen)} сообщений")

    total_new = 0
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        page = browser.new_page()

        for year in years:
            log(f"=== {year}")
            page.goto(SEARCH_URL, wait_until="networkidle", timeout=NAV_TIMEOUT_MS)
            page.wait_for_timeout(5_000)

            checked = check_message_types(page)
            if len(checked) < len(MESSAGE_TYPES):
                missing = sorted(set(MESSAGE_TYPES) - set(checked))
                shot, html = save_debug(page, out_dir, f"types_{year}")
                log(
                    f"не нашёл галочки для кодов {missing}.\n"
                    f"Пришли мне {shot.name} и {html.name} из {out_dir} — поправлю поиск."
                )
                browser.close()
                return 1

            if not fill_dates(page, f"01.01.{year}", f"31.12.{year}"):
                shot, html = save_debug(page, out_dir, f"dates_{year}")
                log(
                    f"не нашёл поля дат.\n"
                    f"Пришли мне {shot.name} и {html.name} из {out_dir} — поправлю поиск."
                )
                browser.close()
                return 1

            try:
                submit(page)
            except Exception as error:  # noqa: BLE001 - отчитаться, не гадать
                shot, html = save_debug(page, out_dir, f"submit_{year}")
                log(
                    f"не нашёл кнопку поиска: {str(error).splitlines()[0][:80]}\n"
                    f"Пришли мне {shot.name} и {html.name} из {out_dir}."
                )
                browser.close()
                return 1

            for page_number in range(1, MAX_PAGES_PER_YEAR + 1):
                html = page.content()
                (pages_dir / f"{year}_p{page_number:03d}.html").write_text(html, encoding="utf-8")
                new_here = 0
                with index_path.open("a", encoding="utf-8") as handle:
                    for row in parse_results(html):
                        if row["event_id"] in seen:
                            continue
                        seen.add(row["event_id"])
                        new_here += 1
                        handle.write(
                            json.dumps(
                                {
                                    **row,
                                    "year_searched": year,
                                    "url": "https://www.e-disclosure.ru/portal/"
                                    f"event.aspx?EventId={row['event_id']}",
                                    "retrieved_at": stamp(),
                                },
                                ensure_ascii=False,
                            )
                            + "\n"
                        )
                total_new += new_here
                log(f"  стр. {page_number}: +{new_here} (всего {len(seen)})")
                time.sleep(PAGE_PAUSE_SECONDS)
                if not next_page(page):
                    break
            time.sleep(YEAR_PAUSE_SECONDS)
        browser.close()

    log(f"\nготово: {len(seen)} сообщений ({total_new} новых) -> {index_path}")
    log(f"страницы выдачи -> {pages_dir}")
    if push:
        return git_push(out_dir)
    log("\nчтобы передать мне результат:")
    log(f"  git add {out_dir} && git commit -m 'owner: Interfax archive' && git push")
    return 0


def git_push(out_dir: Path) -> int:
    branch = "claude/new-project-spec-wx4utz"
    for command in (
        ["git", "add", str(out_dir)],
        ["git", "commit", "-m", "owner: Interfax message archive 2019-2025"],
        ["git", "push", "-u", "origin", branch],
    ):
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0 and "nothing to commit" not in result.stdout:
            log(f"{' '.join(command)} -> {result.stderr.strip()[:200]}")
            return 1
    log(f"запушено в {branch}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=Path("stage-E-1/documents/interfax"))
    parser.add_argument(
        "--years", type=int, nargs="*", default=list(range(FIRST_YEAR, LAST_YEAR + 1))
    )
    parser.add_argument(
        "--push", action="store_true", help="закоммитить и запушить результат самому"
    )
    args = parser.parse_args()
    return collect(args.out_dir, args.years, args.push)


if __name__ == "__main__":
    raise SystemExit(main())
