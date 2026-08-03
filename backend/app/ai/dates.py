"""Выборка дат из английского текста статьи.

Правило «переноси все даты» в системном промпте работает плохо: при сжатии
до тысячи символов модель первым делом выбрасывает именно даты. Готовый
короткий список прямо в запросе она держит гораздо лучше, чем требование
в конце длинной инструкции.

Здесь только поиск упоминаний — решает, какие из них пойдут в пост, модель.
"""

import re

MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|"
    "November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec"
)

# Предлоги и глаголы, с которыми дата приходит в текст. Забираем их вместе
# с датой: «since 2020» и «by 2030» — разные факты, а год один и тот же.
LEAD = (
    "since|by|in|on|from|until|till|through|before|after|around|during|"
    "established|founded|launched|premiered|opened|began|beginning|starting|"
    "between|early|late|mid"
)

ORDINAL = r"(?:st|nd|rd|th)?"

CORE = (
    # 11 July 2026 / 11th July, 2026
    rf"\b\d{{1,2}}{ORDINAL}\s+(?:{MONTHS})\.?,?\s+\d{{4}}"
    # July 11, 2026 / July 11 / July 2026
    rf"|\b(?:{MONTHS})\.?\s+\d{{1,2}}{ORDINAL},?\s+\d{{4}}"
    rf"|\b(?:{MONTHS})\.?\s+\d{{1,2}}{ORDINAL}\b"
    rf"|\b(?:{MONTHS})\.?\s+\d{{4}}"
    # 2019–2024, 2020s, 2026. Через дефис берём только полные годы: иначе
    # «2026-06-28» из ленты видеозаписей читается как промежуток лет
    r"|\b(?:19|20)\d{2}\s*[–—]\s*(?:19|20)?\d{2}\b"
    r"|\b(?:19|20)\d{2}-(?:19|20)\d{2}\b"
    r"|\b(?:19|20)\d{2}s\b"
    r"|\b(?:19|20)\d{2}\b"
)

MENTION = re.compile(rf"\b(?:(?:{LEAD})\s+)?(?:{CORE})", re.IGNORECASE)

# Год внутри денежной суммы, номера дома или ссылки датой не является
NOT_A_DATE = re.compile(r"[$€£₹]|[/\\]|\d,\d")

MAX_MENTIONS = 12


def collect_dates(text: str, limit: int = MAX_MENTIONS) -> list[str]:
    """Возвращает упоминания дат в порядке появления, без повторов."""
    found: list[str] = []
    seen: set[str] = set()

    for match in MENTION.finditer(text):
        mention = " ".join(match.group().split())
        # Смотрим на пару символов вокруг: «$2,026» и «/2026/» — не даты
        around = text[max(0, match.start() - 2) : match.end() + 1]
        if NOT_A_DATE.search(around):
            continue

        key = mention.lower()
        if key in seen:
            continue
        seen.add(key)
        found.append(mention)
        if len(found) >= limit:
            break

    return found
