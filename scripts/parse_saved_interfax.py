#!/usr/bin/env python3
"""Разобрать страницы e-disclosure.ru, сохранённые владельцем вручную.

Ничего никуда не ходит: читает файлы из папки и строит из них индекс
сообщений. Так и задумано — сайт отказывает автоматизированным браузерам
(капча, затем обрыв соединения), поэтому страницы открывает и сохраняет
человек в своём обычном браузере, а разбор — уже здесь.

    python scripts/parse_saved_interfax.py \\
        --pages stage-E-1/documents/interfax/pages \\
        --out stage-E-1/documents/interfax/messages.jsonl

## Какой формат сохранять

**Веб-архив (`.webarchive`)**, не «исходный код страницы». Проверено
2026-09-05 на живом сайте: таблица результатов рисуется скриптом уже в
браузере, и в исходном коде от сервера её нет — там только фильтры. Веб-архив
сохраняет отрисованное, поэтому годится. Формат бинарный (Apple plist), но
HTML внутри него читается штатно, без сторонних библиотек.

`.html` тоже принимается — на случай, если страница окажется статической.

## Как извлекаются строки

Сначала по ссылкам на сообщения, если они есть. Если ссылок нет — по тексту:
строка выдачи выглядит как «дата время | эмитент | тип сообщения |
распространитель», и этого достаточно, потому что для инвентаря нужны именно
дата, эмитент и тип.

Если не сработало ни то, ни другое, скрипт пишет рядом файл `_diagnostic.txt`
с образцом содержимого — чтобы поправить разбор по факту, а не гадать.

Дубликаты отбрасываются, так что пересохранять и запускать повторно безопасно.
"""

from __future__ import annotations

import argparse
import html as htmlmod
import json
import plistlib
import re
from datetime import UTC, datetime
from pathlib import Path

# Ссылка на сообщение — форма менялась между версиями сайта, поэтому
# принимаются все известные варианты.
EVENT_LINK_RE = re.compile(
    r'href="([^"]*(?:event\.aspx\?EventId=|/event/|/message/)(\d+)[^"]*)"[^>]*>(.*?)</a>',
    re.DOTALL | re.IGNORECASE,
)
# Строка выдачи в отрисованном виде: дата, время, эмитент, тип, распространитель.
# Распространитель в конце — надёжный ограничитель: он всегда один из немногих.
TEXT_ROW_RE = re.compile(
    r"(?P<date>\d{2}\.\d{2}\.\d{4})\s+(?P<time>\d{2}:\d{2})\s+"
    r"(?P<issuer>.{3,150}?)\s+"
    r"(?P<title>Поступление эмитенту .{10,250}?)\s+"
    r"(?:ИНТЕРФАКС|Прайм|ПРАЙМ|AZIPI|АЗИПИ|СКРИН|СКРИН\b|АК&М|АКМ)",
    re.IGNORECASE,
)
DATE_RE = re.compile(r"\b(\d{2}\.\d{2}\.\d{4})\b")
# Заголовки сообщений семейства E-1. Коды — нумерация Банка России.
FAMILY_RE = re.compile(
    r"(добровольн\w*\s+предложени|обязательн\w*\s+предложени"
    r"|прав\w*\s+требовать\s+выкупа|требовани\w*\s+о\s+выкупе)",
    re.IGNORECASE,
)


def strip_tags(fragment: str) -> str:
    without_scripts = re.sub(
        r"<(script|style)[^>]*>.*?</\1>", " ", fragment, flags=re.DOTALL | re.IGNORECASE
    )
    return re.sub(r"\s+", " ", htmlmod.unescape(re.sub(r"<[^>]+>", " ", without_scripts))).strip()


def read_page(path: Path) -> str:
    """HTML страницы, из `.html` или из Safari-архива `.webarchive`."""
    if path.suffix.lower() != ".webarchive":
        return path.read_text(encoding="utf-8", errors="replace")
    archive = plistlib.loads(path.read_bytes())
    parts: list[str] = []
    main = archive.get("WebMainResource", {})
    data = main.get("WebResourceData")
    if isinstance(data, bytes):
        parts.append(data.decode("utf-8", errors="replace"))
    # Выдача может лежать во фрейме — подресурсы тоже просматриваются.
    for resource in archive.get("WebSubresources", []) or []:
        mime = str(resource.get("WebResourceMIMEType") or "")
        body = resource.get("WebResourceData")
        if "html" in mime.lower() and isinstance(body, bytes):
            parts.append(body.decode("utf-8", errors="replace"))
    return "\n".join(parts)


def rows_from_links(page: str) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    for match in EVENT_LINK_RE.finditer(page):
        title = strip_tags(match.group(3))
        if not title:
            continue
        window = page[max(0, match.start() - 400) : match.start()]
        dates = DATE_RE.findall(strip_tags(window))
        found.append(
            {
                "event_id": match.group(2),
                "issuer": "",
                "title": title,
                "published_at": dates[-1] if dates else "",
                "extracted_by": "link",
            }
        )
    return found


def rows_from_text(page: str) -> list[dict[str, str]]:
    text = strip_tags(page)
    found: list[dict[str, str]] = []
    for match in TEXT_ROW_RE.finditer(text):
        issuer = match.group("issuer").strip(" |·—-")
        title = re.sub(r"\s+", " ", match.group("title")).strip()
        found.append(
            {
                # Ссылки нет — ключ собирается из даты, эмитента и типа.
                "event_id": f"{match.group('date')}|{issuer}|{title[:60]}",
                "issuer": issuer,
                "title": title,
                "published_at": match.group("date"),
                "extracted_by": "text",
            }
        )
    return found


def write_diagnostic(pages: Path, sample_page: str, sample_name: str) -> Path:
    """Образец содержимого — чтобы поправить разбор по факту, а не гадать."""
    text = strip_tags(sample_page)
    hrefs = sorted({m for m in re.findall(r'href="([^"]{1,120})"', sample_page)})
    report = [
        f"файл: {sample_name}",
        f"символов в разметке: {len(sample_page)}",
        f"символов в тексте:   {len(text)}",
        "",
        "=== первые 3000 символов текста страницы ===",
        text[:3000],
        "",
        "=== до 60 разных ссылок ===",
        *hrefs[:60],
    ]
    path = pages / "_diagnostic.txt"
    path.write_text("\n".join(report), encoding="utf-8")
    return path


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

    files = sorted(
        p
        for p in args.pages.rglob("*")
        if p.is_file() and p.suffix.lower() in {".html", ".htm", ".webarchive"}
    )
    added = family = 0
    biggest: tuple[int, str, str] = (0, "", "")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("a", encoding="utf-8") as handle:
        for path in files:
            page = read_page(path)
            if len(page) > biggest[0]:
                biggest = (len(page), page, path.name)
            rows = rows_from_links(page) or rows_from_text(page)
            for row in rows:
                if row["event_id"] in seen:
                    continue
                seen.add(row["event_id"])
                added += 1
                in_family = bool(FAMILY_RE.search(row["title"]))
                family += in_family
                handle.write(
                    json.dumps(
                        {
                            **row,
                            "in_e1_family": "yes" if in_family else "no",
                            "source_file": path.name,
                            "parsed_at": datetime.now(UTC).isoformat(timespec="seconds"),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )

    print(f"файлов прочитано:         {len(files)}")
    print(f"новых сообщений:          {added}")
    print(f"  из них семейства E-1:   {family}")
    print(f"всего в индексе:          {len(seen)}")
    print(f"записано -> {args.out}")
    if not files:
        print("\nв папке нет .webarchive/.html — сохрани страницы браузером сюда.")
        return 1
    if added == 0 and biggest[1]:
        report = write_diagnostic(args.pages, biggest[1], biggest[2])
        print(f"\nни одной строки не распозналось. Образец записан в {report} —")
        print("пришли этот файл, поправлю разбор по факту.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
