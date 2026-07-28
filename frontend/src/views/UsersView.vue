<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import { api, type Role, type User } from '@/api'
import { ROLE_LABELS, formatDate } from '@/labels'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()

const users = ref<User[]>([])
const loading = ref(true)
const error = ref('')
const notice = ref('')
const showForm = ref(false)

const form = reactive({
  username: '',
  password: '',
  full_name: '',
  role: 'editor' as Role,
})

// Смена пароля существующему пользователю
const resetFor = ref<User | null>(null)
const newPassword = ref('')

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

async function changeRole(user: User, role: Role) {
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
  <div class="workspace-body" style="padding: 20px">
    <div class="ws-control-bar">
      <span class="muted" style="font-size: 13px">Всего учётных записей: {{ users.length }}</span>
      <span class="row-end">
        <button class="ws-btn ws-btn-primary" @click="showForm = !showForm">
          {{ showForm ? 'Отмена' : 'Добавить пользователя' }}
        </button>
      </span>
    </div>

    <p v-if="error" class="alert alert-error" style="margin-bottom: 12px">{{ error }}</p>
    <p v-if="notice" class="alert alert-success" style="margin-bottom: 12px">{{ notice }}</p>

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
          <select v-model="form.role" class="ws-select">
            <option value="editor">Редактор — работа с новостями</option>
            <option value="superadmin">
              Суперадминистратор — плюс пользователи и источники
            </option>
          </select>
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

      <div v-if="loading" class="spinner-line">Загружаем…</div>

      <div v-else class="table-wrap">
        <table class="ws-table">
          <thead>
            <tr>
              <th>Логин</th>
              <th>Имя</th>
              <th>Роль</th>
              <th>Создан</th>
              <th>Последний вход</th>
              <th>Состояние</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="user in users" :key="user.id">
              <td>
                <b>{{ user.username }}</b>
                <span v-if="user.id === auth.user?.id" class="muted"> — это вы</span>
              </td>
              <td>{{ user.full_name || '—' }}</td>
              <td>
                <select
                  class="ws-select ws-control-sm"
                  :value="user.role"
                  :disabled="user.id === auth.user?.id"
                  @change="changeRole(user, ($event.target as HTMLSelectElement).value as Role)"
                >
                  <option value="editor">{{ ROLE_LABELS.editor }}</option>
                  <option value="superadmin">{{ ROLE_LABELS.superadmin }}</option>
                </select>
              </td>
              <td>{{ formatDate(user.created_at) }}</td>
              <td>{{ formatDate(user.last_login_at) }}</td>
              <td>
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
