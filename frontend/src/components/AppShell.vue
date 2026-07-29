<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'

import ProfileMenu from '@/components/ProfileMenu.vue'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const route = useRoute()
const navOpen = ref(false)

const title = computed(() => (route.meta.title as string) ?? 'Новости ИСККОН')
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
          <RouterLink class="ui-nav-link" :to="{ name: 'llm-settings' }" @click="navOpen = false">
            <span>Настройки модели</span>
          </RouterLink>
          <RouterLink class="ui-nav-link" :to="{ name: 'audit' }" @click="navOpen = false">
            <span>Журнал действий</span>
          </RouterLink>
        </nav>
      </section>

      <ProfileMenu />
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
