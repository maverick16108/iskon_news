<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import GarudaMark from '@/components/GarudaMark.vue'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const username = ref('')
const password = ref('')
const error = ref('')
const busy = ref(false)

async function submit() {
  error.value = ''
  busy.value = true
  try {
    await auth.login(username.value.trim(), password.value)
    const redirect = route.query.redirect
    router.push(typeof redirect === 'string' ? redirect : { name: 'articles' })
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Не удалось войти'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="login-screen">
    <form class="login-card" @submit.prevent="submit">
      <div class="login-brand">
        <GarudaMark :size="52" plain style="color: var(--scheme-accent, #1768ff)" />
        <span>
          <div class="login-title">Новости ИСККОН</div>
          <div class="login-subtitle">Портал публикаций</div>
        </span>
      </div>

      <div class="stack">
        <div class="ws-field">
          <label class="ws-field-label" for="username">Логин</label>
          <input
            id="username"
            v-model="username"
            class="ws-input"
            autocomplete="username"
            required
            autofocus
          />
        </div>

        <div class="ws-field">
          <label class="ws-field-label" for="password">Пароль</label>
          <input
            id="password"
            v-model="password"
            class="ws-input"
            type="password"
            autocomplete="current-password"
            required
          />
        </div>

        <p v-if="error" class="alert alert-error">{{ error }}</p>

        <button class="ws-btn ws-btn-primary" type="submit" :disabled="busy">
          {{ busy ? 'Проверяем…' : 'Войти' }}
        </button>
      </div>
    </form>
  </div>
</template>
