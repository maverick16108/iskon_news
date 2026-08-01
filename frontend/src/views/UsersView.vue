<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { api, type Role, type User } from '@/api'
import TableSkeleton from '@/components/TableSkeleton.vue'
import ToastStack from '@/components/ToastStack.vue'
import UiSelect from '@/components/UiSelect.vue'
import type { SelectOption } from '@/components/select'
import { ROLE_LABELS, formatDate } from '@/labels'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()

const users = ref<User[]>([])
const loading = ref(true)
const error = ref('')
const notice = ref('')
const showForm = ref(false)

type SortKey = 'username' | 'full_name' | 'role' | 'created' | 'login' | 'state'
const sortKey = ref<SortKey>('created')
const sortAsc = ref(false)

const COLUMNS: { key: SortKey; label: string }[] = [
  { key: 'username', label: 'Логин' },
  { key: 'full_name', label: 'Имя' },
  { key: 'role', label: 'Роль' },
  { key: 'created', label: 'Создан' },
  { key: 'login', label: 'Последний вход' },
  { key: 'state', label: 'Состояние' },
]

const ROLE_OPTIONS: SelectOption[] = [
  { value: 'editor', label: ROLE_LABELS.editor, hint: 'Работа с новостями' },
  {
    value: 'superadmin',
    label: ROLE_LABELS.superadmin,
    hint: 'Плюс пользователи и источники',
  },
]

const form = reactive({
  username: '',
  password: '',
  full_name: '',
  role: 'editor' as Role,
})

const resetFor = ref<User | null>(null)
const newPassword = ref('')

function sortValue(user: User, key: SortKey): string | number {
  switch (key) {
    case 'username':
      return user.username.toLowerCase()
    case 'full_name':
      return (user.full_name ?? '').toLowerCase()
    case 'role':
      return user.role
    case 'created':
      return Date.parse(user.created_at)
    case 'login':
      return user.last_login_at ? Date.parse(user.last_login_at) : 0
    case 'state':
      return user.is_active ? 1 : 0
  }
}

const sorted = computed(() => {
  const factor = sortAsc.value ? 1 : -1
  return [...users.value].sort((a, b) => {
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
    sortAsc.value = !['created', 'login'].includes(key)
  }
}

function ariaSort(key: SortKey) {
  if (sortKey.value !== key) return 'none'
  return sortAsc.value ? 'ascending' : 'descending'
}

async function load() {
  loading.value = true
  try {
    users.value = await api.get<User[]>('/api/users')
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Не удалось загрузить пользователей'
  } finally {
    loading.value = false
  }
}

async function create() {
  error.value = ''
  notice.value = ''
  try {
    await api.post<User>('/api/users', {
      username: form.username.trim(),
      password: form.password,
      full_name: form.full_name.trim() || null,
      role: form.role,
    })
    notice.value = `Пользователь «${form.username}» создан`
    Object.assign(form, { username: '', password: '', full_name: '', role: 'editor' })
    showForm.value = false
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Не удалось создать пользователя'
  }
}

async function toggleActive(user: User) {
  error.value = ''
  try {
    await api.patch<User>(`/api/users/${user.id}`, { is_active: !user.is_active })
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Не удалось изменить пользователя'
  }
}

async function changeRole(user: User, role: string | number) {
  error.value = ''
  try {
    await api.patch<User>(`/api/users/${user.id}`, { role })
    notice.value = `Роль пользователя «${user.username}» изменена`
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Не удалось изменить роль'
    await load()
  }
}

async function resetPassword() {
  if (!resetFor.value) return
  error.value = ''
  try {
    await api.patch<User>(`/api/users/${resetFor.value.id}`, { password: newPassword.value })
    notice.value = `Пароль для «${resetFor.value.username}» изменён, его сессии завершены`
    resetFor.value = null
    newPassword.value = ''
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Не удалось сменить пароль'
  }
}

async function remove(user: User) {
  if (!confirm(`Удалить пользователя «${user.username}»?`)) return
  error.value = ''
  try {
    await api.delete(`/api/users/${user.id}`)
    notice.value = `Пользователь «${user.username}» удалён`
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Не удалось удалить пользователя'
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="ws-control-bar">
      <span class="muted" style="font-size: 13px">Всего учётных записей: {{ users.length }}</span>
      <span class="row-end">
        <button class="ws-btn ws-btn-primary" @click="showForm = !showForm">
          {{ showForm ? 'Отмена' : 'Добавить пользователя' }}
        </button>
      </span>
    </div>

    <ToastStack
      :error="error"
      :notice="notice"
      @clear-error="error = ''"
      @clear-notice="notice = ''"
    />

    <section v-if="showForm" class="ws-surface" style="margin-bottom: 16px">
      <div class="ws-surface-head"><h2 class="ws-surface-title">Новый пользователь</h2></div>
      <form class="ws-surface-body stack" @submit.prevent="create">
        <div class="ws-field">
          <label class="ws-field-label">Логин</label>
          <input
            v-model="form.username"
            class="ws-input"
            required
            minlength="3"
            pattern="[a-zA-Z0-9_.\-]+"
            placeholder="латиница, цифры, точка, дефис"
          />
        </div>
        <div class="ws-field">
          <label class="ws-field-label">Пароль</label>
          <input
            v-model="form.password"
            class="ws-input"
            type="password"
            required
            minlength="8"
            placeholder="не короче 8 символов"
          />
        </div>
        <div class="ws-field">
          <label class="ws-field-label">Имя (необязательно)</label>
          <input v-model="form.full_name" class="ws-input" />
        </div>
        <div class="ws-field">
          <label class="ws-field-label">Роль</label>
          <UiSelect v-model="form.role" :options="ROLE_OPTIONS" />
        </div>
        <div class="row">
          <button class="ws-btn ws-btn-primary" type="submit">Создать</button>
        </div>
      </form>
    </section>

    <section v-if="resetFor" class="ws-surface" style="margin-bottom: 16px">
      <div class="ws-surface-head">
        <h2 class="ws-surface-title">Новый пароль для «{{ resetFor.username }}»</h2>
      </div>
      <form class="ws-surface-body row" @submit.prevent="resetPassword">
        <input
          v-model="newPassword"
          class="ws-input"
          type="password"
          required
          minlength="8"
          placeholder="не короче 8 символов"
          style="flex: 1"
        />
        <button class="ws-btn ws-btn-primary" type="submit">Сменить</button>
        <button class="ws-btn ws-btn-quiet" type="button" @click="resetFor = null">Отмена</button>
      </form>
    </section>

    <section class="ws-surface">
      <div class="ws-surface-head"><h2 class="ws-surface-title">Пользователи</h2></div>

      <TableSkeleton v-if="loading" :columns="[15, 18, 20, 15, 15, 10, 12]" :rows="4" />

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
            <tr v-for="user in sorted" :key="user.id">
              <td class="cell-title">
                <b>{{ user.username }}</b>
                <span v-if="user.id === auth.user?.id" class="muted"> — это вы</span>
              </td>
              <td data-label="Имя">{{ user.full_name || '—' }}</td>
              <td data-label="Роль">
                <UiSelect
                  :model-value="user.role"
                  :options="ROLE_OPTIONS"
                  :disabled="user.id === auth.user?.id"
                  small
                  @update:model-value="changeRole(user, $event)"
                />
              </td>
              <td data-label="Заведён">{{ formatDate(user.created_at) }}</td>
              <td data-label="Последний вход">{{ formatDate(user.last_login_at) }}</td>
              <td data-label="Состояние">
                <span class="ws-badge" :class="user.is_active ? 'healthy' : 'neutral'">
                  {{ user.is_active ? 'Активен' : 'Отключён' }}
                </span>
              </td>
              <td>
                <div class="row" style="gap: 6px; justify-content: flex-end">
                  <button
                    class="ws-btn ws-btn-quiet"
                    @click="((resetFor = user), (newPassword = ''))"
                  >
                    Пароль
                  </button>
                  <button
                    class="ws-btn ws-btn-quiet"
                    :disabled="user.id === auth.user?.id"
                    @click="toggleActive(user)"
                  >
                    {{ user.is_active ? 'Отключить' : 'Включить' }}
                  </button>
                  <button
                    class="ws-btn ws-btn-danger"
                    :disabled="user.id === auth.user?.id"
                    @click="remove(user)"
                  >
                    Удалить
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
