"""Извлечение видеороликов статьи.

У dandavats.com заметная часть публикаций — это записи лекций: на странице
стоит один плеер, текста почти нет. Ссылку на такой ролик редактору нужно
видеть, а его обложку — брать в пост как иллюстрацию.

Ролики ищем и в <iframe>, и в <video>, и в голых ссылках: разные плагины
вставляют их по-разному.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup

# Прямые файлы, которые браузер и Telegram покажут сами
DIRECT_EXTENSIONS = (".mp4", ".webm", ".mov", ".m4v")


@dataclass
class ExtractedVideo:
    url: str                  # адрес для человека: его и кладём в пост
    provider: str             # youtube | vimeo | rutube | vk | file
    video_id: str | None
    thumbnail_url: str | None


def _youtube_id(url: str) -> str | None:
    parsed = urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.")

    if host == "youtu.be":
        return parsed.path.strip("/").split("/")[0] or None
    if host not in ("youtube.com", "m.youtube.com", "youtube-nocookie.com"):
        return None

    if parsed.path.startswith(("/embed/", "/v/", "/shorts/")):
        return parsed.path.split("/")[2] if len(parsed.path.split("/")) > 2 else None
    if parsed.path == "/watch":
        return (parse_qs(parsed.query).get("v") or [None])[0]
    return None


def _vimeo_id(url: str) -> str | None:
    parsed = urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.")
    if host not in ("vimeo.com", "player.vimeo.com"):
        return None
    match = re.search(r"/(\d+)", parsed.path)
    return match.group(1) if match else None


def _classify(url: str) -> ExtractedVideo | None:
    """Опознаёт ролик по адресу. None — это не видео."""
    youtube = _youtube_id(url)
    if youtube:
        return ExtractedVideo(
            url=f"https://www.youtube.com/watch?v={youtube}",
            provider="youtube",
            video_id=youtube,
            # maxresdefault есть не у всех роликов, hqdefault — всегда
            thumbnail_url=f"https://img.youtube.com/vi/{youtube}/hqdefault.jpg",
        )

    vimeo = _vimeo_id(url)
    if vimeo:
        return ExtractedVideo(
            url=f"https://vimeo.com/{vimeo}",
            provider="vimeo",
            video_id=vimeo,
            thumbnail_url=None,   # обложку Vimeo отдаёт только через своё API
        )

    parsed = urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.")

    if host.endswith("rutube.ru") and "/video/" in parsed.path:
        return ExtractedVideo(url=url, provider="rutube", video_id=None, thumbnail_url=None)
    if host.endswith("vk.com") and ("video" in parsed.path or "video" in parsed.query):
        return ExtractedVideo(url=url, provider="vk", video_id=None, thumbnail_url=None)
    if parsed.path.lower().endswith(DIRECT_EXTENSIONS):
        return ExtractedVideo(url=url, provider="file", video_id=None, thumbnail_url=None)

    return None


def extract_videos(html: str, base_url: str, *, limit: int = 6) -> list[ExtractedVideo]:
    """Ролики статьи в порядке появления, без повторов."""
    soup = BeautifulSoup(html, "html.parser")

    found: list[ExtractedVideo] = []
    seen: set[str] = set()

    def remember(raw: str | None) -> None:
        if not raw or len(found) >= limit:
            return
        video = _classify(urljoin(base_url, raw))
        if video is None or video.url in seen:
            return
        seen.add(video.url)
        found.append(video)

    for frame in soup.find_all("iframe"):
        remember(frame.get("src") or frame.get("data-src"))

    for tag in soup.find_all("video"):
        remember(tag.get("src"))
        for source in tag.find_all("source"):
            remember(source.get("src"))

    # Голые ссылки на ролик: встречаются в текстовых анонсах лекций
    for link in soup.find_all("a", href=True):
        remember(link["href"])

    return found
