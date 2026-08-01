"""Распознавание архивных материалов.

Dandavats регулярно выкладывает записи старых лекций как свежие публикации:
дата страницы — сегодняшняя, а сам материал двух- или трёхлетней давности.
Отличить их можно только по дате внутри заголовка или первой строки текста:

    2023.06.27 – Vastra-harana lila. Lecture 1 (Zurich)
    Nirakula & Jagarini Matajis – CC Reading – 7-31-26
    07.07.26 – SB 7.9.1, Barnaderg, Ireland

Считаем материал архивным, только когда дата в тексте заметно старше даты
публикации. Свежая запись позавчерашней лекции архивом не является.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

# Насколько материал должен отстать от публикации, чтобы считаться архивным.
# Два месяца: запись прошлой недели или прошлого месяца — обычное дело,
# а вот прошлогодняя лекция это уже переиздание.
ARCHIVE_AFTER_DAYS = 60

# Год, раньше которого дат не бывает. Письма Прабхупады датируются
# шестидесятыми-семидесятыми, поэтому граница не в двухтысячных.
MIN_YEAR = 1900

# Месяцы словами: в письмах и лекциях дату пишут именно так —
# «25 March, 1970», «March 25, 1970»
MONTHS = {
    name: number
    for number, names in enumerate(
        [
            ("january", "jan"), ("february", "feb"), ("march", "mar"),
            ("april", "apr"), ("may",), ("june", "jun"),
            ("july", "jul"), ("august", "aug"), ("september", "sep", "sept"),
            ("october", "oct"), ("november", "nov"), ("december", "dec"),
        ],
        1,
    )
    for name in names
}

_MONTH_RE = "|".join(sorted(MONTHS, key=len, reverse=True))

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # 25 March, 1970
    (re.compile(rf"\b(\d{{1,2}})\s+({_MONTH_RE})\.?,?\s+(20\d\d|19\d\d)\b", re.I), "dMy"),
    # March 25, 1970
    (re.compile(rf"\b({_MONTH_RE})\.?\s+(\d{{1,2}}),?\s+(20\d\d|19\d\d)\b", re.I), "Mdy"),
    # 2023.06.27 или 2023-06-27
    (re.compile(r"\b(20\d\d)[.\-/](\d{1,2})[.\-/](\d{1,2})\b"), "ymd"),
    # 27.06.2023 или 27/06/2023
    (re.compile(r"\b(\d{1,2})[.\-/](\d{1,2})[.\-/](20\d\d)\b"), "dmy"),
    # 7-31-26 — американская запись с двузначным годом, частая в заголовках
    (re.compile(r"\b(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2})\b"), "mdy2"),
)


def _build(year: int, month: int, day: int) -> date | None:
    if year < MIN_YEAR or not (1 <= month <= 12) or not (1 <= day <= 31):
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def content_date(text: str) -> date | None:
    """Дата самого материала, если она указана в тексте."""
    if not text:
        return None

    # Смотрим только начало: дальше по тексту попадаются даты событий,
    # цитат и ссылок, которые к дате материала отношения не имеют
    head = text[:200]

    for pattern, order in _PATTERNS:
        match = pattern.search(head)
        if not match:
            continue

        if order == "dMy":
            day, month_name, year = match.groups()
            found = _build(int(year), MONTHS[month_name.lower()], int(day))
            if found:
                return found
            continue

        if order == "Mdy":
            month_name, day, year = match.groups()
            found = _build(int(year), MONTHS[month_name.lower()], int(day))
            if found:
                return found
            continue

        a, b, c = (int(part) for part in match.groups())

        if order == "ymd":
            found = _build(a, b, c)
        elif order == "dmy":
            # 07.07.2026 читается одинаково в обе стороны, а 27.06 — только так
            found = _build(c, b, a) or _build(c, a, b)
        else:
            # Двузначный год: 26 → 2026. Месяц и день различаем по значению —
            # 31 месяцем быть не может
            year = 2000 + c
            found = _build(year, a, b) if a <= 12 else _build(year, b, a)

        if found:
            return found

    return None


def looks_archived(title: str, text: str, published_at: datetime | None) -> tuple[bool, date | None]:
    """Архивный ли материал и какая у него собственная дата."""
    found = content_date(title) or content_date(text)
    if found is None:
        return False, None

    # Точки отсчёта нет — сравниваем с сегодняшним днём
    reference = (published_at or datetime.now(timezone.utc)).date()

    return reference - found > timedelta(days=ARCHIVE_AFTER_DAYS), found
