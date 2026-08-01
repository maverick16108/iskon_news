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
    (re.compile(rf"\b(\d{{1,2}})\s*({_MONTH_RE})\.?,?\s*(20\d\d|19\d\d)\b", re.I), "dMy"),
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


# Слова, после которых дата — это дата самого материала: так подписывают
# записи лекций и письма.
OWN_DATE_MARKERS = re.compile(
    r"(lecture|class|talk|letter|recorded|delivered|spoken|given|"
    r"лекция|запись|письмо|прочитан)\w*[^.]{0,60}$",
    re.I,
)

# Ссылки на стихи писаний выглядят точно как дата: «ŚB 3.16.18» — это
# песнь, глава и стих, а не 16 марта 2018 года. Проверяем, что стоит
# непосредственно перед числом.
SCRIPTURE_MARKERS = re.compile(
    r"(s\.?\s?b\.?|ś\.?\s?b\.?|c\.?\s?c\.?|b\.?\s?g\.?|"
    r"bhagavatam|bhagavad|bhāgavatam|caitanya|caritamrta|caritāmṛta|gita|gītā|"
    r"canto|madhya|antya|adi|ādi|"
    r"бхагаватам|бхагавад|чайтанья|чаритамрита|гита|песнь|глава|стих)"
    r"[\s\-–—|:.]*$",
    re.I,
)

# Слова, после которых дата заведомо чужая: рождение, смерть, основание.
# Проверяются раньше остальных признаков — «born on August 31, 1945»
# в некрологе не делает сам некролог материалом сорок пятого года.
ALIEN_DATE_MARKERS = re.compile(
    r"(born|died|passed away|founded|established|inaugurated|launched|"
    r"since|until|starting|beginning|родил|скончал|основан|учрежд)\w*[^.]{0,40}$",
    re.I,
)

# Публикации вида «2023.06.27 – Название» начинаются прямо с даты
HEAD_DATE_CHARS = 12


def _is_own_date(text: str, start: int) -> bool:
    """Дата материала или просто дата, упомянутая в тексте.

    Различить необходимо: в некрологе «born on August 31, 1945» и в новости
    «following the inauguration on February 4, 2026» даты к возрасту самого
    материала отношения не имеют, а «Lecture given on Nov. 26, 1966» — имеет.
    """
    before = text[:start]

    if ALIEN_DATE_MARKERS.search(before):
        return False
    if start <= HEAD_DATE_CHARS:
        return True
    return bool(OWN_DATE_MARKERS.search(before))


def content_date(text: str, *, require_marker: bool = False) -> date | None:
    """Дата самого материала, если она указана в тексте.

    В заголовке дате верим как есть, в тексте — только если она подписывает
    сам материал, а не упомянута по ходу изложения.
    """
    if not text:
        return None

    # Смотрим только начало: дальше по тексту попадаются даты событий,
    # цитат и ссылок, которые к дате материала отношения не имеют
    head = text[:300]

    for pattern, order in _PATTERNS:
        match = pattern.search(head)
        if not match:
            continue

        # Номер стиха писания — не дата, и в заголовке тоже
        if SCRIPTURE_MARKERS.search(head[: match.start()]):
            continue

        if require_marker and not _is_own_date(head, match.start()):
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
    # В заголовке дата почти всегда относится к самому материалу
    # («CC Reading – 7-31-26»), в тексте — далеко не всегда
    found = content_date(title) or content_date(text, require_marker=True)
    if found is None:
        return False, None

    # Точки отсчёта нет — сравниваем с сегодняшним днём
    reference = (published_at or datetime.now(timezone.utc)).date()

    return reference - found > timedelta(days=ARCHIVE_AFTER_DAYS), found
