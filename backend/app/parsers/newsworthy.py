"""Отсев материалов, которые новостью не являются.

Источники публикуют не только новости. У dandavats.com половина ленты — записи
лекций и философские заметки, у iskconnews.org рядом с новостями идут колонки
и анонсы курсов:

    New Mayapur SB class by Nrisimha Kavaca Prabhu
    Lord Balarama: Who is He
    2026 Tributes Book Available For Download
    Let us come together in prayer, compassion and service to support those affected

В канал такое не идёт, а редактору приходится прокручивать это глазами.
Поэтому отсеиваем на сборе: статья не заводится вовсе.

Решение принимаем по двум признакам.

**Рубрики.** iskconnews.org сам помечает колонки меткой «Opinion», рецензии —
«Book Review», занятия — «Online-course». Признак надёжный: его проставил
редактор источника, а не угадали мы.

**Заголовок.** У dandavats рубрик нет, зато формат заголовка выдаёт материал
с головой: у лекции в нём стоит имя лектора и дата, у заметки — вопрос или
назывное предложение без события.

Правила проверены на тысяче заголовков iskconnews.org и месячном срезе
dandavats.com, и настроены на точность, а не на полноту: раз статья не
заводится вовсе, ошибочный отсев теряет новость безвозвратно, а пропущенная
вода стоит редактору одного щелчка. Поэтому слова вроде «lecture», «course»,
«workshop» сами по себе ничего не решают — в новостях они встречаются не реже,
чем в воде («Mayapur Acting Workshop Bridges Devotion and Creative Expression» —
это отчёт о событии). Срабатывает связка: слово плюс примета анонса или имя
лектора рядом.

По той же причине здесь нет правила на «заголовок без события» (назывные
фразы вроде «Protecting the Freedom to Practice Krishna Consciousness»):
на живых данных оно уносило вместе с водой некрологи и репортажи.

Каждое правило возвращает причину — она уходит в журнал сбора, так что отсев
видно и можно поправить.
"""

from __future__ import annotations

import re

# --------------------------------------------------------------------------
# Рубрики источника
# --------------------------------------------------------------------------

# Метки iskconnews.org, под которыми выходит не новость. Сравниваем в нижнем
# регистре: одна и та же рубрика приходит и как «Opinion», и как «opinion».
FILLER_CATEGORIES = frozenset(
    {
        "opinion",           # колонки и размышления
        "book review",       # рецензии
        "book-review",
        "course",            # анонсы занятий
        "online-course",
        "onsite-course",
        "online-education",
    }
)


# --------------------------------------------------------------------------
# Приметы, из которых собраны правила
# --------------------------------------------------------------------------

# Кто ведёт: «HH Radhanath Swami», «HG Patri prabhu», «Vraj Vihari Prabhu».
SPEAKER = r"(?:H\.?[HG]\.?|His\s+(?:Holiness|Grace)|Swami|Maharaj|Prabhu|Mataji|Dasi)"

# Примета анонса: занятие не прошло, а объявлено. Отчёт о состоявшемся
# семинаре — это новость, объявление о наборе — нет.
ANNOUNCEMENT = (
    r"(?:upcoming|registration|register\s+now|to\s+host|launch(?:es|ed|ing)?|"
    r"opens?|offer(?:s|ed|ing)?|announce[sd]?|enroll|apply|invites?|begins?|starts?)"
)

# Занятие: слово само по себе ничего не значит, работает только с приметой анонса.
LESSON = r"(?:course|seminar|webinar|workshop|masterclass|training|study\s+group)"


_TITLE_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    # --- Записи лекций и занятий -------------------------------------------
    # «Lecture on Lord Balarama's Appearance Day», «morning lecture HH Janananda Swami».
    # Просто «lecture» не берём: «Vedic Wisdom Meets Academia at Bhaktivedanta
    # Lecture» — это репортаж.
    (re.compile(r"^\s*lectures?\b", re.I), "лекция"),
    (
        re.compile(rf"\blectures?\b.{{0,40}}\b{SPEAKER}\b|\b{SPEAKER}\b.{{0,40}}\blectures?\b", re.I),
        "лекция",
    ),
    # «New Mayapur SB class», «Bhagavatam Class 4.28 51-65». В новостях слово
    # «class» не встречается вовсе — проверено на тысяче заголовков.
    (re.compile(r"\bclass(?:es)?\b", re.I), "занятие"),
    # «Ekadashi Satsanga», «Nectar Talks», «Krishna Katha»
    (re.compile(r"\b(?:satsangas?|nectar talks?|katha)\b", re.I), "программа"),
    # Номер стиха в заголовке: «SB 7.9.1», «BG 2.13», «CC Madhya Ch.08»
    (re.compile(r"\b(?:SB|BG|CC|NOI|NOD)\s*\.?\s*\d", re.I), "разбор стиха"),
    (re.compile(r"\bCC\s+(?:Adi|Madhya|Antya)\b", re.I), "разбор стиха"),
    # «Kriya Shakti & Divyadristi Matajis – LA Rathayatra – 7-30-26».
    # Хвост из даты после тире — так подписывают выложенную запись.
    (
        re.compile(r"[–—|]{1,2}\s*\d{1,2}\s*[-./]\s*\d{1,2}\s*[-./]\s*\d{2,4}\s*$"),
        "запись с датой в заголовке",
    ),
    # «Krishna Lila | HG Madhu Madhav Pr | 24/08/2026 | GEV» — ведущий отдельным
    # полем через разделитель: так подписывают запись, а не новость.
    (
        re.compile(rf"[|–—]\s*(?:H\.?[HG]\.?|His\s+(?:Holiness|Grace))\s", re.I),
        "запись выступления",
    ),

    # --- Курсы и обучение ---------------------------------------------------
    (
        re.compile(rf"\b{ANNOUNCEMENT}\b.{{0,60}}\b{LESSON}\b", re.I),
        "анонс занятия",
    ),
    (
        re.compile(rf"\b{LESSON}\b.{{0,60}}\b{ANNOUNCEMENT}\b", re.I),
        "анонс занятия",
    ),
    # Названия учебных курсов ИСККОН: под ними выходят только наборы.
    # «Бхакти-врикша» сюда не входит — это программа проповеди, о её работе
    # пишут обычные новости («ISKCON Bhopal Hosts Bhakti Vriksha Training»).
    (re.compile(r"\bbhakti[\s-]*(?:sastri|shastri|vaibhava)\b", re.I), "курс"),

    # --- Анонсы материалов --------------------------------------------------
    # «2026 Tributes Book Available For Download»
    (
        re.compile(
            r"\b(?:available for download|free download|now available|out now|pre-?order)\b", re.I
        ),
        "анонс материала",
    ),
    (re.compile(r"\b(?:newsletter|weekly feed|feed archive)\b", re.I), "бюллетень"),

    # --- Воззвания ----------------------------------------------------------
    # «Let us come together in prayer...», «Please pray for...».
    # Сборы средств сюда не относим: «ISKCON Naperville Raises Over $1 Million
    # at Gala Fundraiser» — это новость.
    (
        re.compile(r"^\s*(?:let\s+us\b|let['’]s\b|please\b|join us\b|help us\b|donate\b)", re.I),
        "воззвание",
    ),
    (
        re.compile(r"\b(?:prayers?\s+(?:requested|for)\b|seeks?\s+(?:your\s+)?support)", re.I),
        "воззвание",
    ),
    (re.compile(r"^\s*reaching out to\b", re.I), "воззвание"),

    # --- Объяснения и размышления -------------------------------------------
    # «Lord Balarama: Who is He»
    (re.compile(r"\bwho\s+is\s+(?:he|she|they)\b", re.I), "объяснительная заметка"),
    # Заголовок-вопрос. Только со знаком вопроса: «How a Smart Table Quietly
    # Distributes Thousands of Books» — репортаж, а не разъяснение.
    (re.compile(r"\?\s*$"), "заголовок-вопрос"),
    (
        re.compile(
            r"^\s*the\s+(?:purpose|meaning|value|glories|glory|nature|importance|"
            r"significance|power)\s+(?:and\s+\w+\s+)?of\b",
            re.I,
        ),
        "объяснительная заметка",
    ),
    (re.compile(r"^\s*(?:reflections?|thoughts)\s+on\b", re.I), "размышление"),
    # Серия заметок: «Stimulation for Ecstatic Love Part 189 – Sri Radha's Face Part 2»
    (re.compile(r"\bpart\s+\d+\b", re.I), "выпуск серии"),

    # --- Служебное ----------------------------------------------------------
    (re.compile(r"\b(?:click here|previous posts)\b", re.I), "служебная ссылка"),
)


def _is_shouted(title: str) -> bool:
    """Заголовок целиком капсом — так на dandavats перепечатывают заметки.

    Считаем по буквам, а не по строке: «WSN June 2026» и «ISKCON NYC» —
    это аббревиатуры внутри обычного заголовка, а не крик.
    """
    letters = [c for c in title if c.isalpha()]
    if len(letters) < 12:
        return False
    return all(c.isupper() for c in letters)


def filler_reason(title: str, *, categories: list[str] | None = None) -> str | None:
    """Почему материал не новость. None — если это новость.

    Причину возвращаем строкой, а не просто «да/нет»: она уходит в журнал
    сбора, и по ней видно, какое правило сработало.
    """
    for category in categories or []:
        if category.strip().lower() in FILLER_CATEGORIES:
            return f"рубрика «{category}»"

    for pattern, reason in _TITLE_RULES:
        if pattern.search(title):
            return reason

    if _is_shouted(title):
        return "заголовок капсом"

    return None
