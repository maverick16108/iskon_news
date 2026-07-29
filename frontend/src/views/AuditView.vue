<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { api, type AuditEntry } from '@/api'
import TableSkeleton from '@/components/TableSkeleton.vue'
import { AUDIT_ACTION_LABELS, formatDate } from '@/labels'

const entries = ref<AuditEntry[]>([])
const loading = ref(true)
const error = ref('')

type SortKey = 'created' | 'username' | 'action' | 'entity' | 'ip'
const sortKey = ref<SortKey>('created')
const sortAsc = ref(false)

const COLUMNS: { key: SortKey; label: string }[] = [
  { key: 'created', label: 'Время' },
  { key: 'username', label: 'Пользователь' },
  { key: 'action', label: 'Действие' },
  { key: 'entity', label: 'Объект' },
]

function actionLabel(action: string) {
  return AUDIT_ACTION_LABELS[action] ?? action
}

function detailsText(details: Record<string, unknown> | null) {
  if (!details) return '—'
  return Object.entries(details)
    .map(([key, value]) => `${key}: ${value}`)
    .join(', ')
}

function sortValue(entry: AuditEntry, key: SortKey): string | number {
  switch (key) {
    case 'created':
      return Date.parse(entry.created_at)
    case 'username':
      return (entry.username ?? '').toLowerCase()
    case 'action':
      return actionLabel(entry.action).toLowerCase()
    case 'entity':
      return `${entry.entity_type ?? ''}${entry.entity_id ?? ''}`
    case 'ip':
      return entry.ip ?? ''
  }
}

const sorted = computed(() => {
  const factor = sortAsc.value ? 1 : -1
  return [...entries.value].sort((a, b) => {
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
    sortAsc.value = key !== 'created'
  }
}

function ariaSort(key: SortKey) {
  if (sortKey.value !== key) return 'none'
  return sortAsc.value ? 'ascending' : 'descending'
}

async function load() {
  loading.value = true
  try {
    entries.value = await api.get<AuditEntry[]>('/api/audit?limit=200')
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Не удалось загрузить журнал'
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div>
    <p v-if="error" class="alert alert-error" style="margin-bottom: 12px">{{ error }}</p>

    <section class="ws-surface">
      <div class="ws-surface-head">
        <h2 class="ws-surface-title">Журнал действий</h2>
        <button class="ws-btn ws-btn-quiet" :disabled="loading" @click="load">Обновить</button>
      </div>

      <TableSkeleton v-if="loading" :columns="[15, 14, 20, 12, 28, 11]" :rows="12" />
      <div v-else-if="!entries.length" class="empty-state">Записей пока нет.</div>

      <div v-else class="table-wrap">
        <table class="ws-audit-table ws-table">
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
              <th>Подробности</th>
              <th
                class="sortable"
                :class="{ 'is-sorted': sortKey === 'ip' }"
                :aria-sort="ariaSort('ip')"
                tabindex="0"
                @click="toggleSort('ip')"
                @keydown.enter.prevent="toggleSort('ip')"
                @keydown.space.prevent="toggleSort('ip')"
              >
                IP
                <span class="sort-marker">{{
                  sortKey === 'ip' ? (sortAsc ? '▲' : '▼') : '▲'
                }}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="entry in sorted" :key="entry.id">
              <td>{{ formatDate(entry.created_at) }}</td>
              <td>{{ entry.username || '—' }}</td>
              <td>{{ actionLabel(entry.action) }}</td>
              <td class="mono" style="font-size: 12px">
                {{ entry.entity_type ? `${entry.entity_type} #${entry.entity_id}` : '—' }}
              </td>
              <td class="wrap muted" style="font-size: 12px">{{ detailsText(entry.details) }}</td>
              <td class="mono" style="font-size: 12px">{{ entry.ip || '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>
