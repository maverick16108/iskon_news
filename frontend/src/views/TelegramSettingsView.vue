<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { api, type TelegramCheckResult, type TelegramSettings } from '@/api'
import { formatDate } from '@/labels'

const current = ref<TelegramSettings | null>(null)
const loading = ref(true)
const saving = ref(false)
const checking = ref(false)
const error = ref('')
const notice = ref('')
const checkResult = ref<TelegramCheckResult | null>(null)

const form = reactive({ channel: '', bot_token: '', is_enabled: false })

const dirty = computed(
  () =>
    !!current.value &&
    (form.channel !== current.value.channel ||
      form.is_enabled !== current.value.is_enabled ||
      form.bot_token.length > 0),
)

async function load() {
  loading.value = true
  try {
    current.value = await api.get<TelegramSettings>('/api/settings/telegram')
    form.channel = current.value.channel
    form.is_enabled = current.value.is_enabled
    form.bot_token = ''
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
      channel: form.channel,
      is_enabled: form.is_enabled,
    }
    if (form.bot_token.trim()) payload.bot_token = form.bot_token.trim()

    current.value = await api.patch<TelegramSettings>('/api/settings/telegram', payload)
    form.bot_token = ''
    notice.value = form.is_enabled
      ? 'Сохранено. Кнопка «Опубликовать» теперь отправляет пост в канал.'
      : 'Сохранено. Отправка в канал выключена — «Опубликовать» только помечает пост.'
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Не удалось сохранить'
  } finally {
    saving.value = false
  }
}

async function check() {
  checking.value = true
  checkResult.value = null
  error.value = ''
  try {
    checkResult.value = await api.post<TelegramCheckResult>('/api/settings/telegram/check')
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Проверка не удалась'
  } finally {
    checking.value = false
  }
}

onMounted(load)
</script>

<template>
  <div>
    <p v-if="error" class="alert alert-error" style="margin-bottom: 12px">{{ error }}</p>
    <p v-if="notice" class="alert alert-success" style="margin-bottom: 12px">{{ notice }}</p>
    <p
      v-if="checkResult"
      class="alert"
      :class="checkResult.ok ? 'alert-success' : 'alert-error'"
      style="margin-bottom: 12px"
    >
      {{ checkResult.message }}
    </p>

    <section class="ws-surface" style="max-width: 720px">
      <div class="ws-surface-head">
        <h2 class="ws-surface-title">Публикация в канал</h2>
        <span
          v-if="current"
          class="ws-badge"
          :class="current.is_enabled ? 'healthy' : 'neutral'"
        >
          {{ current.is_enabled ? 'Отправка включена' : 'Отправка выключена' }}
        </span>
      </div>

      <div v-if="loading" class="ws-surface-body stack">
        <span class="skeleton skeleton-text" style="width: 30%" />
        <span class="skeleton skeleton-block" style="height: 34px" />
        <span class="skeleton skeleton-text" style="width: 30%" />
        <span class="skeleton skeleton-block" style="height: 34px" />
      </div>

      <form v-else class="ws-surface-body stack" @submit.prevent="save">
        <p class="alert alert-info" style="margin: 0">
          Публикуем через бота — это штатный способ Telegram. Бот должен быть
          администратором канала с правом «Публикация сообщений»; выдать это право
          можно только вручную в самом Telegram.
        </p>

        <div class="ws-field">
          <label class="ws-field-label">Канал</label>
          <div>
            <input v-model="form.channel" class="ws-input" required placeholder="@iskconru" />
            <small class="muted">Публичное имя канала со значком @ или числовой идентификатор.</small>
          </div>
        </div>

        <div class="ws-field">
          <label class="ws-field-label">Токен бота</label>
          <div>
            <input
              v-model="form.bot_token"
              class="ws-input"
              type="password"
              autocomplete="off"
              :placeholder="
                current?.token_set
                  ? `Токен сохранён (${current.token_hint}) — оставьте пустым, чтобы не менять`
                  : 'Токен от @BotFather'
              "
              style="width: 100%"
            />
            <small class="muted">
              Наружу токен не отдаётся: в интерфейсе видны только последние символы.
            </small>
          </div>
        </div>

        <div class="ws-field">
          <label class="ws-field-label">Отправка в канал</label>
          <div>
            <label class="row" style="gap: 8px; cursor: pointer">
              <input v-model="form.is_enabled" type="checkbox" />
              <span>Кнопка «Опубликовать» отправляет пост в канал</span>
            </label>
            <small class="muted">
              Выключено — «Опубликовать» только помечает пост в базе, как раньше.
              Публикация необратима: удалить сообщение можно лишь вручную в Telegram.
            </small>
          </div>
        </div>

        <div class="row">
          <button class="ws-btn ws-btn-primary" type="submit" :disabled="saving || !dirty">
            {{ saving ? 'Сохраняем…' : 'Сохранить' }}
          </button>
          <button class="ws-btn" type="button" :disabled="checking" @click="check">
            {{ checking ? 'Проверяем…' : 'Проверить бота и права' }}
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
