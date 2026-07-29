"""Извлечение изображений статьи.

Со страницы новости берём только контентные картинки: логотипы сайта,
иконки соцсетей, аватарки и прочая обвязка отсеиваются. Подпись ищем
в figcaption, затем в alt, затем в коротком абзаце сразу под картинкой —
на разных сайтах она размечена по-разному.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

log = logging.getLogger(__name__)

# Служебная графика — по пути или имени файла
JUNK_PATTERNS = re.compile(
    r"(logo|icon|sprite|avatar|placeholder|spacer|blank|pixel|emoji|favicon"
    r"|share|social|facebook|twitter|instagram|telegram|whatsapp-icon|youtube"
    r"|/themes?/|/plugins?/|/assets/img/|gravatar)",
    re.I,
)

# Расширения, которые нам не нужны
JUNK_EXTENSIONS = (".svg", ".gif", ".ico")

# Слишком мелкие картинки — почти наверняка декоративные
MIN_DIMENSION = 200

# Подпись длиннее этого — уже не подпись, а абзац текста
MAX_CAPTION_CHARS = 300


@dataclass
class ExtractedImage:
    url: str
    caption: str | None
    width: int | None
    height: int | None


def _content_root(soup: BeautifulSoup) -> Tag:
    """Контейнер с телом статьи."""
    for selector in ("div.details", "div.entry-content", "div.post-content", "article", "main"):
        node = soup.select_one(selector)
        if node:
            return node

    # Ничего не нашли — берём блок с наибольшим числом абзацев
    best: Tag | None = None
    best_count = 0
    for node in soup.find_all(["div", "section"]):
        count = len(node.find_all("p", recursive=False))
        if count > best_count:
            best, best_count = node, count
    return best or soup


def _to_int(value: object) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _best_source(img: Tag, base_url: str) -> str | None:
    """Из srcset берём самый крупный вариант, иначе обычный src."""
    srcset = img.get("srcset") or img.get("data-srcset")
    if srcset:
        best_url, best_width = None, -1
        for chunk in str(srcset).split(","):
            parts = chunk.strip().split()
            if not parts:
                continue
            width = _to_int(parts[1].rstrip("w")) if len(parts) > 1 else 0
            if (width or 0) > best_width:
                best_url, best_width = parts[0], width or 0
        if best_url:
            return urljoin(base_url, best_url)

    src = img.get("src") or img.get("data-src") or img.get("data-lazy-src")
    return urljoin(base_url, str(src)) if src else None


# Имена файлов, из которых подпись не вытащить
MEANINGLESS_NAMES = re.compile(
    r"^(img|image|photo|pic|dsc|screenshot|whatsapp[-_ ]image|untitled|download|"
    r"unnamed|fb[-_]img|received)[-_ \d]*$",
    re.I,
)


def _caption_from_filename(url: str) -> str | None:
    """На iskconnews.org подпись часто зашита в имя файла:
    Devotees-pulling-Rath-while-chanting-.jpg -> «Devotees pulling Rath while chanting»
    """
    name = urlparse(url).path.rsplit("/", 1)[-1]
    name = re.sub(r"\.[a-z0-9]+$", "", name, flags=re.I)          # расширение
    name = re.sub(r"[-_]\d{2,4}x\d{2,4}$", "", name)              # размер миниатюры
    name = re.sub(r"[-_]+\d+$", "", name)                         # хвостовой номер копии
    words = re.sub(r"[-_]+", " ", name).strip()

    if not words or MEANINGLESS_NAMES.match(words):
        return None
    # Мешанина цифр вроде 758964238_1353868086958692_n — не подпись
    digits = sum(c.isdigit() for c in words)
    if digits > len(words) * 0.3:
        return None
    if len(words) < 12 or len(words.split()) < 3:
        return None

    return words[0].upper() + words[1:]


def _caption_for(img: Tag, url: str) -> str | None:
    figure = img.find_parent("figure")
    if figure:
        caption = figure.find("figcaption")
        if caption:
            text = caption.get_text(" ", strip=True)
            if text:
                return text[:MAX_CAPTION_CHARS]

    # На iskconnews.org в alt часто пишут мусор вроде "nw"
    alt = (img.get("alt") or "").strip()
    if len(alt) > 3 and not MEANINGLESS_NAMES.match(alt):
        return alt[:MAX_CAPTION_CHARS]

    # Соседний абзац в подписи не берём: на этих сайтах там идёт
    # обычный текст статьи, и в подпись попадает первый абзац новости.
    return _caption_from_filename(url)


def _looks_like_junk(url: str, width: int | None, height: int | None) -> bool:
    path = urlparse(url).path.lower()

    if path.endswith(JUNK_EXTENSIONS):
        return True
    if JUNK_PATTERNS.search(url):
        return True
    if width is not None and width < MIN_DIMENSION:
        return True
    if height is not None and height < MIN_DIMENSION:
        return True

    return False


def extract_images(html: str, base_url: str, *, limit: int = 12) -> list[ExtractedImage]:
    """Возвращает контентные картинки статьи в порядке появления."""
    soup = BeautifulSoup(html, "html.parser")
    root = _content_root(soup)

    found: list[ExtractedImage] = []
    seen: set[str] = set()

    for img in root.find_all("img"):
        url = _best_source(img, base_url)
        if not url:
            continue

        # Отбрасываем параметры версии, чтобы не дублировать одну картинку
        key = url.split("?")[0]
        if key in seen:
            continue

        width = _to_int(img.get("width"))
        height = _to_int(img.get("height"))

        if _looks_like_junk(url, width, height):
            continue

        seen.add(key)
        found.append(
            ExtractedImage(url=url, caption=_caption_for(img, url), width=width, height=height)
        )

        if len(found) >= limit:
            break

    log.debug("Из %s извлечено картинок: %d", base_url, len(found))
    return found
