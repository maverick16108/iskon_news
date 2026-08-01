"""Разбор помесячного архива сайта.

У dandavats.com RSS отдаёт мешанину: свои посты вперемешку со ссылками на
чужой блогспот, где вместо статьи стоит плеер. Зато на главной есть список
«ARCHIVES» с выбором месяца, и там лежат только собственные публикации.

Адреса месяцев берём из самого списка, а не вычисляем по календарю: когда
начинается новый месяц, он появляется в списке сам, и парсер подхватывает
его без правки настроек.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from app.parsers.fetch import FetchError, fetch_html

log = logging.getLogger(__name__)

# Список месяцев на главной
ARCHIVE_SELECT_NAMES = ("archive-dropdown", "archive-dropdown-2", "cat")

# Дата в карточке: «31 Jul 2026»
DATE_RE = re.compile(r"\b(\d{1,2})\s+([A-Z][a-z]{2})\s+(20\d\d)\b")
MONTHS = {
    m: i
    for i, m in enumerate(
        ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1
    )
}

# Сколько страниц одного месяца обходим максимум
MAX_PAGES = 8


@dataclass
class ArchivePost:
    url: str
    title: str
    published_at: datetime | None


@dataclass
class ArchiveMonth:
    url: str
    label: str


def _is_post_link(href: str, base_host: str) -> bool:
    """Ссылка на публикацию этого же сайта."""
    if urlparse(href).netloc and urlparse(href).netloc.lstrip("www.") != base_host.lstrip("www."):
        return False
    return bool(re.search(r"[?&]p=\d+", href)) or bool(
        re.search(r"/20\d\d/\d\d/[^/]+/?$", urlparse(href).path)
    )


def parse_months(html: str, base_url: str) -> list[ArchiveMonth]:
    """Месяцы из выпадающего списка архива, от свежего к старому."""
    soup = BeautifulSoup(html, "html.parser")

    for select in soup.find_all("select"):
        name = (select.get("name") or select.get("id") or "").lower()
        if name and not any(key in name for key in ARCHIVE_SELECT_NAMES):
            continue

        months: list[ArchiveMonth] = []
        for option in select.find_all("option"):
            value = (option.get("value") or "").strip()
            if not value or value in ("-1", "0"):
                continue
            # В списке лежат либо готовые адреса, либо значения вида 202607
            url = value if value.startswith("http") else urljoin(base_url, f"?m={value}")
            if not re.search(r"[?&]m=\d{6}", url):
                continue
            months.append(ArchiveMonth(url=url, label=option.get_text(strip=True)))

        if months:
            return months

    return []


def _date_near(node: Tag) -> datetime | None:
    """Ищет дату в карточке поста, поднимаясь по родителям."""
    current: Tag | None = node
    for _ in range(4):
        if current is None:
            break
        match = DATE_RE.search(current.get_text(" ", strip=True))
        if match:
            day, mon, year = match.groups()
            month = MONTHS.get(mon)
            if month:
                return datetime(int(year), month, int(day), tzinfo=timezone.utc)
        current = current.parent
    return None


def parse_month_page(html: str, base_url: str) -> list[ArchivePost]:
    """Публикации со страницы месяца."""
    soup = BeautifulSoup(html, "html.parser")
    host = urlparse(base_url).netloc

    posts: dict[str, ArchivePost] = {}
    for link in soup.find_all("a", href=True):
        href = urljoin(base_url, link["href"]).split("#")[0]
        if not _is_post_link(href, host):
            continue

        title = link.get_text(" ", strip=True)
        # На карточке две ссылки: заголовок и «Read more...». Берём ту,
        # у которой текст похож на заголовок.
        if not title or len(title) < 12 or title.lower().startswith("read more"):
            if href in posts:
                continue
            title = ""

        existing = posts.get(href)
        if existing and (not title or len(existing.title) >= len(title)):
            continue

        posts[href] = ArchivePost(url=href, title=title, published_at=_date_near(link))

    return [p for p in posts.values() if p.title]


def has_next_page(html: str, month_url: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    return any("paged=" in (a.get("href") or "") for a in soup.find_all("a", href=True))


async def collect_posts(base_url: str, *, months_back: int = 2, limit: int = 60) -> list[ArchivePost]:
    """Публикации за несколько последних месяцев архива.

    Берём не только текущий месяц: на стыке месяцев материалы за последние
    числа прошлого могут появиться уже после того, как открылся новый.
    """
    home = await fetch_html(base_url)
    months = parse_months(home, base_url)

    if not months:
        raise FetchError("На главной не нашёлся список месяцев архива")

    log.info("Месяцев в архиве: %d, обходим последние %d", len(months), months_back)

    collected: dict[str, ArchivePost] = {}
    for month in months[:months_back]:
        for page in range(1, MAX_PAGES + 1):
            url = month.url if page == 1 else f"{month.url}&paged={page}"
            try:
                html = await fetch_html(url)
            except FetchError as exc:
                log.warning("Страница архива %s недоступна: %s", url, exc)
                break

            found = parse_month_page(html, base_url)
            fresh = [p for p in found if p.url not in collected]
            for post in fresh:
                collected[post.url] = post

            # Ни одной новой ссылки — дальше листать незачем
            if not fresh or not has_next_page(html, month.url):
                break
            if len(collected) >= limit:
                break

        if len(collected) >= limit:
            break

    ordered = sorted(
        collected.values(),
        key=lambda p: p.published_at or datetime(1970, 1, 1, tzinfo=timezone.utc),
        reverse=True,
    )
    return ordered[:limit]
