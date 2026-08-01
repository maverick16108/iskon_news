<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { api, type FetchSettings } from '@/api'
import NavIcon from '@/components/NavIcon.vue'
import ToastStack from '@/components/ToastStack.vue'
import UiSelect from '@/components/UiSelect.vue'
import type { SelectOption } from '@/components/select'
import { formatDate } from '@/labels'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()

const settings = ref<FetchSettings | null>(null)
const loading = ref(true)
const saving = ref(false)
const running = ref(false)
const error = ref('')
const notice = ref('')

const form = reactive({ is_enabled: false, interval_minutes: 60 })

// Готовые интервалы плюс «своё значение»: чаще пяти минут ходить по сайтам
// невежливо, реже недели — новости успеют устареть
const INTERVALS: SelectOption[] = [
  { value: 15, label: 'Каждые 15 минут' },
  { value: 30, label: 'Каждые полчаса' },
  { value: 60, label: 'Раз в час' },
  { value: 180, label: 'Раз в три часа' },
  { value: 360, label: 'Раз в шесть часов' },
  { value: 720, label: 'Дважды в сутки' },
  { value: 1440, label: 'Раз в сутки' },
  { value: 10080, label: 'Раз в неделю' },
]

const dirty = computed(
  () =>
    !!settings.value &&
    (form.is_enabled !== settings.value.is_enabled ||
      form.interval_minutes !== settings.value.interval_minutes),
)

/** Когда ждать следующий обход. */
const nextRun = computed(() => {
  const row = settings.value
  if (!row || !row.is_enabled) return ''
  if (!row.last_run_at) return 'при ближайшей проверке'

  const next = new Date(Date.parse(row.last_run_at) + row.interval_minutes * 60_000)
  return formatDate(next.toISOString())
})

async function load() {
  loading.value = true
  try {
    settings.value = await api.get<FetchSettings>('/api/settings/schedule')
    form.is_enabled = settings.value.is_enabled
    form.interval_minutes = settings.value.interval_minutes
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Не удалось загрузить расписание'
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  error.value = ''
  notice.value = ''
  try {
    settings.value = await api.patch<FetchSettings>('/api/settings/schedule', { ...form })
    notice.value = form.is_enabled
      ? 'Расписание сохранено, обход будет идти автоматически'
      : 'Расписание сохранено, автоматический обход выключен'
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Не удалось сохранить'
  } finally {
    saving.value = false
  }
}

async function runNow() {
  running.value = true
  error.value = ''
  notice.value = ''
  try {
    const result = await api.post<{ detail: string }>('/api/settings/schedule/run')
    notice.value = result.detail
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Обход не удался'
  } finally {
    running.value = false
  }
}

onMounted(load)
</script>

<template>
  <div>
    <ToastStack
      :error="error"
      :notice="notice"
      @clear-error="error = ''"
      @clear-notice="notice = ''"
    />

    <section class="ws-surface" style="max-width: 860px">
      <div class="ws-surface-head">
        <h2 class="ws-surface-title">Автоматический сбор</h2>
        <span
          v-if="settings"
          class="ws-badge"
          :class="settings.is_enabled ? 'healthy' : 'neutral'"
        >
          {{ settings.is_enabled ? 'Работает' : 'Выключен' }}
        </span>
      </div>

      <div v-if="loading" class="ws-surface-body stack">
        <span class="skeleton skeleton-text" style="width: 35%" />
        <span class="skeleton skeleton-block" style="height: 34px" />
        <span class="skeleton skeleton-text" style="width: 25%" />
      </div>

      <form v-else class="ws-surface-body stack" @submit.prevent="save">
        <p class="alert alert-info" style="margin: 0">
          Обход идёт внутри самого приложения: отдельную службу заводить не нужно.
          Источники обходятся по очереди, между запросами к одному сайту выдерживается
          пауза — иначе он начинает отвечать отказом.
        </p>

        <div class="ws-field">
          <label class="ws-field-label">Как часто проверять источники</label>
          <div>
            <UiSelect v-model="form.interval_minutes" :options="INTERVALS" />
            <small v-if="settings?.is_enabled" class="muted">
              Следующий обход: {{ nextRun }}
            </small>
          </div>
        </div>

        <label class="row" style="gap: 8px; cursor: pointer">
          <span class="ui-check" :class="{ 'is-on': form.is_enabled }">
            <input v-model="form.is_enabled" type="checkbox" :disabled="!auth.isSuperadmin" />
            <NavIcon name="tick" />
          </span>
          <span>Собирать новости автоматически</span>
        </label>

        <div class="row">
          <button
            class="ws-btn ws-btn-primary"
            type="submit"
            :disabled="saving || !dirty || !auth.isSuperadmin"
          >
            {{ saving ? 'Сохраняем…' : 'Сохранить' }}
          </button>
          <button
            class="ws-btn ws-btn-quiet"
            type="button"
            :disabled="running"
            @click="runNow"
          >
            {{ running ? 'Обходим источники…' : 'Собрать сейчас' }}
          </button>
        </div>

        <div v-if="settings?.last_run_at" class="muted" style="font-size: 12px">
          Последний обход: {{ formatDate(settings.last_run_at) }} — {{ settings.last_result }}
        </div>
        <div v-else class="muted" style="font-size: 12px">Автоматический обход ещё не запускался.</div>
      </form>
    </section>
  </div>
</template>
