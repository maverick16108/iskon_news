<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import {
  api,
  type BotSubscriber,
  type Channel,
  type Platform,
  type PlatformKind,
  type TelegramInfo,
} from '@/api'
import NavIcon from '@/components/NavIcon.vue'
import ToastStack from '@/components/ToastStack.vue'
import UiSelect from '@/components/UiSelect.vue'
import type { SelectOption } from '@/components/select'
import { formatDate } from '@/labels'

const platforms = ref<Platform[]>([])
const subscribers = ref<BotSubscriber[]>([])
const info = ref<TelegramInfo | null>(null)
const loading = ref(true)
const busyId = ref<number | null>(null)
const error = ref('')
const notice = ref('')

const showForm = ref(false)
const form = reactive({ kind: 'telegram' as PlatformKind, title: '', token: '' })

// Черновики токенов: по одному на площадку, чтобы правка одной не сбрасывала другую
const tokenDraft = reactive<Record<number, string>>({})
const chatDraft = reactive<Record<number, string>>({})

const KINDS: SelectOption[] = [
  { value: 'telegram', label: 'Telegram', hint: 'Бот создаётся у @BotFather' },
  {
    value: 'max',
    label: 'MAX',
    hint: 'Бот создаётся в кабинете организации на dev.max.ru и проходит модерацию',
  },
]

const KIND_LABELS: Record<string, string> = { telegram: 'Telegram', max: 'MAX' }

const HINTS: Record<string, string> = {
  telegram:
    'Токен выдаёт @BotFather. Чтобы бот мог публиковать, добавьте его администратором канала с правом «Публикация сообщений».',
  max:
    'Токен выдаётся в кабинете организации на dev.max.ru; бот становится доступен после модерации. Идентификатор канала приходит боту в событии bot_added.',
}

const readyCount = computed(() =>
  platforms.value
    .filter((p) => p.is_enabled && p.token_set)
    .reduce((sum, p) => sum + p.channels.filter((c) => c.is_enabled && c.can_post).length, 0),
)

async function load() {
  loading.value = true
  try {
    platforms.value = await api.get<Platform[]>('/api/settings/platforms')
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Не удалось загрузить площадки'
  } finally {
    loading.value = false
  }
}

async function loadExtras() {
  try {
    subscribers.value = await api.get<BotSubscriber[]>('/api/settings/schedule/subscribers')
  } catch {
    // не критично для экрана
  }
  try {
    info.value = await api.get<TelegramInfo>('/api/settings/telegram/info')
  } catch {
    // не критично: нужно только предупреждение о вебхуке
  }
}

async function addPlatform() {
  error.value = ''
  try {
    await api.post<Platform>('/api/settings/platforms', {
      kind: form.kind,
      title: form.title.trim() || KIND_LABELS[form.kind],
      token: form.token.trim(),
    })
    notice.value = 'Площадка добавлена. Проверьте связь и добавьте каналы.'
    Object.assign(form, { kind: 'telegram', title: '', token: '' })
    showForm.value = false
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Не удалось добавить площадку'
  }
}

async function saveToken(platform: Platform) {
  const token = (tokenDraft[platform.id] ?? '').trim()
  if (!token) return

  busyId.value = platform.id
  error.value = ''
  try {
    await api.patch<Platform>(`/api/settings/platforms/${platform.id}`, { token })
    tokenDraft[platform.id] = ''
    notice.value = 'Токен сохранён и проверен'
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Не удалось сохранить токен'
  } finally {
    busyId.value = null
  }
}

async function toggleEnabled(platform: Platform) {
  error.value = ''
  try {
    await api.patch<Platform>(`/api/settings/platforms/${platform.id}`, {
      is_enabled: !platform.is_enabled,
    })
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Не удалось изменить площадку'
  }
}

async function checkPlatform(platform: Platform) {
  busyId.value = platform.id
  error.value = ''
  try {
    await api.post<Platform>(`/api/settings/platforms/${platform.id}/check`)
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Проверка не удалась'
  } finally {
    busyId.value = null
  }
}

async function removePlatform(platform: Platform) {
  if (!confirm(`Удалить площадку «${platform.title}» вместе с её каналами?`)) return
  try {
    await api.delete(`/api/settings/platforms/${platform.id}`)
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Не удалось удалить'
  }
}

async function addChannel(platform: Platform) {
  const chat = (chatDraft[platform.id] ?? '').trim()
  if (!chat) return

  error.value = ''
  try {
    await api.post<Channel>(`/api/settings/platforms/${platform.id}/channels`, { chat })
    chatDraft[platform.id] = ''
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Не удалось добавить канал'
  }
}

async function toggleChannel(channel: Channel) {
  try {
    await api.patch<Channel>(`/api/settings/platforms/channels/${channel.id}`, {
      is_enabled: !channel.is_enabled,
    })
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Не удалось изменить канал'
  }
}

async function checkChannel(channel: Channel) {
  busyId.value = channel.id
  try {
    await api.post<Channel>(`/api/settings/platforms/channels/${channel.id}/check`)
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Проверка не удалась'
  } finally {
    busyId.value = null
  }
}

async function removeChannel(channel: Channel) {
  if (!confirm(`Убрать ${channel.chat} из списка каналов?`)) return
  try {
    await api.delete(`/api/settings/platforms/channels/${channel.id}`)
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Не удалось убрать канал'
  }
}

async function testSubscriber(person: BotSubscriber) {
  error.value = ''
  try {
    const result = await api.post<{ detail: string }>(
      `/api/settings/schedule/subscribers/${person.id}/test`,
    )
    notice.value = result.detail
    await loadExtras()
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Не удалось отправить'
  }
}

async function removeSubscriber(person: BotSubscriber) {
  const who = person.username ? `@${person.username}` : person.chat_id
  if (!confirm(`Убрать ${who} из списка? Он вернётся, если снова напишет боту.`)) return
  try {
    await api.delete(`/api/settings/schedule/subscribers/${person.id}`)
    await loadExtras()
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Не удалось убрать'
  }
}

onMounted(async () => {
  await Promise.all([load(), loadExtras()])
})
</script>

<template>
  <div>
    <ToastStack
      :error="error"
      :notice="notice"
      @clear-error="error = ''"
      @clear-notice="notice = ''"
    />

    <div class="ws-control-bar">
      <span class="muted" style="font-size: 13px">
        Площадок: {{ platforms.length }} · каналов готово принимать: {{ readyCount }}
      </span>
      <span class="row-end">
        <button class="ws-btn ws-btn-primary" @click="showForm = !showForm">
          {{ showForm ? 'Отмена' : 'Добавить площадку' }}
        </button>
      </span>
    </div>

    <section v-if="showForm" class="ws-surface" style="margin-bottom: 16px; max-width: 860px">
      <div class="ws-surface-head"><h2 class="ws-surface-title">Новая площадка</h2></div>
      <form class="ws-surface-body stack" @submit.prevent="addPlatform">
        <div class="ws-field">
          <label class="ws-field-label">Мессенджер</label>
          <div>
            <UiSelect v-model="form.kind" :options="KINDS" />
            <small class="muted">{{ HINTS[form.kind] }}</small>
          </div>
        </div>
        <div class="ws-field">
          <label class="ws-field-label">Название</label>
          <input
            v-model="form.title"
            class="ws-input"
            maxlength="255"
            :placeholder="KIND_LABELS[form.kind]"
          />
        </div>
        <div class="ws-field">
          <label class="ws-field-label">Токен бота</label>
          <input
            v-model="form.token"
            class="ws-input"
            type="password"
            autocomplete="off"
            placeholder="Вставьте токен"
          />
        </div>
        <div class="row">
          <button class="ws-btn ws-btn-primary" type="submit">Добавить</button>
        </div>
      </form>
    </section>

    <div v-if="loading" class="ws-surface" style="max-width: 860px">
      <div class="ws-surface-body stack">
        <span class="skeleton skeleton-text" style="width: 30%" />
        <span class="skeleton skeleton-block" style="height: 90px" />
      </div>
    </div>

    <section
      v-for="platform in platforms"
      v-else
      :key="platform.id"
      class="ws-surface"
      style="margin-bottom: 16px; max-width: 860px"
    >
      <div class="ws-surface-head">
        <h2 class="ws-surface-title">
          <span class="platform-tag" :class="`is-${platform.kind}`">
            {{ KIND_LABELS[platform.kind] }}
          </span>
          {{ platform.title }}
        </h2>
        <span class="row" style="gap: 8px">
          <span class="ws-badge" :class="platform.bot_username ? 'healthy' : 'critical'">
            {{ platform.bot_username ? `@${platform.bot_username}` : 'Нет связи' }}
          </span>
          <span class="ws-badge" :class="platform.is_enabled ? 'healthy' : 'neutral'">
            {{ platform.is_enabled ? 'Публикуем' : 'Выключена' }}
          </span>
        </span>
      </div>

      <div class="ws-surface-body stack">
        <p class="muted" style="margin: 0; font-size: 12px">{{ HINTS[platform.kind] }}</p>

        <p v-if="platform.last_status" class="muted" style="margin: 0; font-size: 12px">
          {{ platform.last_status }}
          <template v-if="platform.last_checked_at">
            · проверено {{ formatDate(platform.last_checked_at) }}
          </template>
        </p>

        <div class="ws-field">
          <label class="ws-field-label">Токен бота</label>
          <div>
            <div class="row">
              <input
                v-model="tokenDraft[platform.id]"
                class="ws-input"
                style="flex: 1"
                type="password"
                autocomplete="off"
                :placeholder="
                  platform.token_set
                    ? `Токен сохранён (${platform.token_hint}) — оставьте пустым, чтобы не менять`
                    : 'Вставьте токен'
                "
              />
              <button
                class="ws-btn"
                type="button"
                :disabled="busyId === platform.id || !(tokenDraft[platform.id] ?? '').trim()"
                @click="saveToken(platform)"
              >
                Сохранить
              </button>
            </div>
            <small class="muted">Наружу токен не отдаётся: видны только последние символы.</small>
          </div>
        </div>

        <label class="row" style="gap: 8px; cursor: pointer">
          <span class="ui-check" :class="{ 'is-on': platform.is_enabled }">
            <input
              type="checkbox"
              :checked="platform.is_enabled"
              @change="toggleEnabled(platform)"
            />
            <NavIcon name="tick" />
          </span>
          <span>Отправлять посты на эту площадку</span>
        </label>

        <div class="row">
          <input
            v-model="chatDraft[platform.id]"
            class="ws-input"
            style="flex: 1"
            :placeholder="
              platform.kind === 'telegram'
                ? '@имя_канала или числовой идентификатор'
                : 'Идентификатор чата MAX'
            "
            @keydown.enter.prevent="addChannel(platform)"
          />
          <button
            class="ws-btn ws-btn-quiet"
            type="button"
            :disabled="!(chatDraft[platform.id] ?? '').trim()"
            @click="addChannel(platform)"
          >
            Добавить канал
          </button>
        </div>
      </div>

      <div v-if="!platform.channels.length" class="empty-state">Каналы ещё не добавлены.</div>

      <div v-else class="table-wrap">
        <table class="ws-table">
          <thead>
            <tr>
              <th>Канал</th>
              <th>Название</th>
              <th>Права бота</th>
              <th>Вещаем сюда</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="channel in platform.channels" :key="channel.id">
              <td class="mono cell-title">{{ channel.chat }}</td>
              <td data-label="Название">{{ channel.title || '—' }}</td>
              <td class="wrap" data-label="Права бота">
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
              <td class="wrap" data-label="Вещаем сюда">
                <label class="channel-switch">
                  <span class="ui-check" :class="{ 'is-on': channel.is_enabled }">
                    <input
                      type="checkbox"
                      :checked="channel.is_enabled"
                      @change="toggleChannel(channel)"
                    />
                    <NavIcon name="tick" />
                  </span>
                  <span>{{ channel.is_enabled ? 'Да' : 'Нет' }}</span>
                </label>
                <div
                  v-if="channel.is_enabled && channel.can_post === false"
                  class="muted"
                  style="font-size: 11px; margin-top: 4px"
                >
                  Отправка сюда сорвётся и остановит рассылку по остальным каналам
                </div>
              </td>
              <td>
                <div class="row-actions">
                  <button
                    class="icon-btn"
                    :class="{ 'is-busy': busyId === channel.id }"
                    :disabled="busyId === channel.id"
                    data-tip="Проверить права бота"
                    aria-label="Проверить права бота"
                    @click="checkChannel(channel)"
                  >
                    <NavIcon name="check" />
                  </button>
                  <button
                    class="icon-btn is-danger"
                    data-tip="Убрать из списка"
                    aria-label="Убрать канал из списка"
                    @click="removeChannel(channel)"
                  >
                    <NavIcon name="trash" />
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="ws-surface-body">
        <div class="row-actions">
          <button
            class="icon-btn"
            :class="{ 'is-busy': busyId === platform.id }"
            :disabled="busyId === platform.id || !platform.token_set"
            data-tip="Проверить токен"
            aria-label="Проверить токен площадки"
            @click="checkPlatform(platform)"
          >
            <NavIcon name="refresh" />
          </button>
          <button
            class="icon-btn is-danger"
            data-tip="Удалить площадку"
            aria-label="Удалить площадку"
            @click="removePlatform(platform)"
          >
            <NavIcon name="trash" />
          </button>
        </div>
      </div>
    </section>

    <!-- Подписчики бота: относятся к Telegram, но живут рядом с площадками -->
    <section class="ws-surface" style="max-width: 860px">
      <div class="ws-surface-head">
        <h2 class="ws-surface-title">Кому бот сообщает о новостях</h2>
        <span class="muted" style="font-size: 12px">
          подписано: {{ subscribers.filter((s) => s.notify && !s.is_blocked).length }}
        </span>
      </div>

      <div class="ws-surface-body">
        <p v-if="info?.webhook_url" class="alert alert-error" style="margin: 0">
          У бота включён вебхук на <b>{{ info.webhook_url }}</b>. Пока он стоит, Telegram
          не отдаёт нам сообщения людей, и подписаться через меню бота нельзя.
        </p>
        <p v-else class="alert alert-info" style="margin: 0">
          Человек подписывается сам: пишет боту команду «/start» и включает оповещения
          кнопкой. После каждого сбора бот присылает подписчикам сводку — сколько новостей
          пришло и из каких источников, сколько готово к публикации и сколько ещё
          не просмотрено.
        </p>
      </div>

      <div v-if="!subscribers.length" class="empty-state">Пока никто не подписан.</div>

      <div v-else class="table-wrap">
        <table class="ws-table">
          <thead>
            <tr>
              <th>Кто</th>
              <th>Оповещения</th>
              <th>Последняя сводка</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="person in subscribers" :key="person.id">
              <td class="cell-title">
                {{ person.full_name || '—' }}
                <div v-if="person.username" class="muted" style="font-size: 11px">
                  @{{ person.username }}
                </div>
              </td>
              <td data-label="Оповещения">
                <span
                  class="ws-badge"
                  :class="person.is_blocked ? 'critical' : person.notify ? 'healthy' : 'neutral'"
                >
                  {{
                    person.is_blocked
                      ? 'Заблокировал бота'
                      : person.notify
                        ? 'Включены'
                        : 'Выключены'
                  }}
                </span>
              </td>
              <td data-label="Последняя сводка">{{ formatDate(person.last_notified_at) }}</td>
              <td>
                <div class="row-actions">
                  <button
                    class="icon-btn"
                    data-tip="Отправить сводку сейчас"
                    aria-label="Отправить сводку сейчас"
                    @click="testSubscriber(person)"
                  >
                    <NavIcon name="bell" />
                  </button>
                  <button
                    class="icon-btn is-danger"
                    data-tip="Убрать из списка"
                    aria-label="Убрать подписчика из списка"
                    @click="removeSubscriber(person)"
                  >
                    <NavIcon name="trash" />
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>
