"""Переработка статьи в пост канала через OpenAI."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from openai import APIError, AsyncOpenAI, RateLimitError

from app.ai.config import LlmConfig, current as current_config
from app.ai.hashtags import sanitize_hashtags
from app.ai.prompt import GLOSSARY, render_system_prompt, build_user_prompt
from app.config import settings
from app.models import MAX_POST_CHARS, Article, ContentQuality, Source

log = logging.getLogger(__name__)

# Подпись канала — вторая строка, неизменная
CHANNEL_LINE = "Новости ИСККОН t.me/iskconru"

# Сколько символов резервируем под хэштеги и заголовок, пока их ещё нет
HEAD_RESERVE = 120


class AIError(RuntimeError):
    pass


@dataclass
class Draft:
    hashtags: str
    title: str
    body: str
    signature: str
    raw: str
    model: str

    @property
    def rendered(self) -> str:
        head = f"{self.hashtags} **{self.title}**".strip()
        tail = f"{self.signature}\n{CHANNEL_LINE}".strip()
        return f"{head}\n\n{self.body.strip()}\n\n{tail}"

    @property
    def char_count(self) -> int:
        return len(self.rendered)


def build_client(config: LlmConfig) -> AsyncOpenAI:
    if not config.api_key:
        raise AIError("Не задан ключ API — укажите его в настройках подключения к модели")
    return AsyncOpenAI(api_key=config.api_key, base_url=config.base_url)


def _body_budget(signature: str) -> int:
    tail_len = len(signature) + 1 + len(CHANNEL_LINE)
    # 4 перевода строки между блоками
    return max(200, MAX_POST_CHARS - HEAD_RESERVE - tail_len - 4)


def _parse_response(content: str) -> tuple[list[str], str, str]:
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise AIError(f"Модель вернула не JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise AIError("Модель вернула JSON неверной структуры")

    title = str(data.get("title", "")).strip()
    body = str(data.get("body", "")).strip()
    tags = sanitize_hashtags(data.get("hashtags", []))

    if not title:
        raise AIError("Модель не вернула заголовок")
    if not body:
        raise AIError("Модель не вернула текст поста")

    return tags, title, body


async def rewrite(article: Article, source: Source) -> Draft:
    """Переводит статью на русский и сжимает в пост канала.

    Хэштеги, жирный заголовок и подпись собираются здесь, а не моделью, —
    так формат гарантирован, а на модель остаётся только работа с языком.
    """
    text = article.text_for_ai
    if not text.strip():
        raise AIError("У статьи нет текста для переработки")

    signature = source.signature_line
    budget = _body_budget(signature)

    user_prompt = build_user_prompt(
        title=article.title,
        text=text,
        body_budget=budget,
        published=article.published_at.strftime("%d.%m.%Y") if article.published_at else None,
        author=article.author,
        is_excerpt=article.content_quality is not ContentQuality.full,
    )

    # Промпт берём из шаблона, назначенного источнику; если своего нет —
    # передаём None, и соберётся встроенный по умолчанию.
    template = source.prompt_template.body if source.prompt_template else None

    messages = [
        {"role": "system", "content": render_system_prompt(template)},
        {"role": "user", "content": user_prompt},
    ]

    config = await current_config()
    client = build_client(config)
    model = config.model

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=messages,  # type: ignore[arg-type]
            response_format={"type": "json_object"},
            temperature=config.temperature,
        )
    except RateLimitError as exc:
        raise AIError(f"OpenAI: превышен лимит запросов — {exc}") from exc
    except APIError as exc:
        raise AIError(f"OpenAI вернул ошибку: {exc}") from exc

    raw = response.choices[0].message.content or ""
    tags, title, body = _parse_response(raw)

    draft = Draft(
        hashtags=" ".join(tags),
        title=title,
        body=body,
        signature=signature,
        raw=raw,
        model=model,
    )

    # Лимит в 1000 символов — жёсткое требование, поэтому при перерасходе
    # просим модель сжать текст, а не обрезаем его посередине фразы.
    if draft.char_count > MAX_POST_CHARS:
        overflow = draft.char_count - MAX_POST_CHARS
        log.info("Пост длиннее лимита на %d символов, сокращаем", overflow)
        draft = await _shorten(client, model, messages, raw, overflow, draft)

    return draft


CAPTION_SYSTEM_PROMPT = f"""\
Ты переводишь подписи к фотографиям для новостного телеграм-канала
«Новости ИСККОН» на русский язык.

Правила:
— Перевод короткий, как подпись под фото: без точки в конце, до 120 символов.
— Ничего не добавляй от себя: только то, что есть в исходной подписи.
— Соблюдай терминологию:
{GLOSSARY}

Ответ — строгий JSON вида {{"captions": ["перевод 1", "перевод 2"]}}.
Порядок и количество переводов должны совпадать с исходным списком.\
"""


async def translate_captions(captions: list[str]) -> list[str]:
    """Переводит подписи к фотографиям.

    Одним запросом на всю статью: подписи короткие, а отдельный вызов
    на каждую — лишние деньги и время.
    """
    if not captions:
        return []

    numbered = "\n".join(f"{i + 1}. {text}" for i, text in enumerate(captions))

    config = await current_config()

    try:
        response = await build_client(config).chat.completions.create(
            model=config.model,
            messages=[
                {"role": "system", "content": CAPTION_SYSTEM_PROMPT},
                {"role": "user", "content": f"Переведи подписи:\n{numbered}"},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
        )
    except APIError as exc:
        raise AIError(f"OpenAI вернул ошибку при переводе подписей: {exc}") from exc

    try:
        data = json.loads(response.choices[0].message.content or "")
        translated = [str(item).strip() for item in data.get("captions", [])]
    except (json.JSONDecodeError, AttributeError, TypeError) as exc:
        raise AIError(f"Не удалось разобрать перевод подписей: {exc}") from exc

    # Если модель вернула не то количество — не сдвигаем подписи под чужие фото
    if len(translated) != len(captions):
        log.warning(
            "Подписей на входе %d, в ответе %d — оставляем оригиналы",
            len(captions),
            len(translated),
        )
        return captions

    return translated


async def refine(
    article: Article, source: Source, current: dict, instruction: str
) -> Draft:
    """Правит уже готовый пост по указанию редактора.

    Модель получает исходную статью, текущий пост и просьбу человека.
    Ограничения те же, что при первой генерации: факты только из статьи,
    хэштеги из списка канала, лимит по длине — поэтому системный промпт
    берём тот же самый.
    """
    signature = source.signature_line
    budget = _body_budget(signature)

    template = source.prompt_template.body if source.prompt_template else None

    messages = [
        {"role": "system", "content": render_system_prompt(template)},
        {
            "role": "user",
            "content": build_user_prompt(
                title=article.title,
                text=article.text_for_ai,
                body_budget=budget,
                published=article.published_at.strftime("%d.%m.%Y") if article.published_at else None,
                author=article.author,
                is_excerpt=article.content_quality is not ContentQuality.full,
            ),
        },
        # Текущий пост подаём как прошлый ответ модели — тогда правка
        # ложится на него, а не начинается с чистого листа.
        {"role": "assistant", "content": json.dumps(current, ensure_ascii=False)},
        {
            "role": "user",
            "content": (
                f"Правка от редактора: {instruction.strip()}\n\n"
                "Внеси только её, остальное оставь как есть. Все прежние правила "
                "продолжают действовать: ничего не выдумывай сверх статьи, теги "
                f"бери из списка, тело поста — до {budget} символов. "
                "Верни тот же JSON."
            ),
        },
    ]

    config = await current_config()
    client = build_client(config)

    try:
        response = await client.chat.completions.create(
            model=config.model,
            messages=messages,  # type: ignore[arg-type]
            response_format={"type": "json_object"},
            temperature=config.temperature,
        )
    except RateLimitError as exc:
        raise AIError(f"OpenAI: превышен лимит запросов — {exc}") from exc
    except APIError as exc:
        raise AIError(f"OpenAI вернул ошибку: {exc}") from exc

    raw = response.choices[0].message.content or ""
    tags, title, body = _parse_response(raw)

    draft = Draft(
        hashtags=" ".join(tags),
        title=title,
        body=body,
        signature=signature,
        raw=raw,
        model=config.model,
    )

    if draft.char_count > MAX_POST_CHARS:
        overflow = draft.char_count - MAX_POST_CHARS
        draft = await _shorten(client, config.model, messages, raw, overflow, draft)

    return draft


async def _shorten(
    client: AsyncOpenAI,
    model: str,
    messages: list[dict],
    previous: str,
    overflow: int,
    draft: Draft,
) -> Draft:
    """Второй проход: та же новость, но короче."""
    follow_up = messages + [
        {"role": "assistant", "content": previous},
        {
            "role": "user",
            "content": (
                f"Пост длиннее допустимого на {overflow} символов. "
                f"Сократи тело поста минимум на {overflow + 40} символов: "
                "убери второстепенные подробности и повторы, но сохрани все "
                "ключевые факты, числа и имена. Верни тот же JSON."
            ),
        },
    ]

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=follow_up,  # type: ignore[arg-type]
            response_format={"type": "json_object"},
            temperature=0.3,
        )
    except APIError as exc:
        raise AIError(f"OpenAI вернул ошибку при сокращении: {exc}") from exc

    raw = response.choices[0].message.content or ""
    tags, title, body = _parse_response(raw)

    shortened = Draft(
        hashtags=" ".join(tags) or draft.hashtags,
        title=title,
        body=body,
        signature=draft.signature,
        raw=raw,
        model=model,
    )

    # Если модель и со второй попытки не уложилась — отдаём как есть.
    # Редактор увидит счётчик и подрежет сам; молча ломать текст не станем.
    if shortened.char_count > MAX_POST_CHARS:
        log.warning("После сокращения пост всё ещё %d символов", shortened.char_count)

    return shortened
