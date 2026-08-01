<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
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
const WIDTH_KEY = 'iskcon-sidebar-width'
const MIN_WIDTH = 180
const MAX_WIDTH = 420
const DEFAULT_WIDTH = 232

const width = ref(DEFAULT_WIDTH)
const dragging = ref(false)

function applyWidth() {
  const value = collapsed.value ? 66 : width.value
  document.documentElement.style.setProperty('--sidebar-width', `${value}px`)
  // Оболочка темы — грид, и колонка под панель берётся из этой переменной.
  // Менять ширину только у самого элемента недостаточно: трек останется
  // прежним, и содержимое залезет под панель.
  document.documentElement.style.setProperty('--ui-sidebar', `${value}px`)
}

onMounted(() => {
  collapsed.value = localStorage.getItem(COLLAPSE_KEY) === '1'
  const saved = Number(localStorage.getItem(WIDTH_KEY))
  if (Number.isFinite(saved) && saved >= MIN_WIDTH && saved <= MAX_WIDTH) width.value = saved
  applyWidth()
})

watch(collapsed, (value) => {
  applyWidth()
  try {
    localStorage.setItem(COLLAPSE_KEY, value ? '1' : '0')
  } catch {
    // приватный режим — состояние просто не переживёт перезагрузку
  }
})

// --- Растягивание панели ---------------------------------------------------

function onPointerMove(event: PointerEvent) {
  if (!dragging.value) return
  // Панель зумится вместе с оболочкой, поэтому переводим экранные
  // пиксели в её собственные, иначе рукоятка «убегает» от курсора.
  const scale = Number(getComputedStyle(document.documentElement).getPropertyValue('--ui-scale')) || 1
  width.value = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, event.clientX / scale))
  applyWidth()
}

function stopDrag() {
  if (!dragging.value) return
  dragging.value = false
  document.body.style.userSelect = ''
  try {
    localStorage.setItem(WIDTH_KEY, String(Math.round(width.value)))
  } catch {
    // приватный режим
  }
}

function startDrag(event: PointerEvent) {
  if (collapsed.value) return
  dragging.value = true
  document.body.style.userSelect = 'none'
  ;(event.target as HTMLElement).setPointerCapture?.(event.pointerId)
}

/** Клавиатурой — стрелками, шагом в 16 пикселей. */
function onHandleKeydown(event: KeyboardEvent) {
  const step = event.key === 'ArrowLeft' ? -16 : event.key === 'ArrowRight' ? 16 : 0
  if (!step) return
  event.preventDefault()
  width.value = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, width.value + step))
  applyWidth()
  try {
    localStorage.setItem(WIDTH_KEY, String(Math.round(width.value)))
  } catch {
    // приватный режим
  }
}

function resetWidth() {
  width.value = DEFAULT_WIDTH
  applyWidth()
  localStorage.setItem(WIDTH_KEY, String(DEFAULT_WIDTH))
}

/** На мобильном панель — выдвижная шторка: закрываем по Esc и по фону. */
function onShellKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') navOpen.value = false
}

watch(navOpen, (open) => {
  // Пока шторка открыта, страница под ней не прокручивается
  document.body.style.overflow = open ? 'hidden' : ''
})

onMounted(() => {
  window.addEventListener('keydown', onShellKeydown)
  window.addEventListener('pointermove', onPointerMove)
  window.addEventListener('pointerup', stopDrag)
  window.addEventListener('pointercancel', stopDrag)
})

onBeforeUnmount(() => {
  document.body.style.overflow = ''
  window.removeEventListener('keydown', onShellKeydown)
  window.removeEventListener('pointermove', onPointerMove)
  window.removeEventListener('pointerup', stopDrag)
  window.removeEventListener('pointercancel', stopDrag)
})
</script>

<template>
  <div class="ui-shell" :class="{ 'is-collapsed': collapsed, 'is-resizing': dragging }">
    <aside class="ui-sidebar" :class="{ open: navOpen }" aria-label="Основная навигация">
      <div class="brand-row">
        <!-- В свёрнутом виде логотип сам разворачивает панель:
             отдельная кнопка занимала бы вторую строку в узкой колонке -->
        <button
          v-if="collapsed"
          type="button"
          class="ui-brand brand-button"
          title="Развернуть меню"
          @click="collapsed = false"
        >
          <GarudaMark :size="34" plain style="color: var(--scheme-accent, #1768ff)" />
          <span class="sr-only">Развернуть меню</span>
        </button>

        <RouterLink
          v-else
          class="ui-brand"
          :to="{ name: 'articles' }"
          title="Новости ИСККОН"
        >
          <GarudaMark :size="34" plain style="color: var(--scheme-accent, #1768ff)" />
          <span class="ui-brand-copy">
            Новости ИСККОН
            <small>Портал публикаций</small>
          </span>
        </RouterLink>
        <button
          v-if="!collapsed"
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

      <!-- Прокручиваемая часть: при крупном масштабе пункты меню больше
           не выдавливают блок профиля за пределы экрана -->
      <div class="sidebar-scroll">
        <section class="ui-nav-section">
          <div class="ui-nav-label">Работа</div>
          <nav class="ui-nav-list">
            <RouterLink
              class="ui-nav-link"
              :to="{ name: 'articles' }"
              data-tip="Лента новостей"
              @click="navOpen = false"
            >
              <NavIcon name="feed" />
              <span>Лента новостей</span>
            </RouterLink>
            <RouterLink
              class="ui-nav-link"
              :to="{ name: 'sources' }"
              data-tip="Источники"
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
              :to="{ name: 'schedule' }"
              data-tip="Расписание сбора"
              @click="navOpen = false"
            >
              <NavIcon name="clock" />
              <span>Расписание сбора</span>
            </RouterLink>
            <RouterLink
              class="ui-nav-link"
              :to="{ name: 'prompts' }"
              data-tip="Промпты"
              @click="navOpen = false"
            >
              <NavIcon name="prompts" />
              <span>Промпты</span>
            </RouterLink>
            <RouterLink
              class="ui-nav-link"
              :to="{ name: 'llm-settings' }"
              data-tip="Настройки модели"
              @click="navOpen = false"
            >
              <NavIcon name="model" />
              <span>Настройки модели</span>
            </RouterLink>
            <RouterLink
              class="ui-nav-link"
              :to="{ name: 'platforms' }"
              data-tip="Площадки публикации"
              @click="navOpen = false"
            >
              <NavIcon name="telegram" />
              <span>Площадки публикации</span>
            </RouterLink>
            <RouterLink
              class="ui-nav-link"
              :to="{ name: 'audit' }"
              data-tip="Журнал действий"
              @click="navOpen = false"
            >
              <NavIcon name="audit" />
              <span>Журнал действий</span>
            </RouterLink>
            <RouterLink
              class="ui-nav-link"
              :to="{ name: 'users' }"
              data-tip="Пользователи"
              @click="navOpen = false"
            >
              <NavIcon name="users" />
              <span>Пользователи</span>
            </RouterLink>
          </nav>
        </section>
      </div>

      <ProfileMenu />

      <div
        v-if="!collapsed"
        class="sidebar-resizer"
        role="separator"
        aria-orientation="vertical"
        :aria-valuenow="Math.round(width)"
        :aria-valuemin="MIN_WIDTH"
        :aria-valuemax="MAX_WIDTH"
        tabindex="0"
        title="Потяните, чтобы изменить ширину. Двойной щелчок — вернуть по умолчанию"
        @pointerdown.prevent="startDrag"
        @dblclick="resetWidth"
        @keydown="onHandleKeydown"
      />
    </aside>

    <div v-if="navOpen" class="nav-scrim" @click="navOpen = false" />

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
            <h1 class="ui-page-title">{{ title }}</h1>
          </div>
        </div>
      </header>

      <slot />
    </main>
  </div>
</template>
