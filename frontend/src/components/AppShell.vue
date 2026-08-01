<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import GarudaMark from '@/components/GarudaMark.vue'
import NavIcon from '@/components/NavIcon.vue'
import ProfileMenu from '@/components/ProfileMenu.vue'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const route = useRoute()
const navOpen = ref(false)
const collapsed = ref(false)

const title = computed(() => (route.meta.title as string) ?? 'Новости ИСККОН')

const COLLAPSE_KEY = 'iskcon-sidebar-collapsed'

onMounted(() => {
  collapsed.value = localStorage.getItem(COLLAPSE_KEY) === '1'
})

watch(collapsed, (value) => {
  try {
    localStorage.setItem(COLLAPSE_KEY, value ? '1' : '0')
  } catch {
    // приватный режим — состояние просто не переживёт перезагрузку
  }
})
</script>

<template>
  <div class="ui-shell" :class="{ 'is-collapsed': collapsed }">
    <aside class="ui-sidebar" :class="{ 'is-visible': navOpen }" aria-label="Основная навигация">
      <div class="brand-row">
        <RouterLink class="ui-brand" :to="{ name: 'articles' }" :title="'Новости ИСККОН'">
          <GarudaMark :size="26" style="color: var(--scheme-accent, #1768ff)" />
          <span class="ui-brand-copy">
            Новости ИСККОН
            <small>Редакция канала</small>
          </span>
        </RouterLink>
        <button
          type="button"
          class="sidebar-toggle"
          :aria-expanded="!collapsed"
          :title="collapsed ? 'Развернуть меню' : 'Свернуть меню'"
          @click="collapsed = !collapsed"
        >
          <NavIcon name="collapse" />
          <span class="sr-only">{{ collapsed ? 'Развернуть меню' : 'Свернуть меню' }}</span>
        </button>
      </div>

      <section class="ui-nav-section">
        <div class="ui-nav-label">Работа</div>
        <nav class="ui-nav-list">
          <RouterLink
            class="ui-nav-link"
            :to="{ name: 'articles' }"
            title="Лента новостей"
            @click="navOpen = false"
          >
            <NavIcon name="feed" />
            <span>Лента новостей</span>
          </RouterLink>
          <RouterLink
            class="ui-nav-link"
            :to="{ name: 'sources' }"
            title="Источники"
            @click="navOpen = false"
          >
            <NavIcon name="sources" />
            <span>Источники</span>
          </RouterLink>
        </nav>
      </section>

      <section v-if="auth.isSuperadmin" class="ui-nav-section">
        <div class="ui-nav-label">Администрирование</div>
        <nav class="ui-nav-list">
          <RouterLink
            class="ui-nav-link"
            :to="{ name: 'users' }"
            title="Пользователи"
            @click="navOpen = false"
          >
            <NavIcon name="users" />
            <span>Пользователи</span>
          </RouterLink>
          <RouterLink
            class="ui-nav-link"
            :to="{ name: 'prompts' }"
            title="Промпты"
            @click="navOpen = false"
          >
            <NavIcon name="prompts" />
            <span>Промпты</span>
          </RouterLink>
          <RouterLink
            class="ui-nav-link"
            :to="{ name: 'llm-settings' }"
            title="Настройки модели"
            @click="navOpen = false"
          >
            <NavIcon name="model" />
            <span>Настройки модели</span>
          </RouterLink>
          <RouterLink
            class="ui-nav-link"
            :to="{ name: 'audit' }"
            title="Журнал действий"
            @click="navOpen = false"
          >
            <NavIcon name="audit" />
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
