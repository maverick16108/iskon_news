<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { api, type TelegramChannel, type TelegramInfo, type TelegramSettings } from '@/api'
import { formatDate } from '@/labels'

const settings = ref<TelegramSettings | null>(null)
const info = ref<TelegramInfo | null>(null)
const loading = ref(true)
const saving = ref(false)
const busyId = ref<number | null>(null)
const adding = ref(false)
const error = ref('')
const notice = ref('')

const form = reactive({ bot_token: '', is_enabled: false })
const newChannel = ref('')

const channels = computed(() => info.value?.channels ?? [])
const enabledCount = computed(() => channels.value.filter((c) => c.is_enabled).length)
const readyCount = computed(() => channels.value.filter((c) => c.is_enabled && c.can_post).length)

const dirty = computed(
  () =>
    !!settings.value &&
    (form.is_enabled !== settings.value.is_enabled || form.bot_token.length > 0),
)

async function load() {
  loading.value = true
  try {
    settings.value = await api.get<TelegramSettings>('/api/settings/telegram')
    form.is_enabled = settings.value.is_enabled
    form.bot_token = ''
    info.value = await api.get<TelegramInfo>('/api/settings/telegram/info')
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
    const payload: Record<string, unknown> = { is_enabled: form.is_enabled }
    if (form.bot_token.trim()) payload.bot_token = form.bot_token.trim()

    settings.value = await api.patch<TelegramSettings>('/api/settings/telegram', payload)
    form.bot_token = ''
    notice.value = form.is_enabled
      ? 'Сохранено. «Опубликовать» теперь отправляет пост в отмеченные каналы.'
      : 'Сохранено. Отправка выключена — «Опубликовать» только помечает пост.'
    info.value = await api.get<TelegramInfo>('/api/settings/telegram/info')
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Не удалось сохранить'
  } finally {
    saving.value = false
  }
}

async function addChannel() {
  const chat = newChannel.value.trim()
  if (!chat) return

  adding.value = true
  error.value = ''
  try {
    await api.post<TelegramChannel>('/api/settings/telegram/channels', { chat })
    newChannel.value = ''
    info.value = await api.get<TelegramInfo>('/api/settings/telegram/info')
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Не удалось добавить канал'
  } finally {
    adding.value = false
  }
}

async function toggleChannel(channel: TelegramChannel) {
  error.value = ''
  try {
    await api.patch<TelegramChannel>(`/api/settings/telegram/channels/${channel.id}`, {
      is_enabled: !channel.is_enabled,
    })
    info.value = await api.get<TelegramInfo>('/api/settings/telegram/info')
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Не удалось изменить канал'
  }
}

async function checkChannel(channel: TelegramChannel) {
  busyId.value = channel.id
  error.value = ''
  try {
    await api.post<TelegramChannel>(`/api/settings/telegram/channels/${channel.id}/check`)
    info.value = await api.get<TelegramInfo>('/api/settings/telegram/info')
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Проверка не удалась'
  } finally {
    busyId.value = null
  }
}

async function removeChannel(channel: TelegramChannel) {
  if (!confirm(`Убрать ${channel.chat} из списка каналов?`)) return
  error.value = ''
  try {
    await api.delete(`/api/settings/telegram/channels/${channel.id}`)
    info.value = await api.get<TelegramInfo>('/api/settings/telegram/info')
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Не удалось убрать канал'
  }
}

onMounted(load)
</script>

<template>
  <div>
    <p v-if="error" class="alert alert-error" style="margin-bottom: 12px">{{ error }}</p>
    <p v-if="notice" class="alert alert-success" style="margin-bottom: 12px">{{ notice }}</p>

    <!-- Кто подключён -->
    <section class="ws-surface" style="margin-bottom: 16px; max-width: 860px">
      <div class="ws-surface-head">
        <h2 class="ws-surface-title">Бот</h2>
        <span
          v-if="info"
          class="ws-badge"
          :class="info.bot_username ? 'healthy' : 'critical'"
        >
          {{ info.bot_username ? 'На связи' : 'Нет связи' }}
        </span>
      </div>

      <div v-if="loading" class="ws-surface-body stack">
        <span class="skeleton skeleton-text" style="width: 40%" />
        <span class="skeleton skeleton-text" style="width: 25%" />
      </div>

      <div v-else class="ws-surface-body">
        <div v-if="info?.bot_username" class="bot-card">
          <span class="bot-avatar">@</span>
          <div>
            <div class="bot-name">@{{ info.bot_username }}</div>
            <div class="muted" style="font-size: 12px">
              {{ info.bot_name }} · идентификатор {{ info.bot_id }}
            </div>
          </div>
          <span class="row-end muted" style="font-size: 12px">
            Каналов в списке: {{ channels.length }} · отмечено: {{ enabledCount }} ·
            готовы принимать: {{ readyCount }}
          </span>
        </div>
        <p v-else class="alert alert-error" style="margin: 0">
          {{ info?.message || 'Бот недоступен' }}
        </p>
      </div>
    </section>

    <!-- Каналы -->
    <section class="ws-surface" style="margin-bottom: 16px; max-width: 860px">
      <div class="ws-surface-head">
        <h2 class="ws-surface-title">Куда публикуем</h2>
      </div>

      <div class="ws-surface-body stack">
        <p class="alert alert-info" style="margin: 0">
          Список каналов ведётся вручную: Telegram не даёт узнать, в каких каналах состоит
          бот, — такого метода в Bot API просто нет. Проверить можно только тот канал,
          который вы назвали. Чтобы бот мог публиковать, добавьте его администратором
          канала с правом «Публикация сообщений».
        </p>

        <div class="row">
          <input
            v-model="newChannel"
            class="ws-input"
            style="flex: 1"
            placeholder="@имя_канала или числовой идентификатор"
            @keydown.enter.prevent="addChannel"
          />
          <button
            class="ws-btn ws-btn-primary"
            type="button"
            :disabled="adding || !newChannel.trim()"
            @click="addChannel"
          >
            {{ adding ? 'Добавляем…' : 'Добавить канал' }}
          </button>
        </div>
      </div>

      <div v-if="loading" class="ws-surface-body">
        <span class="skeleton skeleton-block" style="height: 60px" />
      </div>
      <div v-else-if="!channels.length" class="empty-state">Каналы ещё не добавлены.</div>

      <div v-else class="table-wrap">
        <table class="ws-table">
          <thead>
            <tr>
              <th>Канал</th>
              <th>Название</th>
              <th>Состояние</th>
              <th>Проверен</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="channel in channels" :key="channel.id">
              <td class="mono">{{ channel.chat }}</td>
              <td>{{ channel.title || '—' }}</td>
              <td class="wrap">
                <span
                  class="ws-badge"
                  :class="channel.can_post ? 'healthy' : channel.can_post === false ? 'critical' : 'neutral'"
                >
                  {{
                    channel.can_post
                      ? 'Готов принимать'
                      : channel.can_post === false
                        ? 'Публиковать не может'
                        : 'Не проверен'
                  }}
                </span>
                <div v-if="channel.last_status" class="muted" style="font-size: 11px; margin-top: 4px">
                  {{ channel.last_status }}
                </div>
              </td>
              <td>{{ formatDate(channel.last_checked_at) }}</td>
              <td>
                <div class="row" style="gap: 6px; justify-content: flex-end">
                  <button
                    class="ws-btn ws-btn-quiet"
                    :disabled="busyId === channel.id"
                    @click="checkChannel(channel)"
                  >
                    {{ busyId === channel.id ? 'Проверяем…' : 'Проверить' }}
                  </button>
                  <button class="ws-btn ws-btn-quiet" @click="toggleChannel(channel)">
                    {{ channel.is_enabled ? 'Не публиковать' : 'Публиковать' }}
                  </button>
                  <button class="ws-btn ws-btn-danger" @click="removeChannel(channel)">
                    Убрать
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <!-- Токен и общий выключатель -->
    <section class="ws-surface" style="max-width: 860px">
      <div class="ws-surface-head">
        <h2 class="ws-surface-title">Настройки</h2>
        <span
          v-if="settings"
          class="ws-badge"
          :class="settings.is_enabled ? 'healthy' : 'neutral'"
        >
          {{ settings.is_enabled ? 'Отправка включена' : 'Отправка выключена' }}
        </span>
      </div>

      <form v-if="!loading" class="ws-surface-body stack" @submit.prevent="save">
        <div class="ws-field">
          <label class="ws-field-label">Токен бота</label>
          <div>
            <input
              v-model="form.bot_token"
              class="ws-input"
              type="password"
              autocomplete="off"
              :placeholder="
                settings?.token_set
                  ? `Токен сохранён (${settings.token_hint}) — оставьте пустым, чтобы не менять`
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
          <label class="ws-field-label">Вещать в каналы</label>
          <div>
            <label class="row" style="gap: 8px; cursor: pointer">
              <input v-model="form.is_enabled" type="checkbox" />
              <span>Кнопка «Опубликовать» отправляет пост в отмеченные каналы</span>
            </label>
            <small class="muted">
              Выключено — «Опубликовать» только помечает пост в базе. Публикация
              необратима: удалить сообщение можно лишь вручную в Telegram.
            </small>
          </div>
        </div>

        <div class="row">
          <button class="ws-btn ws-btn-primary" type="submit" :disabled="saving || !dirty">
            {{ saving ? 'Сохраняем…' : 'Сохранить' }}
          </button>
          <span v-if="settings" class="row-end muted" style="font-size: 11px">
            Изменено: {{ formatDate(settings.updated_at) }}
            <template v-if="settings.updated_by"> · {{ settings.updated_by }}</template>
          </span>
        </div>
      </form>
    </section>
  </div>
</template>
