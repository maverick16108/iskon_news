<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { api, type FetchSettings } from '@/api'
import NavIcon from '@/components/NavIcon.vue'
import ToastStack from '@/components/ToastStack.vue'
import UiDate from '@/components/UiDate.vue'
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

const form = reactive({
  is_enabled: false,
  interval_minutes: 60,
  // Пустая строка = «без ограничения». Дата хранится как YYYY-MM-DD для <input type="date">
  min_published_at: '',
  max_age_days: '' as number | '',
})

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

const dirty = computed(() => {
  const row = settings.value
  if (!row) return false
  return (
    form.is_enabled !== row.is_enabled ||
    form.interval_minutes !== row.interval_minutes ||
    form.min_published_at !== (row.min_published_at?.slice(0, 10) ?? '') ||
    String(form.max_age_days) !== String(row.max_age_days ?? '')
  )
})

/** Словами: какие новости сборщик пропустит. */
const cutoffHint = computed(() => {
  const parts: string[] = []
  if (form.min_published_at) parts.push(`вышедшие раньше ${form.min_published_at}`)
  if (form.max_age_days) parts.push(`старше ${form.max_age_days} дн.`)
  if (!parts.length) return 'Ограничения нет: собираем всё, что найдём в источниках.'
  return `Не собираем: ${parts.join(' и ')}. Публикации без даты собираются в любом случае.`
})

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
    form.min_published_at = settings.value.min_published_at?.slice(0, 10) ?? ''
    form.max_age_days = settings.value.max_age_days ?? ''
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
    settings.value = await api.patch<FetchSettings>('/api/settings/schedule', {
      is_enabled: form.is_enabled,
      interval_minutes: form.interval_minutes,
      // Пусто в поле означает «снять ограничение», а не «не менять»
      min_published_at: form.min_published_at ? `${form.min_published_at}T00:00:00Z` : null,
      max_age_days: form.max_age_days === '' ? null : Number(form.max_age_days),
    })
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

        <div class="ws-field">
          <label class="ws-field-label">Не собирать новости старше</label>
          <div>
            <div class="row">
              <UiDate
                v-model="form.min_published_at"
                :disabled="!auth.isSuperadmin"
                placeholder="Без ограничения"
              />
              <span class="muted" style="font-size: 13px">или не старше</span>
              <input
                v-model="form.max_age_days"
                class="ws-input"
                type="number"
                min="0"
                max="3650"
                placeholder="дней"
                style="max-width: 110px"
                :disabled="!auth.isSuperadmin"
              />
              <span class="muted" style="font-size: 13px">дней</span>
            </div>
            <small class="muted">{{ cutoffHint }}</small>
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
