/** Тонкая обёртка над fetch: единый разбор ошибок и передача сессионной куки. */

export class ApiError extends Error {
  // Свойство объявлено явно: в конфиге включён erasableSyntaxOnly,
  // а он запрещает сокращённую запись через параметр конструктора.
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...options,
    credentials: 'include', // сессия живёт в httpOnly-куке
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
  })

  if (!response.ok) {
    let detail = `Ошибка ${response.status}`
    try {
      const body = await response.json()
      if (typeof body.detail === 'string') {
        detail = body.detail
      } else if (Array.isArray(body.detail)) {
        // Ошибка валидации pydantic
        detail = body.detail.map((e: { msg: string }) => e.msg).join('; ')
      }
    } catch {
      // тело не JSON — оставляем текст по умолчанию
    }
    throw new ApiError(detail, response.status)
  }

  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: body ? JSON.stringify(body) : undefined }),
  patch: <T>(path: string, body: unknown) =>
    request<T>(path, { method: 'PATCH', body: JSON.stringify(body) }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
}

// --- Типы, зеркалящие схемы бэкенда ---------------------------------------

export type Role = 'superadmin' | 'editor'
export type PostStatus = 'draft' | 'generating' | 'generated' | 'edited' | 'published' | 'failed'
export type ContentQuality = 'full' | 'excerpt' | 'empty'
export type SourceKind = 'rss' | 'archive' | 'html' | 'newsletter'

export interface User {
  id: number
  username: string
  full_name: string | null
  role: Role
  is_active: boolean
  created_at: string
  last_login_at: string | null
}

export interface Source {
  id: number
  name: string
  url: string
  kind: SourceKind
  is_active: boolean
  signature_name: string | null
  signature_suffix: string
  fetch_interval_minutes: number
  last_fetched_at: string | null
  last_error: string | null
  created_at: string
  /** Пусто — применяется шаблон по умолчанию */
  prompt_template_id: number | null
  prompt_template_name: string | null
}

export interface Post {
  id: number
  article_id: number
  hashtags: string
  title: string
  body: string
  signature: string
  status: PostStatus
  ai_model: string | null
  ai_error: string | null
  created_at: string
  updated_at: string
  published_at: string | null
  /** Дата исходной новости, попадает в подпись под постом */
  source_date: string | null
  rendered: string
  char_count: number
  is_within_limit: boolean
  /** Ссылка на сообщение в канале, если пост туда ушёл */
  telegram_url: string | null
}

export interface Article {
  id: number
  source_id: number
  url: string
  title: string
  author: string | null
  published_at: string | null
  summary: string | null
  content_quality: ContentQuality
  image_url: string | null
  categories: string[] | null
  fetched_at: string
  /** Переиздание старой записи: сайт выложил её сегодня, материал давний */
  is_archive: boolean
  /** Дата, указанная в самом материале */
  content_date: string | null
}

/** Ролик из новости. */
export interface ArticleVideo {
  id: number
  url: string
  provider: string
  thumbnail_url: string | null
}

export interface ArticleImage {
  id: number
  /** У загруженных редактором адреса нет */
  url: string | null
  is_uploaded: boolean
  caption: string | null
  caption_ru: string | null
  width: number | null
  height: number | null
  position: number
  is_selected: boolean
  /** Главная: уходит в альбом первой */
  is_cover: boolean
  /** Обложка ролика, а не кадр статьи */
  from_video: boolean
}

export interface ArticleListItem extends Article {
  source_name: string
  post_status: PostStatus | null
  post_char_count: number | null
  image_count: number
  video_count: number
  is_viewed: boolean
  viewed_at: string | null
  repeat_sources: string[]      // другие источники с этим же сюжетом
  repeat_article_ids: number[]  // двойники под своими адресами
  /** Этот же сюжет уже публиковали в другой карточке */
  repeat_published: boolean
}

/** Уйдёт ли пост в канал при публикации. Видно любому вошедшему. */
export interface TelegramState {
  is_enabled: boolean
  ready: string[]     // каналы, готовые принять пост
  blocked: string[]   // отмечены, но бот там публиковать не может
}

/** Что появилось в ленте после указанного момента. */
export interface FeedUpdates {
  count: number
  latest: string | null
  /** Время последнего обхода — лента показывает его в шапке */
  last_run_at: string | null
  last_result: string | null
}

/** Тот же сюжет в другом источнике. */
export interface RepeatEntry {
  source: string
  url: string | null
  article_id: number | null
  /** Состояние поста у двойника: публиковали этот сюжет или нет */
  post_status: PostStatus | null
  telegram_url: string | null
}

export interface ArticleDetail extends Article {
  content: string | null
  post: Post | null
  images: ArticleImage[]
  videos: ArticleVideo[]
  repeats: RepeatEntry[]
}

export interface AuditEntry {
  id: number
  user_id: number | null
  username: string | null
  action: string
  entity_type: string | null
  entity_id: number | null
  details: Record<string, unknown> | null
  ip: string | null
  created_at: string
}

export interface FetchResult {
  source: string
  entries: number
  added: number
  with_full_text: number
  images: number
  videos: number
  /** Переиздания старых записей */
  archived: number
  /** Старше заданной границы возраста */
  too_old: number
  /** Источник не отдал страницу — отложены до следующего обхода */
  unreachable: number
  /** Уже были в ленте от другого источника */
  repeats: number
}

export interface PromptTemplate {
  id: number
  name: string
  description: string | null
  body: string
  is_default: boolean
  created_at: string
  updated_at: string
  updated_by: string | null
  used_by_sources: number
}

export interface PromptPreview {
  rendered: string
  chars: number
}

export interface PlaceholderInfo {
  token: string
  description: string
}

export interface LlmSettings {
  base_url: string
  model: string
  temperature: number
  api_key_set: boolean
  api_key_hint: string | null
  /** Чем закончилось последнее обращение к модели */
  last_ok_at: string | null
  last_error: string | null
  last_error_at: string | null
  /** На счёте закончились средства */
  out_of_money: boolean
  updated_at: string
  updated_by: string | null
}

export interface LlmTestResult {
  ok: boolean
  message: string
  model: string | null
  elapsed_ms: number | null
}

export interface TelegramSettings {
  channel: string
  is_enabled: boolean
  token_set: boolean
  token_hint: string | null
  updated_at: string
  updated_by: string | null
}

/** Расписание автоматического обхода источников. */
export interface FetchSettings {
  is_enabled: boolean
  interval_minutes: number
  /** Новости старше этой даты не собираем */
  min_published_at: string | null
  /** Либо скользящее окно в днях */
  max_age_days: number | null
  last_run_at: string | null
  last_result: string | null
  /** До какого момента подписчикам уже рассказали */
  last_reported_at: string | null
  updated_at: string
  updated_by: string | null
}

/** Кто подписан на оповещения бота. */
export interface BotSubscriber {
  id: number
  chat_id: string
  username: string | null
  full_name: string | null
  notify: boolean
  is_blocked: boolean
  created_at: string
  last_notified_at: string | null
}

export type PlatformKind = 'telegram' | 'max'

/** Канал площадки. */
export interface Channel {
  id: number
  platform_id: number | null
  chat: string
  title: string | null
  is_enabled: boolean
  can_post: boolean | null
  last_status: string | null
  last_checked_at: string | null
}

/** Подключённый мессенджер: свой бот, свой токен, свои каналы. */
export interface Platform {
  id: number
  kind: PlatformKind
  title: string
  is_enabled: boolean
  token_set: boolean
  token_hint: string | null
  bot_username: string | null
  bot_id: string | null
  last_status: string | null
  last_checked_at: string | null
  channels: Channel[]
}

export interface TelegramChannel {
  id: number
  chat: string
  title: string | null
  is_enabled: boolean
  can_post: boolean | null
  last_status: string | null
  last_checked_at: string | null
}

export interface TelegramInfo {
  token_set: boolean
  is_enabled: boolean
  bot_username: string | null
  bot_name: string | null
  bot_id: number | null
  channels: TelegramChannel[]
  message: string
  /** Пока стоит вебхук, бот не принимает команды от людей */
  webhook_url: string | null
}

export const MAX_POST_CHARS = 1000
