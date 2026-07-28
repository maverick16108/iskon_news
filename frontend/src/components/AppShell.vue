<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const navOpen = ref(false)

// Тема UIUIDS умеет светлую и тёмную схему через html[data-theme]
const dark = ref(false)

function applyTheme() {
  document.documentElement.dataset.theme = dark.value ? 'dark' : 'light'
  localStorage.setItem('iskcon-theme', dark.value ? 'dark' : 'light')
}

function toggleTheme() {
  dark.value = !dark.value
  applyTheme()
}

onMounted(() => {
  dark.value = localStorage.getItem('iskcon-theme') === 'dark'
  applyTheme()
})

const title = computed(() => (route.meta.title as string) ?? 'Новости ИСККОН')

const initials = computed(() => {
  const source = auth.user?.full_name || auth.user?.username || '?'
  return source
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? '')
    .join('')
})

const roleLabel = computed(() =>
  auth.user?.role === 'superadmin' ? 'Суперадминистратор' : 'Редактор',
)

async function onLogout() {
  await auth.logout()
  router.push({ name: 'login' })
}
</script>

<template>
  <div class="ui-shell">
    <aside class="ui-sidebar" :class="{ 'is-visible': navOpen }" aria-label="Основная навигация">
      <RouterLink class="ui-brand" :to="{ name: 'articles' }">
        <span class="ui-brand-mark">ИН</span>
        <span class="ui-brand-copy">
          Новости ИСККОН
          <small>Редакция канала</small>
        </span>
      </RouterLink>

      <section class="ui-nav-section">
        <div class="ui-nav-label">Работа</div>
        <nav class="ui-nav-list">
          <RouterLink class="ui-nav-link" :to="{ name: 'articles' }" @click="navOpen = false">
            <span>Лента новостей</span>
          </RouterLink>
          <RouterLink class="ui-nav-link" :to="{ name: 'sources' }" @click="navOpen = false">
            <span>Источники</span>
          </RouterLink>
        </nav>
      </section>

      <section v-if="auth.isSuperadmin" class="ui-nav-section">
        <div class="ui-nav-label">Администрирование</div>
        <nav class="ui-nav-list">
          <RouterLink class="ui-nav-link" :to="{ name: 'users' }" @click="navOpen = false">
            <span>Пользователи</span>
          </RouterLink>
          <RouterLink class="ui-nav-link" :to="{ name: 'audit' }" @click="navOpen = false">
            <span>Журнал действий</span>
          </RouterLink>
        </nav>
      </section>

      <button class="ui-theme-toggle" type="button" :aria-pressed="dark" @click="toggleTheme">
        <span class="ui-theme-icon" aria-hidden="true">◐</span>
        <span>{{ dark ? 'Светлая тема' : 'Тёмная тема' }}</span>
      </button>

      <div class="ui-profile">
        <span class="ui-avatar">{{ initials }}</span>
        <span class="ui-profile-copy">
          <b>{{ auth.user?.full_name || auth.user?.username }}</b>
          <small>{{ roleLabel }}</small>
        </span>
        <button type="button" aria-label="Выйти из системы" title="Выйти" @click="onLogout">
          ⏻
        </button>
      </div>
    </aside>

    <main class="ui-main">
      <header class="ui-page-header">
        <div class="ui-title-row">
          <button
            type="button"
            class="ui-mobile-menu"
            :aria-expanded="navOpen"
            @click="navOpen = !navOpen"
          >
            ☰<span class="sr-only">Открыть навигацию</span>
          </button>
          <div class="ui-page-heading">
            <div class="ui-eyebrow">t.me/iskconru</div>
            <h1 class="ui-page-title">{{ title }}</h1>
          </div>
        </div>
      </header>

      <slot />
    </main>
  </div>
</template>
