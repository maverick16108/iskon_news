<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { api, type LlmSettings, type LlmTestResult } from '@/api'
import ToastStack from '@/components/ToastStack.vue'
import UiSelect from '@/components/UiSelect.vue'
import type { SelectOption } from '@/components/select'
import { formatDate } from '@/labels'

const current = ref<LlmSettings | null>(null)

/* Подпись и цвет метки в шапке. Ключ на месте — ещё не значит, что
   переработка работает: деньги могли кончиться. */
const stateLabel = computed(() => {
  const row = current.value
  if (!row?.api_key_set) return 'Ключа нет'
  if (row.out_of_money) return 'Кончились средства'
  if (row.last_error) return 'Последний запрос не прошёл'
  if (row.last_ok_at) return 'Работает'
  return 'Ключ задан'
})

const stateTone = computed(() => {
  const row = current.value
  if (!row?.api_key_set || row.out_of_money) return 'critical'
  if (row.last_error) return 'warning'
  return 'healthy'
})
const models = ref<string[]>([])
const loading = ref(true)
const saving = ref(false)
const testing = ref(false)
const loadingModels = ref(false)
const error = ref('')
const notice = ref('')
const testResult = ref<LlmTestResult | null>(null)

const form = reactive({
  base_url: '',
  model: '',
  temperature: 0.4,
  api_key: '',
})

const PRESETS: SelectOption[] = [
  { value: 'https://api.openai.com/v1', label: 'OpenAI', hint: 'api.openai.com' },
  { value: 'https://openrouter.ai/api/v1', label: 'OpenRouter', hint: 'openrouter.ai' },
  { value: 'http://localhost:11434/v1', label: 'Ollama локально', hint: 'localhost:11434' },
]

const modelOptions = computed<SelectOption[]>(() => {
  const list = models.value.length ? models.value : [form.model].filter(Boolean)
  return list.map((name) => ({ value: name, label: name }))
})

const dirty = computed(
  () =>
    !!current.value &&
    (form.base_url !== current.value.base_url ||
      form.model !== current.value.model ||
      form.temperature !== current.value.temperature ||
      form.api_key.length > 0),
)

async function load() {
  loading.value = true
  try {
    current.value = await api.get<LlmSettings>('/api/settings/llm')
    form.base_url = current.value.base_url
    form.model = current.value.model
    form.temperature = current.value.temperature
    form.api_key = ''
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Не удалось загрузить настройки'
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  error.value = ''
  notice.value = ''
  try {
    const payload: Record<string, unknown> = {
      base_url: form.base_url,
      model: form.model,
      temperature: form.temperature,
    }
    // Пустое поле означает «ключ не меняем»
    if (form.api_key.trim()) payload.api_key = form.api_key.trim()

    current.value = await api.patch<LlmSettings>('/api/settings/llm', payload)
    form.api_key = ''
    notice.value = 'Настройки сохранены и применяются сразу — перезапуск не нужен'
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Не удалось сохранить'
  } finally {
    saving.value = false
  }
}

async function testConnection() {
  testing.value = true
  testResult.value = null
  error.value = ''
  try {
    testResult.value = await api.post<LlmTestResult>('/api/settings/llm/test')
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Проверка не удалась'
  } finally {
    testing.value = false
  }
}

async function loadModels() {
  loadingModels.value = true
  error.value = ''
  try {
    const result = await api.get<{ models: string[] }>('/api/settings/llm/models')
    models.value = result.models
    notice.value = `Доступно моделей: ${result.models.length}`
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Не удалось получить список моделей'
  } finally {
    loadingModels.value = false
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
    <p
      v-if="testResult"
      class="alert"
      :class="testResult.ok ? 'alert-success' : 'alert-error'"
      style="margin-bottom: 12px"
    >
      {{ testResult.message }}
      <span v-if="testResult.model"> · модель: {{ testResult.model }}</span>
    </p>

    <section class="ws-surface" style="max-width: 720px">
      <div class="ws-surface-head">
        <h2 class="ws-surface-title">Подключение к языковой модели</h2>
        <!-- Состояние важнее наличия ключа: ключ может быть на месте,
             а деньги на счёте кончиться, и переработка встанет -->
        <span v-if="current" class="ws-badge" :class="stateTone">
          {{ stateLabel }}
        </span>
      </div>

      <div v-if="loading" class="ws-surface-body stack">
        <span class="skeleton skeleton-text" style="width: 30%" />
        <span class="skeleton skeleton-block" style="height: 34px" />
        <span class="skeleton skeleton-text" style="width: 30%" />
        <span class="skeleton skeleton-block" style="height: 34px" />
        <span class="skeleton skeleton-text" style="width: 30%" />
        <span class="skeleton skeleton-block" style="height: 34px" />
      </div>

      <form v-else class="ws-surface-body stack" @submit.prevent="save">
        <div class="ws-field">
          <label class="ws-field-label">Адрес API</label>
          <div>
            <input
              v-model="form.base_url"
              class="ws-input"
              required
              placeholder="https://api.openai.com/v1"
              style="width: 100%"
            />
            <div class="row" style="margin-top: 6px; gap: 6px">
              <button
                v-for="preset in PRESETS"
                :key="preset.value"
                type="button"
                class="ws-chip"
                @click="form.base_url = String(preset.value)"
              >
                {{ preset.label }}
              </button>
            </div>
            <small class="muted">
              Подойдёт любой сервис с совместимым API — OpenAI, OpenRouter, локальная модель.
            </small>
          </div>
        </div>

        <div class="ws-field">
          <label class="ws-field-label">Ключ API</label>
          <div>
            <input
              v-model="form.api_key"
              class="ws-input"
              type="password"
              autocomplete="off"
              :placeholder="
                current?.api_key_set
                  ? `Ключ сохранён (${current.api_key_hint}) — оставьте пустым, чтобы не менять`
                  : 'sk-...'
              "
              style="width: 100%"
            />
            <small class="muted">
              Наружу ключ не отдаётся: в интерфейсе видны только последние символы.
            </small>
          </div>
        </div>

        <div class="ws-field">
          <label class="ws-field-label">Модель</label>
          <div>
            <div class="row">
              <UiSelect
                v-if="modelOptions.length"
                v-model="form.model"
                :options="modelOptions"
                style="flex: 1"
              />
              <input v-else v-model="form.model" class="ws-input" style="flex: 1" />
              <button
                type="button"
                class="ws-btn ws-btn-quiet"
                :disabled="loadingModels"
                @click="loadModels"
              >
                {{ loadingModels ? 'Запрашиваем…' : 'Обновить список' }}
              </button>
            </div>
            <small class="muted">
              Список подтягивается по текущему ключу. Пока не нажали — можно вписать название вручную.
            </small>
          </div>
        </div>

        <div class="ws-field">
          <label class="ws-field-label">Температура</label>
          <div>
            <div class="row">
              <input
                v-model.number="form.temperature"
                type="range"
                min="0"
                max="1"
                step="0.05"
                style="flex: 1"
              />
              <b class="char-counter ok" style="min-width: 42px">{{ form.temperature.toFixed(2) }}</b>
            </div>
            <small class="muted">
              Ниже — суше и предсказуемее, выше — свободнее. Для новостей разумно 0.3–0.5.
            </small>
          </div>
        </div>

        <div class="row">
          <button class="ws-btn ws-btn-primary" type="submit" :disabled="saving || !dirty">
            {{ saving ? 'Сохраняем…' : 'Сохранить' }}
          </button>
          <button
            class="ws-btn"
            type="button"
            :disabled="testing"
            @click="testConnection"
          >
            {{ testing ? 'Проверяем…' : 'Проверить связь' }}
          </button>
          <span v-if="current" class="row-end muted" style="font-size: 11px">
            Изменено: {{ formatDate(current.updated_at) }}
            <template v-if="current.updated_by"> · {{ current.updated_by }}</template>
          </span>
        </div>
      </form>
    </section>
  </div>
</template>
