<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { api, type FetchResult, type Source } from '@/api'
import TableSkeleton from '@/components/TableSkeleton.vue'
import UiSelect from '@/components/UiSelect.vue'
import type { SelectOption } from '@/components/select'
import { formatDate } from '@/labels'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()

const sources = ref<Source[]>([])
const loading = ref(true)
const busyId = ref<number | null>(null)
const error = ref('')
const notice = ref('')
const showForm = ref(false)

type SortKey = 'name' | 'url' | 'signature' | 'fetched' | 'state'
const sortKey = ref<SortKey>('name')
const sortAsc = ref(true)

const COLUMNS: { key: SortKey; label: string }[] = [
  { key: 'name', label: 'Название' },
  { key: 'url', label: 'Адрес' },
  { key: 'signature', label: 'Подпись' },
  { key: 'fetched', label: 'Последний сбор' },
  { key: 'state', label: 'Состояние' },
]

const SUFFIX_OPTIONS: SelectOption[] = [
  { value: 'website', label: 'website' },
  { value: 'facebook page', label: 'facebook page' },
  { value: 'telegram channel', label: 'telegram channel' },
]

const form = reactive({
  name: '',
  url: '',
  kind: 'rss' as const,
  signature_name: '',
  signature_suffix: 'website',
  fetch_interval_minutes: 60,
})

function sortValue(source: Source, key: SortKey): string | number {
  switch (key) {
    case 'name':
      return source.name.toLowerCase()
    case 'url':
      return source.url.toLowerCase()
    case 'signature':
      return (source.signature_name || source.name).toLowerCase()
    case 'fetched':
      return source.last_fetched_at ? Date.parse(source.last_fetched_at) : 0
    case 'state':
      return source.is_active ? 1 : 0
  }
}

const sorted = computed(() => {
  const factor = sortAsc.value ? 1 : -1
  return [...sources.value].sort((a, b) => {
    const left = sortValue(a, sortKey.value)
    const right = sortValue(b, sortKey.value)
    if (left === right) return 0
    if (typeof left === 'number' && typeof right === 'number') return (left - right) * factor
    return String(left).localeCompare(String(right), 'ru') * factor
  })
})

function toggleSort(key: SortKey) {
  if (sortKey.value === key) sortAsc.value = !sortAsc.value
  else {
    sortKey.value = key
    sortAsc.value = key !== 'fetched'
  }
}

function ariaSort(key: SortKey) {
  if (sortKey.value !== key) return 'none'
  return sortAsc.value ? 'ascending' : 'descending'
}

async function load() {
  loading.value = true
  try {
    sources.value = await api.get<Source[]>('/api/sources')
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Не удалось загрузить источники'
  } finally {
    loading.value = false
  }
}

async function create() {
  error.value = ''
  notice.value = ''
  try {
    await api.post<Source>('/api/sources', {
      ...form,
      signature_name: form.signature_name || null,
    })
    notice.value = `Источник «${form.name}» добавлен`
    Object.assign(form, {
      name: '',
      url: '',
      signature_name: '',
      signature_suffix: 'website',
      fetch_interval_minutes: 60,
    })
    showForm.value = false
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Не удалось добавить источник'
  }
}

async function toggleActive(source: Source) {
  try {
    await api.patch<Source>(`/api/sources/${source.id}`, { is_active: !source.is_active })
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Не удалось изменить источник'
  }
}

async function fetchOne(source: Source) {
  busyId.value = source.id
  error.value = ''
  notice.value = ''
  try {
    const result = await api.post<FetchResult>(`/api/sources/${source.id}/fetch`)
    notice.value = `${result.source}: записей ${result.entries}, добавлено ${result.added}, с полным текстом ${result.with_full_text}`
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Сбор не удался'
  } finally {
    busyId.value = null
  }
}

async function remove(source: Source) {
  if (!confirm(`Удалить источник «${source.name}»? Его статьи тоже будут удалены.`)) return
  try {
    await api.delete(`/api/sources/${source.id}`)
    notice.value = `Источник «${source.name}» удалён`
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Не удалось удалить источник'
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="ws-control-bar">
      <span class="muted" style="font-size: 13px">Всего источников: {{ sources.length }}</span>
      <span class="row-end">
        <button
          v-if="auth.isSuperadmin"
          class="ws-btn ws-btn-primary"
          @click="showForm = !showForm"
        >
          {{ showForm ? 'Отмена' : 'Добавить источник' }}
        </button>
      </span>
    </div>

    <p v-if="error" class="alert alert-error" style="margin-bottom: 12px">{{ error }}</p>
    <p v-if="notice" class="alert alert-success" style="margin-bottom: 12px">{{ notice }}</p>

    <section v-if="showForm" class="ws-surface" style="margin-bottom: 16px">
      <div class="ws-surface-head"><h2 class="ws-surface-title">Новый источник</h2></div>
      <form class="ws-surface-body stack" @submit.prevent="create">
        <div class="ws-field">
          <label class="ws-field-label">Название</label>
          <input v-model="form.name" class="ws-input" required placeholder="ISKCON News" />
        </div>
        <div class="ws-field">
          <label class="ws-field-label">Адрес RSS-фида</label>
          <input
            v-model="form.url"
            class="ws-input"
            required
            placeholder="https://example.org/feed/"
          />
        </div>
        <div class="ws-field">
          <label class="ws-field-label">
            Подпись в посте — как источник называется в последней строке
          </label>
          <div>
            <div class="row">
              <input
                v-model="form.signature_name"
                class="ws-input"
                style="flex: 1"
                placeholder="ISKCON News"
              />
              <UiSelect v-model="form.signature_suffix" :options="SUFFIX_OPTIONS" auto />
            </div>
            <small class="muted">
              Получится: «{{ form.signature_name || form.name || '…' }}»
              {{ form.signature_suffix }}
            </small>
          </div>
        </div>
        <div class="ws-field">
          <label class="ws-field-label">Как часто проверять, минут</label>
          <input
            v-model.number="form.fetch_interval_minutes"
            class="ws-input"
            type="number"
            min="5"
            max="10080"
          />
        </div>
        <div class="row">
          <button class="ws-btn ws-btn-primary" type="submit">Добавить</button>
        </div>
      </form>
    </section>

    <section class="ws-surface">
      <div class="ws-surface-head"><h2 class="ws-surface-title">Источники</h2></div>

      <TableSkeleton v-if="loading" :columns="[20, 30, 20, 18, 12, 10]" :rows="4" />
      <div v-else-if="!sources.length" class="empty-state">Источники ещё не добавлены.</div>

      <div v-else class="table-wrap">
        <table class="ws-table">
          <thead>
            <tr>
              <th
                v-for="column in COLUMNS"
                :key="column.key"
                class="sortable"
                :class="{ 'is-sorted': sortKey === column.key }"
                :aria-sort="ariaSort(column.key)"
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
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="source in sorted" :key="source.id">
              <td>{{ source.name }}</td>
              <td class="mono" style="font-size: 12px">{{ source.url }}</td>
              <td>«{{ source.signature_name || source.name }}» {{ source.signature_suffix }}</td>
              <td>{{ formatDate(source.last_fetched_at) }}</td>
              <td>
                <span class="ws-badge" :class="source.is_active ? 'healthy' : 'neutral'">
                  {{ source.is_active ? 'Активен' : 'Отключён' }}
                </span>
                <div v-if="source.last_error" class="muted" style="font-size: 11px; margin-top: 4px">
                  {{ source.last_error }}
                </div>
              </td>
              <td>
                <div class="row" style="gap: 6px; justify-content: flex-end">
                  <button
                    class="ws-btn ws-btn-quiet"
                    :disabled="busyId === source.id"
                    @click="fetchOne(source)"
                  >
                    {{ busyId === source.id ? 'Собираем…' : 'Собрать' }}
                  </button>
                  <template v-if="auth.isSuperadmin">
                    <button class="ws-btn ws-btn-quiet" @click="toggleActive(source)">
                      {{ source.is_active ? 'Отключить' : 'Включить' }}
                    </button>
                    <button class="ws-btn ws-btn-danger" @click="remove(source)">Удалить</button>
                  </template>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>
