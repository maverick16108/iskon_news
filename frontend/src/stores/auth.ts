import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

import { api, ApiError, type User } from '@/api'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<User | null>(null)
  const checked = ref(false)

  const isAuthenticated = computed(() => user.value !== null)
  const isSuperadmin = computed(() => user.value?.role === 'superadmin')

  async function login(username: string, password: string) {
    user.value = await api.post<User>('/api/auth/login', { username, password })
    checked.value = true
  }

  async function logout() {
    try {
      await api.post('/api/auth/logout')
    } finally {
      user.value = null
    }
  }

  /** Восстанавливает сессию по куке при загрузке страницы. */
  async function restore() {
    if (checked.value) return
    try {
      user.value = await api.get<User>('/api/auth/me')
    } catch (error) {
      if (!(error instanceof ApiError && error.status === 401)) {
        console.error('Не удалось восстановить сессию:', error)
      }
      user.value = null
    } finally {
      checked.value = true
    }
  }

  return { user, checked, isAuthenticated, isSuperadmin, login, logout, restore }
})
