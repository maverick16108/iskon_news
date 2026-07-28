<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import { api, type ArticleListItem, type FetchResult, type PostStatus, type Source } from '@/api'
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
const sourceFilter = ref<number | ''>('')
const statusFilter = ref<PostStatus | '' | 'none'>('')

const statusOptions = Object.entries(POST_STATUS_LABELS) as [PostStatus, string][]

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

onMounted(async () => {
  try {
    sources.value = await api.get<Source[]>('/api/sources')
  } catch {
    // список источников не критичен для ленты
  }
  await load()
})

let debounce: ReturnType<typeof setTimeout>
watch(search, () => {
  clearTimeout(debounce)
  debounce = setTimeout(load, 350)
})
watch([sourceFilter, statusFilter], load)
</script>

<template>
  <div class="workspace-body" style="padding: 20px">
    <div class="ws-control-bar">
      <input v-model="search" class="ws-input ws-control-sm" placeholder="Поиск по заголовку" />

      <select v-model="sourceFilter" class="ws-select ws-control-sm">
        <option value="">Все источники</option>
        <option v-for="s in sources" :key="s.id" :value="s.id">{{ s.name }}</option>
      </select>

      <select v-model="statusFilter" class="ws-select ws-control-sm">
        <option value="">Любой статус</option>
        <option value="none">Не обработаны</option>
        <option v-for="[value, label] in statusOptions" :key="value" :value="value">
          {{ label }}
        </option>
      </select>

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

      <div v-if="loading" class="spinner-line">Загружаем…</div>

      <div v-else-if="!articles.length" class="empty-state">
        Новостей нет. Нажмите «Собрать новости», чтобы обойти источники.
      </div>

      <div v-else class="table-wrap">
        <table class="ws-table">
          <thead>
            <tr>
              <th>Заголовок</th>
              <th>Источник</th>
              <th>Дата</th>
              <th>Исходник</th>
              <th>Пост</th>
              <th class="num">Символов</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="article in articles" :key="article.id">
              <td class="wrap">
                <RouterLink
                  class="title-link"
                  :to="{ name: 'article', params: { id: article.id } }"
                >
                  {{ article.title }}
                </RouterLink>
              </td>
              <td>{{ article.source_name }}</td>
              <td>{{ formatDateShort(article.published_at) }}</td>
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
