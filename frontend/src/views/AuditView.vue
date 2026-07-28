<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { api, type AuditEntry } from '@/api'
import { AUDIT_ACTION_LABELS, formatDate } from '@/labels'

const entries = ref<AuditEntry[]>([])
const loading = ref(true)
const error = ref('')

function actionLabel(action: string) {
  return AUDIT_ACTION_LABELS[action] ?? action
}

function detailsText(details: Record<string, unknown> | null) {
  if (!details) return '—'
  return Object.entries(details)
    .map(([key, value]) => `${key}: ${value}`)
    .join(', ')
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
  <div class="workspace-body" style="padding: 20px">
    <p v-if="error" class="alert alert-error" style="margin-bottom: 12px">{{ error }}</p>

    <section class="ws-surface">
      <div class="ws-surface-head">
        <h2 class="ws-surface-title">Журнал действий</h2>
        <button class="ws-btn ws-btn-quiet" @click="load">Обновить</button>
      </div>

      <div v-if="loading" class="spinner-line">Загружаем…</div>
      <div v-else-if="!entries.length" class="empty-state">Записей пока нет.</div>

      <div v-else class="table-wrap">
        <table class="ws-audit-table ws-table">
          <thead>
            <tr>
              <th>Время</th>
              <th>Пользователь</th>
              <th>Действие</th>
              <th>Объект</th>
              <th>Подробности</th>
              <th>IP</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="entry in entries" :key="entry.id">
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
