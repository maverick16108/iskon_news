<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { api, type ArticleListItem, type FetchResult, type PostStatus, type Source } from '@/api'
import TableSkeleton from '@/components/TableSkeleton.vue'
import UiSelect from '@/components/UiSelect.vue'
import type { SelectOption } from '@/components/select'
import {
  POST_STATUS_LABELS,
  POST_STATUS_TONE,
  QUALITY_LABELS,
  QUALITY_TONE,
  formatDateShort,
} from '@/labels'

const articles = ref<ArticleListItem[]>([])
const sources = ref<Source[]>([])
const loading = ref(true)
const fetching = ref(false)
const error = ref('')
const notice = ref('')

const search = ref('')
const searchInput = ref<HTMLInputElement | null>(null)
const sourceFilter = ref<number | ''>('')
const statusFilter = ref<PostStatus | '' | 'none'>('')

type SortKey = 'published' | 'fetched' | 'title' | 'source' | 'quality' | 'post' | 'chars'
const sortKey = ref<SortKey>('published')
const sortAsc = ref(false)

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
  { key: 'published', label: 'Дата новости', title: 'Когда новость вышла на сайте источника' },
  { key: 'fetched', label: 'Добавлена', title: 'Когда её забрал наш парсер' },
  { key: 'title', label: 'Заголовок' },
  { key: 'source', label: 'Источник' },
  { key: 'quality', label: 'Исходник' },
  { key: 'post', label: 'Пост' },
  { key: 'chars', label: 'Символов', numeric: true },
]

// Сортируем на клиенте: страница отдаёт не больше 100 записей,
// гонять запрос на сервер ради смены порядка незачем.
function sortValue(article: ArticleListItem, key: SortKey): string | number {
  switch (key) {
    case 'title':
      return article.title.toLowerCase()
    case 'source':
      return article.source_name.toLowerCase()
    case 'published':
      return article.published_at ? Date.parse(article.published_at) : 0
    case 'fetched':
      return Date.parse(article.fetched_at)
    case 'quality':
      return article.content_quality
    case 'post':
      return article.post_status ?? ''
    case 'chars':
      return article.post_char_count ?? -1
  }
}

const sorted = computed(() => {
  const factor = sortAsc.value ? 1 : -1
  return [...articles.value].sort((a, b) => {
    const left = sortValue(a, sortKey.value)
    const right = sortValue(b, sortKey.value)
    if (left === right) return 0
    if (typeof left === 'number' && typeof right === 'number') return (left - right) * factor
    return String(left).localeCompare(String(right), 'ru') * factor
  })
})

function toggleSort(key: SortKey) {
  if (sortKey.value === key) {
    sortAsc.value = !sortAsc.value
  } else {
    sortKey.value = key
    // Даты и числа удобнее сразу видеть по убыванию, текст — по алфавиту
    sortAsc.value = !['published', 'fetched', 'chars'].includes(key)
  }
}

function ariaSort(key: SortKey) {
  if (sortKey.value !== key) return 'none'
  return sortAsc.value ? 'ascending' : 'descending'
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const params = new URLSearchParams({ limit: '100' })
    if (search.value.trim()) params.set('search', search.value.trim())
    if (sourceFilter.value !== '') params.set('source_id', String(sourceFilter.value))
    if (statusFilter.value === 'none') params.set('only_unprocessed', 'true')
    else if (statusFilter.value !== '') params.set('status', statusFilter.value)

    articles.value = await api.get<ArticleListItem[]>(`/api/articles?${params}`)
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Не удалось загрузить ленту'
  } finally {
    loading.value = false
  }
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
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Сбор не удался'
  } finally {
    fetching.value = false
  }
}

const unprocessed = computed(() => articles.value.filter((a) => !a.post_status).length)

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
  try {
    sources.value = await api.get<Source[]>('/api/sources')
  } catch {
    // список источников не критичен для ленты
  }
  await load()
})

onBeforeUnmount(() => document.removeEventListener('keydown', onGlobalKeydown))

let debounce: ReturnType<typeof setTimeout>
watch(search, () => {
  clearTimeout(debounce)
  debounce = setTimeout(load, 350)
})
watch([sourceFilter, statusFilter], load)
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

      <span class="row-end row">
        <span class="muted" style="font-size: 13px">
          Показано: {{ articles.length }} · без поста: {{ unprocessed }}
        </span>
        <button class="ws-btn ws-btn-primary" :disabled="fetching" @click="fetchAll">
          {{ fetching ? 'Собираем…' : 'Собрать новости' }}
        </button>
      </span>
    </div>

    <p v-if="error" class="alert alert-error" style="margin-bottom: 12px">{{ error }}</p>
    <p v-if="notice" class="alert alert-success" style="margin-bottom: 12px">{{ notice }}</p>

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
            <tr v-for="article in sorted" :key="article.id">
              <td>{{ formatDateShort(article.published_at) }}</td>
              <td class="muted">{{ formatDateShort(article.fetched_at) }}</td>
              <td class="wrap">
                <RouterLink
                  class="title-link"
                  :to="{ name: 'article', params: { id: article.id } }"
                >
                  {{ article.title }}
                </RouterLink>
                <span v-if="article.image_count" class="photo-count" :title="`Фотографий: ${article.image_count}`">
                  🖼 {{ article.image_count }}
                </span>
              </td>
              <td>{{ article.source_name }}</td>
              <td>
                <span class="ws-badge" :class="QUALITY_TONE[article.content_quality]">
                  {{ QUALITY_LABELS[article.content_quality] }}
                </span>
              </td>
              <td>
                <span
                  v-if="article.post_status"
                  class="ws-badge"
                  :class="POST_STATUS_TONE[article.post_status]"
                >
                  {{ POST_STATUS_LABELS[article.post_status] }}
                </span>
                <span v-else class="muted">—</span>
              </td>
              <td class="num">
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
      </div>
    </section>
  </div>
</template>
