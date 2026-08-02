import type { ContentQuality, PostStatus, Role } from '@/api'

export const POST_STATUS_LABELS: Record<PostStatus, string> = {
  draft: 'Черновик',
  generating: 'Генерируется',
  generated: 'Готов от ИИ',
  edited: 'Отредактирован',
  published: 'Опубликован',
  failed: 'Ошибка',
}

/** Классы состояний берём из темы: healthy / info / warning / critical / neutral */
export const POST_STATUS_TONE: Record<PostStatus, string> = {
  draft: 'neutral',
  generating: 'info',
  generated: 'info',
  edited: 'warning',
  published: 'healthy',
  failed: 'critical',
}

export const QUALITY_LABELS: Record<ContentQuality, string> = {
  full: 'Полный текст',
  excerpt: 'Только анонс',
  empty: 'Нет текста',
}

export const QUALITY_TONE: Record<ContentQuality, string> = {
  full: 'healthy',
  excerpt: 'warning',
  empty: 'critical',
}

export const ROLE_LABELS: Record<Role, string> = {
  superadmin: 'Суперадминистратор',
  editor: 'Редактор',
}

export const AUDIT_ACTION_LABELS: Record<string, string> = {
  login: 'Вход в систему',
  logout: 'Выход',
  'user.create': 'Создан пользователь',
  'user.update': 'Изменён пользователь',
  'user.delete': 'Удалён пользователь',
  'source.create': 'Добавлен источник',
  'source.update': 'Изменён источник',
  'source.delete': 'Удалён источник',
  'source.fetch': 'Сбор новостей',
  'source.fetch_all': 'Сбор по всем источникам',
  'post.generate': 'Переработка через ИИ',
  'post.edit': 'Правка поста',
  'post.publish': 'Публикация',
  'post.unpublish': 'Снятие с публикации',
  'article.delete': 'Удалена статья',
  'image.update': 'Изменён выбор фото',
  'llm.update': 'Изменены настройки модели',
  'image.upload': 'Загружены фотографии',
  'image.delete': 'Удалена фотография',
  'prompt.create': 'Создан шаблон промпта',
  'prompt.update': 'Изменён шаблон промпта',
  'prompt.delete': 'Удалён шаблон промпта',
  'telegram.update': 'Изменены настройки публикации',
  'post.refine': 'Правка поста через ИИ',
  'article.refetch': 'Новость перечитана с сайта',
  'article.mark_all_viewed': 'Все новости отмечены просмотренными',
  'schedule.update': 'Изменено расписание сбора',
  'schedule.run': 'Сбор запущен вручную',
  'platform.create': 'Добавлена площадка',
  'platform.update': 'Изменена площадка',
  'platform.delete': 'Удалена площадка',
  'platform.channel_add': 'Добавлен канал',
  'platform.channel_update': 'Изменён канал',
  'platform.channel_delete': 'Удалён канал',
  'telegram.channel_add': 'Добавлен канал',
  'telegram.channel_update': 'Изменён канал',
  'telegram.channel_delete': 'Убран канал',
}

export function formatDate(value: string | null): string {
  if (!value) return '—'
  return new Date(value).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function formatDateShort(value: string | null): string {
  if (!value) return '—'
  return new Date(value).toLocaleDateString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  })
}


// Месяцы для подписи под постом. Формат обязан совпадать с серверным
// до символа: по этой же строке считается лимит в 1000 знаков.
const MONTHS_GENITIVE = [
  'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
  'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря',
]

/** Дата новости словами: «1 августа 2026». */
export function formatNewsDate(value: string | null): string {
  if (!value) return ''
  const date = new Date(value)
  return `${date.getDate()} ${MONTHS_GENITIVE[date.getMonth()]} ${date.getFullYear()}`
}
