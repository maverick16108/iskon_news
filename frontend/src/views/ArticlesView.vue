<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import {
  api,
  type ArticleListItem,
  type FeedUpdates,
  type FetchResult,
  type FetchSettings,
  type PostStatus,
  type Source,
} from '@/api'
import NavIcon from '@/components/NavIcon.vue'
import TableSkeleton from '@/components/TableSkeleton.vue'
import ToastStack from '@/components/ToastStack.vue'
import UiSelect from '@/components/UiSelect.vue'
import type { SelectOption } from '@/components/select'
import {
  POST_STATUS_LABELS,
  POST_STATUS_TONE,
  QUALITY_LABELS,
  QUALITY_TONE,
  formatDate,
  formatDateShort,
} from '@/labels'

const PAGE_SIZE = 50

// Насколько заранее просим следующую порцию. Полтора экрана: за это время
// запрос успевает вернуться, и прокрутка не упирается в пустоту.
const PRELOAD_MARGIN_PX = 1500

const router = useRouter()
const route = useRoute()

const articles = ref<ArticleListItem[]>([])
const sources = ref<Source[]>([])
const loading = ref(true)
const loadingMore = ref(false)
const exhausted = ref(false)
const fetching = ref(false)
const error = ref('')
const notice = ref('')

const search = ref('')
const searchInput = ref<HTMLInputElement | null>(null)
const sourceFilter = ref<number | ''>('')
const statusFilter = ref<PostStatus | '' | 'none'>('')
// Переиздания старых записей по умолчанию не показываем
const includeArchive = ref(false)

const sentinel = ref<HTMLElement | null>(null)
let observer: IntersectionObserver | null = null

type SortKey = 'published' | 'fetched' | 'title' | 'source' | 'quality' | 'post' | 'chars'
const SORT_KEYS: SortKey[] = ['published', 'fetched', 'title', 'source', 'quality', 'post', 'chars']

// Сортировку можно задать адресом: бот приводит сюда со ссылкой
// ?sort=fetched, чтобы только что собранные новости были сверху
const initialSort = SORT_KEYS.find((key) => key === route.query.sort)
// По умолчанию сверху то, что собрали последним: у новостей из рассылок
// дата публикации бывает старой, и по ней свежий улов уходит в конец
const sortKey = ref<SortKey>(initialSort ?? 'fetched')
const sortAsc = ref(route.query.order === 'asc')

const sourceOptions = computed<SelectOption[]>(() => [
  { value: '', label: 'Все источники' },
  ...sources.value.map((s) => ({ value: s.id, label: s.name })),
])

const statusOptions = computed<SelectOption[]>(() => [
  { value: '', label: 'Любой статус' },
  { value: 'none', label: 'Не обработаны' },
  ...Object.entries(POST_STATUS_LABELS).map(([value, label]) => ({ value, label })),
])

const COLUMNS: { key: SortKey; label: string; title?: string; numeric?: boolean }[] = [
  { key: 'fetched', label: 'Добавлена', title: 'Когда новость забрал наш сборщик' },
  { key: 'published', label: 'Дата новости', title: 'Когда новость вышла на сайте источника' },
  { key: 'title', label: 'Заголовок' },
  { key: 'source', label: 'Источник' },
  { key: 'quality', label: 'Исходник' },
  { key: 'post', label: 'Пост' },
  { key: 'chars', label: 'Символов', numeric: true },
]

function buildParams(offset: number) {
  const params = new URLSearchParams({
    limit: String(PAGE_SIZE),
    offset: String(offset),
    sort: sortKey.value,
    order: sortAsc.value ? 'asc' : 'desc',
  })
  if (includeArchive.value) params.set('include_archive', 'true')
  if (search.value.trim()) params.set('search', search.value.trim())
  if (sourceFilter.value !== '') params.set('source_id', String(sourceFilter.value))
  if (statusFilter.value === 'none') params.set('only_unprocessed', 'true')
  else if (statusFilter.value !== '') params.set('status', statusFilter.value)
  return params
}

/** Следующая порция — по мере прокрутки и заранее. */
async function loadMore() {
  if (loading.value || loadingMore.value || exhausted.value) return

  loadingMore.value = true
  try {
    const page = await api.get<ArticleListItem[]>(
      `/api/articles?${buildParams(articles.value.length)}`,
    )
    // Сортировка и постраничность живут на сервере, поэтому просто дописываем
    articles.value = [...articles.value, ...page]
    if (page.length < PAGE_SIZE) exhausted.value = true
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Не удалось догрузить ленту'
    exhausted.value = true
  } finally {
    loadingMore.value = false
  }
}

/** Первая страница: список сбрасывается. */
async function load() {
  loading.value = true
  exhausted.value = false
  error.value = ''
  try {
    const page = await api.get<ArticleListItem[]>(`/api/articles?${buildParams(0)}`)
    articles.value = page
    exhausted.value = page.length < PAGE_SIZE

    // Точка отсчёта для слежения — самая свежая из показанных
    const newest = page.reduce<string | null>(
      (max, a) => (!max || a.fetched_at > max ? a.fetched_at : max),
      null,
    )
    if (newest) newestSeen.value = newest
    pendingCount.value = 0
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Не удалось загрузить ленту'
  } finally {
    loading.value = false
  }

  // Держим одну порцию про запас: к моменту, когда читатель до неё
  // доскроллит, она уже будет на месте
  void loadMore()
}

/** Клик по любому месту строки открывает новость. */
function openArticle(article: ArticleListItem, event: MouseEvent | KeyboardEvent) {
  // По ссылке-заголовку и по любому другому элементу управления внутри строки
  // отрабатывает он сам — иначе получилось бы два перехода разом
  const target = event.target as HTMLElement | null
  if (target?.closest('a, button, input, select, textarea')) return

  const mouse = event as MouseEvent
  if (mouse.button === 2) return // правая кнопка — контекстное меню

  const route = router.resolve({ name: 'article', params: { id: article.id } })

  // Средняя кнопка и Ctrl/Cmd открывают в новой вкладке — как у обычной ссылки
  if (mouse.button === 1 || mouse.metaKey || mouse.ctrlKey) {
    window.open(route.href, '_blank', 'noopener')
    return
  }

  // Красим строку сразу: сервер отметит просмотр, но ленту мы уже покидаем
  article.is_viewed = true
  router.push(route)
}

function toggleSort(key: SortKey) {
  if (sortKey.value === key) {
    sortAsc.value = !sortAsc.value
  } else {
    sortKey.value = key
    // Даты и числа удобнее сразу видеть по убыванию, текст — по алфавиту
    sortAsc.value = !['published', 'fetched', 'chars', 'post'].includes(key)
  }
  load()
}

function ariaSort(key: SortKey) {
  if (sortKey.value !== key) return 'none'
  return sortAsc.value ? 'ascending' : 'descending'
}

async function fetchAll() {
  fetching.value = true
  error.value = ''
  notice.value = ''
  try {
    const results = await api.post<FetchResult[]>('/api/sources/fetch-all')
    const added = results.reduce((sum, r) => sum + r.added, 0)
    notice.value = added
      ? `Добавлено новостей: ${added}. ` +
        results
          .filter((r) => r.added)
          .map((r) => `${r.source} — ${r.added}`)
          .join(', ')
      : 'Новых публикаций в источниках нет'
    const archived = results.reduce((sum, r) => sum + r.archived, 0)
    if (archived) notice.value += `. Переизданий старых записей: ${archived} — скрыты из ленты`
    const tooOld = results.reduce((sum, r) => sum + r.too_old, 0)
    if (tooOld) notice.value += `. Старше заданной границы: ${tooOld} — не собирали`
    await Promise.all([load(), loadSchedule()])
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Сбор не удался'
  } finally {
    fetching.value = false
  }
}

const schedule = ref<FetchSettings | null>(null)

async function loadSchedule() {
  try {
    schedule.value = await api.get<FetchSettings>('/api/settings/schedule')
  } catch {
    // не критично: лента работает и без этой строки
  }
}

const lastRunLabel = computed(() => {
  const row = schedule.value
  if (!row?.last_run_at) return 'Сборщик ещё не запускался'
  return `Последний сбор: ${formatDate(row.last_run_at)}`
})

const lastRunHint = computed(() => {
  const row = schedule.value
  if (!row) return ''
  const parts = [row.last_result ?? '']
  parts.push(
    row.is_enabled
      ? `Автоматический сбор включён, раз в ${row.interval_minutes} мин.`
      : 'Автоматический сбор выключен.',
  )
  return parts.filter(Boolean).join(' · ')
})
const unviewed = computed(() => articles.value.filter((a) => !a.is_viewed).length)

// С какого возраста новость уже не новость. Две недели: недельная задержка
// у дайджестов — обычное дело, а всё, что старше, редактору стоит видеть.
const STALE_AFTER_DAYS = 14

/** На сколько дней новость была старой в момент, когда мы её забрали. */
function staleDays(article: ArticleListItem): number {
  if (!article.published_at) return 0
  const days = (Date.parse(article.fetched_at) - Date.parse(article.published_at)) / 86_400_000
  return days >= STALE_AFTER_DAYS ? Math.round(days) : 0
}

/** Словами, чтобы не заставлять считать в уме. */
function staleLabel(days: number): string {
  if (days >= 365) return `${Math.floor(days / 365)} г.`
  if (days >= 60) return `${Math.round(days / 30)} мес.`
  return `${days} дн.`
}

const markingRead = ref(false)

// --- Слежение за новыми новостями ------------------------------------------
// Постоянное соединение здесь избыточно: новости приходят раз в час,
// а короткий запрос раз в полминуты почти ничего не стоит.
const POLL_INTERVAL_MS = 30_000

// Ниже этого от верха считаем, что человек смотрит начало списка,
// и обновляем молча. Если он ушёл вглубь — обновлять под руками нельзя,
// поэтому предлагаем кнопкой.
const TOP_THRESHOLD_PX = 200

const newestSeen = ref<string | null>(null)
const pendingCount = ref(0)
let pollTimer: ReturnType<typeof setInterval> | undefined

async function checkUpdates() {
  // Пока вкладка скрыта или список занят — не дёргаем сервер
  if (document.visibilityState !== 'visible') return
  if (loading.value || loadingMore.value || fetching.value) return

  const params = new URLSearchParams()
  if (newestSeen.value) params.set('since', newestSeen.value)
  if (includeArchive.value) params.set('include_archive', 'true')

  try {
    const updates = await api.get<FeedUpdates>(`/api/articles/updates?${params}`)

    if (!newestSeen.value) {
      newestSeen.value = updates.latest
      return
    }
    if (!updates.count) return

    if (window.scrollY <= TOP_THRESHOLD_PX) {
      await load()
    } else {
      pendingCount.value = updates.count
    }
  } catch {
    // Молчим: это фоновая проверка, ошибку показывать незачем
  }
}

/** Показать пришедшее и вернуться к началу списка. */
async function showPending() {
  pendingCount.value = 0
  await load()
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

function newsWord(count: number) {
  const tens = count % 100
  const ones = count % 10
  if (tens > 10 && tens < 20) return 'новостей'
  if (ones === 1) return 'новость'
  if (ones >= 2 && ones <= 4) return 'новости'
  return 'новостей'
}

/** Отметить все новости просмотренными — отметка личная, чужие не трогаем. */
async function markAllViewed() {
  markingRead.value = true
  error.value = ''
  notice.value = ''
  try {
    const result = await api.post<{ detail: string }>('/api/articles/mark-all-viewed')
    notice.value = result.detail
    // Красим сразу, не дожидаясь перезагрузки списка
    articles.value.forEach((a) => (a.is_viewed = true))
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Не удалось отметить'
  } finally {
    markingRead.value = false
  }
}

/** Набор текста в любом месте страницы уводит фокус в поиск. */
function onGlobalKeydown(event: KeyboardEvent) {
  const target = event.target as HTMLElement | null
  const typingElsewhere =
    target &&
    (target.tagName === 'INPUT' ||
      target.tagName === 'TEXTAREA' ||
      target.tagName === 'SELECT' ||
      target.isContentEditable)

  if (typingElsewhere || event.metaKey || event.ctrlKey || event.altKey) return

  if (event.key === 'Escape' && search.value) {
    search.value = ''
    return
  }

  // Только печатаемые символы: стрелки, Tab и прочая навигация не мешают
  if (event.key.length !== 1) return

  event.preventDefault()
  search.value += event.key
  searchInput.value?.focus()
}

onMounted(async () => {
  document.addEventListener('keydown', onGlobalKeydown)

  observer = new IntersectionObserver(
    (entries) => {
      if (entries.some((entry) => entry.isIntersecting)) loadMore()
    },
    { rootMargin: `${PRELOAD_MARGIN_PX}px` },
  )
  if (sentinel.value) observer.observe(sentinel.value)

  try {
    sources.value = await api.get<Source[]>('/api/sources')
  } catch {
    // список источников не критичен для ленты
  }
  await Promise.all([load(), loadSchedule()])

  pollTimer = setInterval(checkUpdates, POLL_INTERVAL_MS)
  // Вернулись на вкладку — проверяем сразу, не дожидаясь тика
  document.addEventListener('visibilitychange', checkUpdates)
})

onBeforeUnmount(() => {
  document.removeEventListener('keydown', onGlobalKeydown)
  document.removeEventListener('visibilitychange', checkUpdates)
  clearInterval(pollTimer)
  observer?.disconnect()
})

// Наблюдатель вешаем, когда маячок появился в разметке
watch(sentinel, (element) => {
  if (element && observer) observer.observe(element)
})

let debounce: ReturnType<typeof setTimeout>
watch(search, () => {
  clearTimeout(debounce)
  debounce = setTimeout(load, 350)
})
watch([sourceFilter, statusFilter, includeArchive], load)
</script>

<template>
  <div>
    <div class="ws-control-bar">
      <input
        ref="searchInput"
        v-model="search"
        class="ws-input ws-control-sm search-input"
        placeholder="Поиск по заголовку — просто начните печатать"
      />

      <UiSelect v-model="sourceFilter" :options="sourceOptions" small auto />
      <UiSelect v-model="statusFilter" :options="statusOptions" small auto />

      <label class="row archive-toggle" style="gap: 7px; cursor: pointer">
        <span class="ui-check" :class="{ 'is-on': includeArchive }">
          <input v-model="includeArchive" type="checkbox" />
          <NavIcon name="tick" />
        </span>
        <span
          class="muted"
          style="font-size: 13px"
          title="Записи старых лекций, которые сайт выложил заново"
        >
          Показывать архивные
        </span>
      </label>

      <span class="row-end row">
        <span class="muted" style="font-size: 13px" :title="lastRunHint">
          {{ lastRunLabel }}
        </span>
        <button
          class="ws-btn ws-btn-quiet"
          :disabled="markingRead || !unviewed"
          :title="unviewed ? `Отметить просмотренными: ${unviewed}` : 'Непросмотренных нет'"
          @click="markAllViewed"
        >
          {{ markingRead ? 'Отмечаем…' : 'Прочитать все' }}
        </button>
        <button class="ws-btn ws-btn-primary" :disabled="fetching" @click="fetchAll">
          {{ fetching ? 'Собираем…' : 'Собрать новости' }}
        </button>
      </span>
    </div>

    <ToastStack
      :error="error"
      :notice="notice"
      @clear-error="error = ''"
      @clear-notice="notice = ''"
    />

    <!-- Пришло новое, пока человек читал середину списка. Подменять
         строки под руками нельзя, поэтому предлагаем кнопкой. -->
    <Transition name="toast">
      <button v-if="pendingCount" class="feed-pending" type="button" @click="showPending">
        Пришло {{ pendingCount }} {{ newsWord(pendingCount) }} — показать
      </button>
    </Transition>

    <section class="ws-surface">
      <div class="ws-surface-head">
        <h2 class="ws-surface-title">Лента новостей</h2>
      </div>

      <TableSkeleton v-if="loading" :columns="[12, 12, 38, 14, 15, 12, 8]" :rows="10" />

      <div v-else-if="!articles.length" class="empty-state">
        Новостей нет. Нажмите «Собрать новости», чтобы обойти источники.
      </div>

      <div v-else class="table-wrap">
        <table class="ws-table">
          <thead>
            <tr>
              <th
                v-for="column in COLUMNS"
                :key="column.key"
                class="sortable"
                :class="{ 'is-sorted': sortKey === column.key, num: column.numeric }"
                :aria-sort="ariaSort(column.key)"
                :title="column.title"
                tabindex="0"
                @click="toggleSort(column.key)"
                @keydown.enter.prevent="toggleSort(column.key)"
                @keydown.space.prevent="toggleSort(column.key)"
              >
                {{ column.label }}
                <span class="sort-marker">{{
                  sortKey === column.key ? (sortAsc ? '▲' : '▼') : '▲'
                }}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="article in articles"
              :key="article.id"
              class="row-link"
              :class="{ 'is-unread': !article.is_viewed }"
              :title="article.is_viewed ? `Просмотрено: ${formatDate(article.viewed_at)}` : 'Ещё не просматривали'"
              tabindex="0"
              @click="openArticle(article, $event)"
              @auxclick="openArticle(article, $event)"
              @keydown.enter="openArticle(article, $event)"
            >
              <td class="nowrap" data-label="Добавлена">
                <span class="unread-dot" aria-hidden="true" />
                {{ formatDate(article.fetched_at) }}
              </td>
              <td class="muted nowrap" data-label="Дата новости">
                {{ formatDateShort(article.published_at) }}
              </td>
              <td class="wrap cell-title">
                <RouterLink
                  class="title-link"
                  :to="{ name: 'article', params: { id: article.id } }"
                >
                  {{ article.title }}
                </RouterLink>
                <span
                  v-if="article.image_count"
                  class="photo-count"
                  :title="`Фотографий: ${article.image_count}`"
                >
                  <NavIcon name="photo" class="photo-count-icon" />
                  {{ article.image_count }}
                </span>
                <!-- Новость пришла к нам уже несвежей. Это не то же, что архив:
                     там переиздание старой записи, а здесь просто задержка —
                     дайджест дошёл до нас через неделю после публикации. -->
                <span
                  v-if="!article.is_archive && staleDays(article)"
                  class="ws-badge stale-badge"
                  :title="`На момент сбора новости было ${staleDays(article)} дн.`"
                >
                  старая · {{ staleLabel(staleDays(article)) }}
                </span>
                <span
                  v-if="article.is_archive"
                  class="ws-badge archive-badge"
                  :title="`Материал от ${formatDateShort(article.content_date)} — сайт выложил его заново`"
                >
                  архив{{ article.content_date ? ` · ${formatDateShort(article.content_date)}` : '' }}
                </span>
                <span
                  v-if="article.repeat_sources.length"
                  class="ws-badge repeat-badge"
                  :class="{ 'is-published': article.repeat_published }"
                  :title="
                    article.repeat_published
                      ? `Этот сюжет уже уходил в канал. Он есть в источниках: ${article.repeat_sources.join(', ')}`
                      : `Этот же сюжет есть в источниках: ${article.repeat_sources.join(', ')}. В канал ещё не уходил.`
                  "
                >
                  повтор{{ article.repeat_published ? ', опубликован' : '' }} ·
                  {{ article.repeat_sources.join(', ') }}
                </span>
              </td>
              <td data-label="Источник">{{ article.source_name }}</td>
              <td data-label="Исходник">
                <span class="ws-badge" :class="QUALITY_TONE[article.content_quality]">
                  {{ QUALITY_LABELS[article.content_quality] }}
                </span>
              </td>
              <td data-label="Пост">
                <span
                  v-if="article.post_status"
                  class="ws-badge"
                  :class="POST_STATUS_TONE[article.post_status]"
                >
                  {{ POST_STATUS_LABELS[article.post_status] }}
                </span>
                <!-- Пусто по разным причинам: у одних просто ещё не делали
                     пост, а у других его и не сделать — на странице источника
                     один плеер без текста. Это две разные ситуации. -->
                <span
                  v-else-if="article.content_quality === 'empty'"
                  class="muted no-post-note"
                  title="На странице источника нет текста — перерабатывать нечего"
                >
                  нечего перерабатывать
                </span>
                <span v-else class="muted">—</span>
              </td>
              <td class="num" data-label="Символов" :class="{ 'is-empty': article.post_char_count === null }">
                <span
                  v-if="article.post_char_count !== null"
                  class="char-counter"
                  :class="article.post_char_count > 1000 ? 'over' : 'ok'"
                >
                  {{ article.post_char_count }}
                </span>
                <span v-else class="muted">—</span>
              </td>
            </tr>
          </tbody>
        </table>

        <!-- Маячок подгрузки: попал в поле зрения — тянем следующую порцию -->
        <div ref="sentinel" class="load-more">
          <span v-if="loadingMore" class="skeleton skeleton-text" style="width: 180px" />
          <span v-else-if="exhausted" class="muted">Это все новости</span>
        </div>
      </div>
    </section>
  </div>
</template>
