"""Разбор архива рассылок.

У iskconconnection.org новостей своих нет: каждый выпуск рассылки — это
подборка ссылок на чужие сайты, в основном на dandavats.com и iskconnews.org.
Поэтому статьёй считаем не выпуск целиком, а каждую новость, на которую он
ссылается, и берём её по родному адресу.

Из этого следует и главное свойство источника: почти всё, что он приносит,
уже пришло из dandavats и iskconnews напрямую. Совпадения ловятся по адресу
и попадают в article_mentions — так видно, что новость прошла по нескольким
источникам, а не дублируется в ленте.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from app.parsers.fetch import FetchError, fetch_html

log = logging.getLogger(__name__)

# Сколько выпусков разбираем за один заход: они еженедельные, и лезть
# в двухлетнюю глубину при каждом обходе незачем
DEFAULT_ISSUES = 4

# «IC Newsletter Vol.11, Issue 30, 26. July 2026»
ISSUE_DATE_RE = re.compile(r"(\d{1,2})\.\s*([A-Z][a-z]+)\s+(20\d\d)")
MONTHS = {
    name: number
    for number, name in enumerate(
        [
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December",
        ],
        1,
    )
}

# Хосты, ссылки на которые новостями не являются
SKIP_HOSTS = {
    "facebook.com", "x.com", "twitter.com", "instagram.com", "youtube.com",
    "youtu.be", "whatsapp.com", "chat.whatsapp.com", "t.me", "telegram.me",
    "zeffy.com", "paypal.com", "eventbrite.com", "linkedin.com",
}

# Служебные ссылки самой рассылки
SKIP_TEXT_RE = re.compile(
    r"^(unsubscribe|подписаться|subscribe|view (this )?email|forward|donate|"
    r"click here|read more|here|more|sign up|contact us|home)\b",
    re.I,
)

# Слишком короткий текст ссылки — это не заголовок новости
MIN_TITLE_CHARS = 20


@dataclass
class Issue:
    url: str
    title: str
    published_at: datetime | None


@dataclass
class DigestItem:
    url: str
    title: str
    published_at: datetime | None  # дата выпуска: у самой новости её тут нет


def _issue_date(label: str) -> datetime | None:
    match = ISSUE_DATE_RE.search(label)
    if not match:
        return None
    day, month_name, year = match.groups()
    month = MONTHS.get(month_name)
    if not month:
        return None
    try:
        return datetime(int(year), month, int(day), tzinfo=timezone.utc)
    except ValueError:
        return None


def parse_issues(html: str, base_url: str) -> list[Issue]:
    """Выпуски рассылки со страницы архива, свежие первыми."""
    soup = BeautifulSoup(html, "html.parser")
    issues: list[Issue] = []
    seen: set[str] = set()

    for link in soup.select("a[href]"):
        href = link["href"]
        # Выпуск живёт в CiviCRM: /civicrm/mailing/view?id=...
        if "civicrm/mailing/view" not in href:
            continue
        url = urljoin(base_url, href)
        if url in seen:
            continue
        seen.add(url)

        label = link.get_text(" ", strip=True)
        issues.append(Issue(url=url, title=label, published_at=_issue_date(label)))

    # Порядок на странице — от свежих к старым, но полагаться на него не будем
    issues.sort(key=lambda i: (i.published_at is not None, i.published_at), reverse=True)
    return issues


def _is_news_link(url: str, base_host: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False

    host = parsed.netloc.lower().removeprefix("www.")
    if host in SKIP_HOSTS or any(host.endswith("." + h) for h in SKIP_HOSTS):
        return False
    # Ссылки на сам сайт рассылки — это её служебные страницы
    if host == base_host.lower().removeprefix("www."):
        return False
    # Голый домен без страницы — это не новость, а сайт организации
    return bool(parsed.path.strip("/")) or bool(parsed.query)


def parse_items(html: str, issue: Issue, base_url: str) -> list[DigestItem]:
    """Новости, на которые ссылается выпуск."""
    soup = BeautifulSoup(html, "html.parser")
    base_host = urlparse(base_url).netloc

    items: list[DigestItem] = []
    seen: set[str] = set()

    for link in soup.select("a[href]"):
        url = urljoin(issue.url, link["href"])
        title = link.get_text(" ", strip=True)

        if len(title) < MIN_TITLE_CHARS or SKIP_TEXT_RE.match(title):
            continue
        if not _is_news_link(url, base_host):
            continue
        if url in seen:
            continue
        seen.add(url)

        items.append(DigestItem(url=url, title=title, published_at=issue.published_at))

    return items


async def collect_posts(
    base_url: str, *, issues_back: int = DEFAULT_ISSUES, limit: int = 120
) -> list[DigestItem]:
    """Новости из нескольких последних выпусков рассылки."""
    try:
        html = await fetch_html(base_url)
    except FetchError as exc:
        raise FetchError(f"Архив рассылок недоступен: {exc}") from exc

    issues = parse_issues(html, base_url)[:issues_back]
    if not issues:
        raise FetchError("На странице архива не нашлось ни одного выпуска")

    collected: list[DigestItem] = []
    seen: set[str] = set()

    for issue in issues:
        try:
            issue_html = await fetch_html(issue.url)
        except FetchError as exc:
            # Один недоступный выпуск не повод ронять весь обход
            log.warning("выпуск %s не открылся: %s", issue.url, exc)
            continue

        for item in parse_items(issue_html, issue, base_url):
            if item.url in seen:
                continue
            seen.add(item.url)
            collected.append(item)
            if len(collected) >= limit:
                return collected

    return collected
