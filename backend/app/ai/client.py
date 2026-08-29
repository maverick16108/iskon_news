"""Переработка статьи в пост канала через OpenAI."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from openai import APIError, AsyncOpenAI, RateLimitError

from app.ai.config import LlmConfig, current as current_config, prompt_for
from app.ai.hashtags import sanitize_hashtags
from app.ai.prompt import GLOSSARY, render_system_prompt, build_user_prompt
from app.config import settings
from app.models import CHANNEL_TITLE, Article, ContentQuality, Source, render_post

log = logging.getLogger(__name__)

# Сколько символов резервируем под хэштеги и заголовок, пока их ещё нет
HEAD_RESERVE = 120

# Насколько пост должен не дотянуть до нижней границы, чтобы просить модель
# дописать. Отклонение в несколько процентов не стоит лишнего запроса, а
# главное — лишнего повода что-нибудь присочинить.
UNDERSHOOT_TOLERANCE = 0.1


# У «превышен лимит запросов» и «закончились деньги» один код ответа — 429,
# и различить их можно только по типу ошибки в теле. Разница существенная:
# лимит проходит сам через минуту, а деньги сами не появятся.
QUOTA_MARKERS = ("insufficient_quota", "billing", "exceeded your current quota", "credit balance")


def is_quota_error(exc: Exception) -> bool:
    """Кончились ли средства на счёте, а не просто уперлись в частоту."""
    text = str(exc).lower()
    code = getattr(getattr(exc, "body", None), "get", lambda *_: None)("code")
    return code == "insufficient_quota" or any(m in text for m in QUOTA_MARKERS)


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
        return render_post(self.hashtags, self.title, self.body, self.signature)

    @property
    def char_count(self) -> int:
        return len(self.rendered)


def build_client(config: LlmConfig) -> AsyncOpenAI:
    if not config.api_key:
        raise AIError("Не задан ключ API — укажите его в настройках подключения к модели")
    return AsyncOpenAI(api_key=config.api_key, base_url=config.base_url)


def _tail_length(signature: str) -> int:
    """Длина подписи в готовом посте: источник, перевод строки и канал жирным."""
    return len(signature) + 1 + len(CHANNEL_TITLE) + len("****")


def _body_budget(signature: str, max_chars: int) -> int:
    """Сколько символов остаётся телу поста при верхней границе."""
    # 4 перевода строки между блоками
    return max(200, max_chars - HEAD_RESERVE - _tail_length(signature) - 4)


def _body_floor(signature: str, min_chars: int) -> int:
    """Сколько символов тело должно набрать, чтобы пост дотянул до нижней границы."""
    return max(120, min_chars - HEAD_RESERVE - _tail_length(signature) - 4)


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

    config = await current_config()
    prompt = await prompt_for(source)
    min_chars, max_chars = prompt.min_chars, prompt.max_chars

    signature = source.signature_line
    budget = _body_budget(signature, max_chars)

    user_prompt = build_user_prompt(
        title=article.title,
        text=text,
        body_budget=budget,
        body_floor=_body_floor(signature, min_chars),
        min_chars=min_chars,
        max_chars=max_chars,
        published=article.published_at.strftime("%d.%m.%Y") if article.published_at else None,
        author=article.author,
        is_excerpt=article.content_quality is not ContentQuality.full,
    )

    messages = [
        {
            "role": "system",
            "content": render_system_prompt(prompt.body, min_chars=min_chars, max_chars=max_chars),
        },
        {"role": "user", "content": user_prompt},
    ]

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
        if is_quota_error(exc):
            raise AIError(
                "На счёте OpenAI закончились средства — переработка не работает, "
                "пока баланс не пополнят"
            ) from exc
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

    return await _fit_to_range(client, model, messages, raw, draft, min_chars, max_chars)


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
    config = await current_config()
    prompt = await prompt_for(source)
    min_chars, max_chars = prompt.min_chars, prompt.max_chars

    signature = source.signature_line
    budget = _body_budget(signature, max_chars)

    messages = [
        {
            "role": "system",
            "content": render_system_prompt(prompt.body, min_chars=min_chars, max_chars=max_chars),
        },
        {
            "role": "user",
            "content": build_user_prompt(
                title=article.title,
                text=article.text_for_ai,
                body_budget=budget,
                body_floor=_body_floor(signature, min_chars),
                min_chars=min_chars,
                max_chars=max_chars,
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

    client = build_client(config)

    try:
        response = await client.chat.completions.create(
            model=config.model,
            messages=messages,  # type: ignore[arg-type]
            response_format={"type": "json_object"},
            temperature=config.temperature,
        )
    except RateLimitError as exc:
        if is_quota_error(exc):
            raise AIError(
                "На счёте OpenAI закончились средства — переработка не работает, "
                "пока баланс не пополнят"
            ) from exc
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

    return await _fit_to_range(client, config.model, messages, raw, draft, min_chars, max_chars)


async def _second_pass(
    client: AsyncOpenAI,
    model: str,
    messages: list[dict],
    previous: str,
    draft: Draft,
    instruction: str,
) -> Draft:
    """Ещё один проход по той же новости с дополнительным указанием.

    Прошлый ответ подаём как реплику модели, а не пересобираем разговор:
    правка тогда ложится на готовый пост, а не пишется с чистого листа.
    """
    follow_up = messages + [
        {"role": "assistant", "content": previous},
        {"role": "user", "content": instruction},
    ]

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=follow_up,  # type: ignore[arg-type]
            response_format={"type": "json_object"},
            temperature=0.3,
        )
    except RateLimitError as exc:
        # Про кончившиеся деньги говорим теми же словами, что и при первой
        # переработке: по ним роутер узнаёт, что дело в счёте, а не в частоте.
        if is_quota_error(exc):
            raise AIError(
                "На счёте OpenAI закончились средства — переработка не работает, "
                "пока баланс не пополнят"
            ) from exc
        raise AIError(f"OpenAI: превышен лимит запросов — {exc}") from exc
    except APIError as exc:
        raise AIError(f"OpenAI вернул ошибку при пересчёте длины: {exc}") from exc

    raw = response.choices[0].message.content or ""
    tags, title, body = _parse_response(raw)

    return Draft(
        hashtags=" ".join(tags) or draft.hashtags,
        title=title,
        body=body,
        signature=draft.signature,
        raw=raw,
        model=model,
    )


def _shorten_instruction(overflow: int) -> str:
    return (
        f"Пост длиннее допустимого на {overflow} символов. "
        f"Сократи тело поста минимум на {overflow + 40} символов: "
        "убери второстепенные подробности и повторы, но сохрани все "
        "ключевые факты, числа, имена и даты. Даты не выбрасывай — "
        "лучше убрать описание или эпитет. Верни тот же JSON."
    )


def _lengthen_instruction(shortfall: int) -> str:
    return (
        f"Пост короче нужного на {shortfall} символов. "
        f"Дополни тело поста примерно на {shortfall + 40} символов, "
        "используя ТОЛЬКО то, что есть в исходной статье: подробности "
        "события, числа, имена участников, даты, прямую речь. "
        "Ничего не выдумывай и не добавляй общих рассуждений, оценок "
        "и рассказов об ИСККОН вообще. Если в статье добавить больше "
        "нечего — верни пост без изменений. Верни тот же JSON."
    )


async def _fit_to_range(
    client: AsyncOpenAI,
    model: str,
    messages: list[dict],
    previous: str,
    draft: Draft,
    min_chars: int,
    max_chars: int,
) -> Draft:
    """Подгоняет пост под заданный в настройках диапазон длины.

    Верхняя граница — жёсткая: длиннее пост не примет ни канал, ни проверка
    при публикации, поэтому просим модель сжать текст, а не режем его
    посередине фразы.

    Нижнюю соблюдаем мягче. Она нужна, чтобы из большой статьи не вышло
    три строки, но гнаться за каждым символом здесь вредно: чем настойчивее
    просишь «подлиннее», тем охотнее модель доливает воду. Поэтому
    дописываем, только если недобор заметный, и разрешаем вернуть как есть,
    когда в статье добавить нечего.
    """
    if draft.char_count > max_chars:
        overflow = draft.char_count - max_chars
        log.info("Пост длиннее предела на %d символов, сокращаем", overflow)
        result = await _second_pass(
            client, model, messages, previous, draft, _shorten_instruction(overflow)
        )
        # Если модель и со второй попытки не уложилась — отдаём как есть.
        # Редактор увидит счётчик и подрежет сам; молча ломать текст не станем.
        if result.char_count > max_chars:
            log.warning("После сокращения пост всё ещё %d символов", result.char_count)
        return result

    if draft.char_count < min_chars * (1 - UNDERSHOOT_TOLERANCE):
        shortfall = min_chars - draft.char_count
        log.info("Пост короче нижней границы на %d символов, дописываем", shortfall)
        result = await _second_pass(
            client, model, messages, previous, draft, _lengthen_instruction(shortfall)
        )
        # Просили дописать — а получили перебор: такое бывает, когда в статье
        # было чем дополнить. Возвращаем более короткий из двух, лишь бы
        # не вылезти за верхнюю границу.
        if result.char_count > max_chars:
            log.info("После дописывания пост вышел за предел — оставляем прежний")
            return draft
        return result

    return draft


async def resize(article: Article, source: Source, current: dict, target: int) -> Draft:
    """Переделывает готовый пост под заданную длину.

    Редактор жмёт «короче» или «длиннее», интерфейс присылает нужное число
    символов — модель переписывает пост под него. Отдельно от «правки по
    указанию»: там человек говорит, что поменять по смыслу, а здесь смысл
    остаётся прежним и меняется только объём.
    """
    config = await current_config()
    prompt = await prompt_for(source)
    min_chars, max_chars = prompt.min_chars, prompt.max_chars

    signature = source.signature_line
    messages = [
        {
            "role": "system",
            "content": render_system_prompt(prompt.body, min_chars=min_chars, max_chars=max_chars),
        },
        {
            "role": "user",
            "content": build_user_prompt(
                title=article.title,
                text=article.text_for_ai,
                body_budget=_body_budget(signature, target),
                body_floor=_body_floor(signature, target),
                min_chars=min_chars,
                max_chars=max_chars,
                published=article.published_at.strftime("%d.%m.%Y") if article.published_at else None,
                author=article.author,
                is_excerpt=article.content_quality is not ContentQuality.full,
            ),
        },
    ]

    # Хэштеги роутер отдаёт списком — тем же, что уходит в модель;
    # для подсчёта длины они нужны строкой.
    tags = current.get("hashtags", "")
    tags = " ".join(tags) if isinstance(tags, list) else str(tags)

    previous = json.dumps(current, ensure_ascii=False)
    length_now = len(
        render_post(tags, current.get("title", ""), current.get("body", ""), signature)
    )

    if target < length_now:
        instruction = (
            f"Сделай пост короче: сейчас в нём {length_now} символов, нужно "
            f"около {target}. Убирай второстепенные подробности, повторы и "
            "эпитеты, но сохрани все ключевые факты, числа, имена и даты. "
            "Смысл и тему не меняй. Верни тот же JSON."
        )
    else:
        instruction = (
            f"Сделай пост длиннее: сейчас в нём {length_now} символов, нужно "
            f"около {target}. Дополняй ТОЛЬКО тем, что есть в исходной статье: "
            "подробностями события, числами, именами, датами, прямой речью. "
            "Ничего не выдумывай, не добавляй общих рассуждений и оценок. "
            "Смысл и тему не меняй. Верни тот же JSON."
        )

    client = build_client(config)

    draft = Draft(
        hashtags=tags,
        title=current.get("title", ""),
        body=current.get("body", ""),
        signature=signature,
        raw=previous,
        model=config.model,
    )

    return await _second_pass(client, config.model, messages, previous, draft, instruction)
