#!/usr/bin/env python3
"""Разобрать страницы e-disclosure.ru, сохранённые владельцем вручную.

Ничего никуда не ходит: читает `.html`-файлы из папки и строит из них индекс
сообщений. Так и задумано — сайт отказывает автоматизированным браузерам
(капча, затем обрыв соединения), поэтому страницы открывает и сохраняет
человек в своём обычном браузере, а разбор — уже здесь.

    uv run python scripts/parse_saved_interfax.py \\
        --pages stage-E-1/documents/interfax/pages \\
        --out stage-E-1/documents/interfax/messages.jsonl

Годятся страницы двух видов, и различать их не нужно:

* выдача поиска по типам сообщений;
* лента раскрытия конкретного эмитента (`portal/company.aspx?id=...`),
  где так же перечислены сообщения со ссылками.

Дубликаты по `EventId` отбрасываются, так что пересохранять и запускать
повторно безопасно.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path

EVENT_LINK_RE = re.compile(
    r'href="([^"]*event\.aspx\?EventId=(\d+)[^"]*)"[^>]*>(.*?)</a>',
    re.DOTALL | re.IGNORECASE,
)
DATE_RE = re.compile(r"\b(\d{2}\.\d{2}\.\d{4})\b")
# Заголовки сообщений семейства E-1. Коды — нумерация Банка России.
FAMILY_RE = re.compile(
    r"(добровольн\w*\s+предложени|обязательн\w*\s+предложени"
    r"|прав\w*\s+требовать\s+выкупа|требовани\w*\s+о\s+выкупе)",
    re.IGNORECASE,
)


def strip_tags(fragment: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", fragment)).strip()


def rows_from(html: str) -> list[dict[str, str]]:
    """Сообщение + дата из той же строки таблицы, если она там есть."""
    found: list[dict[str, str]] = []
    for match in EVENT_LINK_RE.finditer(html):
        title = strip_tags(match.group(3))
        if not title:
            continue
        # Дата обычно стоит в соседней ячейке — берём ближайшую слева.
        window = html[max(0, match.start() - 400) : match.start()]
        dates = DATE_RE.findall(window)
        found.append(
            {
                "event_id": match.group(2),
                "title": title,
                "published_at": dates[-1] if dates else "",
                "in_e1_family": "yes" if FAMILY_RE.search(title) else "no",
            }
        )
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pages", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    if not args.pages.is_dir():
        raise SystemExit(f"нет папки со страницами: {args.pages}")

    seen: set[str] = set()
    if args.out.is_file():
        seen = {
            json.loads(line)["event_id"]
            for line in args.out.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }

    files = sorted(p for p in args.pages.rglob("*.htm*") if p.is_file())
    added = family = 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("a", encoding="utf-8") as handle:
        for path in files:
            html = path.read_text(encoding="utf-8", errors="replace")
            for row in rows_from(html):
                if row["event_id"] in seen:
                    continue
                seen.add(row["event_id"])
                added += 1
                family += row["in_e1_family"] == "yes"
                handle.write(
                    json.dumps(
                        {
                            **row,
                            "url": "https://www.e-disclosure.ru/portal/"
                            f"event.aspx?EventId={row['event_id']}",
                            "source_file": path.name,
                            "parsed_at": datetime.now(UTC).isoformat(timespec="seconds"),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )

    print(f"страниц прочитано:        {len(files)}")
    print(f"новых сообщений:          {added}")
    print(f"  из них семейства E-1:   {family}")
    print(f"всего в индексе:          {len(seen)}")
    print(f"записано -> {args.out}")
    if not files:
        print("\nв папке нет .html — сохрани страницы браузером (Cmd+S) сюда.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
