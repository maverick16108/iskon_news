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
export type SourceKind = 'rss' | 'html'

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
  rendered: string
  char_count: number
  is_within_limit: boolean
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
}

export interface ArticleImage {
  id: number
  url: string
  caption: string | null
  caption_ru: string | null
  width: number | null
  height: number | null
  position: number
  is_selected: boolean
}

export interface ArticleListItem extends Article {
  source_name: string
  post_status: PostStatus | null
  post_char_count: number | null
  image_count: number
}

export interface ArticleDetail extends Article {
  content: string | null
  post: Post | null
  images: ArticleImage[]
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
}

export interface LlmSettings {
  base_url: string
  model: string
  temperature: number
  api_key_set: boolean
  api_key_hint: string | null
  updated_at: string
  updated_by: string | null
}

export interface LlmTestResult {
  ok: boolean
  message: string
  model: string | null
  elapsed_ms: number | null
}

export const MAX_POST_CHARS = 1000
