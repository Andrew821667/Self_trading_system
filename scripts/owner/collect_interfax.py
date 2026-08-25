#!/usr/bin/env python3
"""Записать архив сообщений e-disclosure.ru по семейству E-1. ЗАПУСКАТЬ НА СВОЕЙ МАШИНЕ.

    python scripts/owner/collect_interfax.py

Открывается окно браузера. **Ведёшь ты, скрипт только записывает.** Он ничего
не нажимает на сайте: ты проходишь проверку, сам настраиваешь поиск и сам
листаешь страницы, а он забирает каждую открывшуюся страницу выдачи и копит
сообщения в один файл.

## Почему именно так

Предыдущая версия сама заполняла форму, и это оказалось тупиком: сайт
распознаёт автоматизированный браузер и отвечает капчей — «Ваше поведение
похоже на поведение автоматизированных систем», с головоломкой на поворот
картинки. Никакая правка селекторов этого не меняет.

Решать капчу программно здесь ничего не будет. Проверку проходит человек —
то есть ты, руками, один раз за сессию. Дальше ты просто листаешь выдачу в
своём темпе, а скрипт снимает то, что уже открыто у тебя на экране. Никаких
запросов к сайту он не делает вообще: весь трафик порождают твои клики.

Профиль браузера сохраняется в `.interfax-profile/`, поэтому пройденную
проверку не придётся повторять при каждом запуске.

## Что нужно набрать в поиске

Четыре типа сообщений (это нумерация Банка России):

    181  Поступление эмитенту добровольного предложения о приобретении
         его эмиссионных ценных бумаг
    182  Поступление эмитенту обязательного предложения о приобретении
         его эмиссионных ценных бумаг
    184  Поступление эмитенту уведомления о праве требовать выкупа
         эмиссионных ценных бумаг эмитента
    185  Поступление эмитенту требования о выкупе эмиссионных ценных
         бумаг эмитента

Даты — по одному году за раз, 01.01.2019–31.12.2019 и так далее до 2025:
у выдачи бывает потолок по числу результатов, и год за раз его обходит.

Порядок и повторные запуски значения не имеют: сообщения складываются в один
файл и не дублируются. Прерывать можно когда угодно — Ctrl+C или просто
закрыть окно браузера.
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
POLL_SECONDS = 2.0
EVENT_LINK_RE = re.compile(
    r'href="([^"]*event\.aspx\?EventId=(\d+)[^"]*)"[^>]*>(.*?)</a>', re.DOTALL
)
BRANCH = "claude/new-project-spec-wx4utz"


def log(message: str = "") -> None:
    print(message, file=sys.stderr, flush=True)


def ensure_playwright() -> None:
    try:
        import playwright  # noqa: F401
    except ImportError:
        log("playwright не найден, ставлю (один раз)...")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet", "playwright"], check=True
        )
    subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        check=True,
        capture_output=True,
    )


def parse_results(html: str) -> list[dict[str, str]]:
    rows = []
    for href, event_id, inner in EVENT_LINK_RE.findall(html):
        title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", inner)).strip()
        rows.append({"event_id": event_id, "title": title, "href": href})
    return rows


def load_seen(index_path: Path) -> set[str]:
    if not index_path.is_file():
        return set()
    return {
        json.loads(line)["event_id"]
        for line in index_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def instructions() -> None:
    log("=" * 70)
    log("Окно браузера открыто. Скрипт на сайте НИЧЕГО не нажимает — ведёшь ты.")
    log("")
    log("  1. Пройди проверку «вы не бот», если она появилась.")
    log("  2. Отметь четыре типа сообщений:")
    log("       181  ...добровольного предложения о приобретении...")
    log("       182  ...обязательного предложения о приобретении...")
    log("       184  ...уведомления о праве требовать выкупа...")
    log("       185  ...требования о выкупе эмиссионных ценных бумаг...")
    log("  3. Поставь даты за ОДИН год (01.01.2019 – 31.12.2019) и найди.")
    log("  4. Листай страницы выдачи. Каждую я записываю сам.")
    log("  5. Кончился год — поменяй даты на следующий. И так до 2025.")
    log("")
    log("Закончил — Ctrl+C здесь или просто закрой окно браузера.")
    log("=" * 70)
    log("")


def record(out_dir: Path, push: bool) -> int:
    ensure_playwright()
    from playwright.sync_api import sync_playwright

    pages_dir = out_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    index_path = out_dir / "messages.jsonl"
    profile_dir = Path(".interfax-profile").absolute()

    seen = load_seen(index_path)
    if seen:
        log(f"продолжаю: уже записано {len(seen)} сообщений")

    captured_pages = len(list(pages_dir.glob("*.html")))
    last_fingerprint = ""

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(profile_dir), headless=False, viewport={"width": 1400, "height": 950}
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=120_000)
        instructions()

        try:
            while True:
                time.sleep(POLL_SECONDS)
                try:
                    html = page.content()
                except Exception:  # noqa: BLE001 - страница грузится или окно закрыто
                    if not context.pages:
                        break
                    continue

                rows = parse_results(html)
                if not rows:
                    continue
                fingerprint = ",".join(row["event_id"] for row in rows)
                if fingerprint == last_fingerprint:
                    continue
                last_fingerprint = fingerprint

                new_rows = [row for row in rows if row["event_id"] not in seen]
                captured_pages += 1
                (pages_dir / f"page_{captured_pages:04d}.html").write_text(html, encoding="utf-8")
                with index_path.open("a", encoding="utf-8") as handle:
                    for row in new_rows:
                        seen.add(row["event_id"])
                        handle.write(
                            json.dumps(
                                {
                                    **row,
                                    "url": "https://www.e-disclosure.ru/portal/"
                                    f"event.aspx?EventId={row['event_id']}",
                                    "retrieved_at": datetime.now(UTC).isoformat(timespec="seconds"),
                                },
                                ensure_ascii=False,
                            )
                            + "\n"
                        )
                log(f"  страница {captured_pages}: +{len(new_rows)} (всего {len(seen)})")
        except KeyboardInterrupt:
            log("\nостановлено")
        finally:
            try:
                context.close()
            except Exception:  # noqa: BLE001,S110 - окно могли уже закрыть
                pass

    log(f"\nзаписано {len(seen)} сообщений -> {index_path}")
    log(f"страницы выдачи -> {pages_dir}")
    if not seen:
        log("\nничего не записалось: страницы выдачи так и не открылись.")
        return 1
    if push:
        return git_push(out_dir)
    log("\nпередать мне результат:")
    log(f"  git add {out_dir} && git commit -m 'owner: Interfax archive' && git push")
    return 0


def git_push(out_dir: Path) -> int:
    for command in (
        ["git", "add", str(out_dir)],
        ["git", "commit", "-m", "owner: Interfax message archive"],
        ["git", "push", "-u", "origin", BRANCH],
    ):
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0 and "nothing to commit" not in result.stdout:
            log(f"{' '.join(command)} -> {result.stderr.strip()[:200]}")
            return 1
    log(f"запушено в {BRANCH}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=Path("stage-E-1/documents/interfax"))
    parser.add_argument("--push", action="store_true", help="сразу закоммитить и запушить")
    args = parser.parse_args()
    return record(args.out_dir, args.push)


if __name__ == "__main__":
    raise SystemExit(main())
