<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import {
  FONT_STEPS,
  UI_STEPS,
  fontBigger,
  fontSmaller,
  fontStep,
  percent,
  resetAppearance,
  setTheme,
  theme,
  uiBigger,
  uiStep,
  uiSmaller,
} from '@/appearance'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()

const open = ref(false)
const root = ref<HTMLElement | null>(null)

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

const fontAtMin = computed(() => fontStep.value === 0)
const fontAtMax = computed(() => fontStep.value === FONT_STEPS.length - 1)
const uiAtMin = computed(() => uiStep.value === 0)
const uiAtMax = computed(() => uiStep.value === UI_STEPS.length - 1)

const isDefault = computed(
  () => fontStep.value === FONT_STEPS.indexOf(1) && uiStep.value === UI_STEPS.indexOf(1),
)

function onPointerDown(event: PointerEvent) {
  if (!root.value?.contains(event.target as Node)) open.value = false
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') open.value = false
}

watch(open, (isOpen) => {
  if (isOpen) {
    document.addEventListener('pointerdown', onPointerDown, true)
    document.addEventListener('keydown', onKeydown)
  } else {
    document.removeEventListener('pointerdown', onPointerDown, true)
    document.removeEventListener('keydown', onKeydown)
  }
})

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onPointerDown, true)
  document.removeEventListener('keydown', onKeydown)
})

async function onLogout() {
  open.value = false
  await auth.logout()
  router.push({ name: 'login' })
}
</script>

<template>
  <div ref="root" class="profile-menu">
    <div v-if="open" class="profile-panel" role="menu">
      <div class="profile-panel-head">
        <b>{{ auth.user?.full_name || auth.user?.username }}</b>
        <small>{{ roleLabel }}</small>
      </div>

      <section class="profile-section">
        <div class="profile-section-title">Тема</div>
        <div class="profile-switch">
          <button
            type="button"
            :class="{ 'is-active': theme === 'light' }"
            @click="setTheme('light')"
          >
            Светлая
          </button>
          <button
            type="button"
            :class="{ 'is-active': theme === 'dark' }"
            @click="setTheme('dark')"
          >
            Тёмная
          </button>
        </div>
      </section>

      <section class="profile-section">
        <div class="profile-section-title">
          Размер шрифта
          <span class="profile-value">{{ percent(FONT_STEPS, fontStep) }}</span>
        </div>
        <div class="profile-stepper">
          <button type="button" :disabled="fontAtMin" aria-label="Уменьшить шрифт" @click="fontSmaller">
            А−
          </button>
          <span class="profile-bar" aria-hidden="true">
            <i
              v-for="(_, index) in FONT_STEPS"
              :key="index"
              :class="{ 'is-on': index <= fontStep }"
            />
          </span>
          <button type="button" :disabled="fontAtMax" aria-label="Увеличить шрифт" @click="fontBigger">
            А+
          </button>
        </div>
      </section>

      <section class="profile-section">
        <div class="profile-section-title">
          Масштаб интерфейса
          <span class="profile-value">{{ percent(UI_STEPS, uiStep) }}</span>
        </div>
        <div class="profile-stepper">
          <button type="button" :disabled="uiAtMin" aria-label="Уменьшить масштаб" @click="uiSmaller">
            −
          </button>
          <span class="profile-bar" aria-hidden="true">
            <i v-for="(_, index) in UI_STEPS" :key="index" :class="{ 'is-on': index <= uiStep }" />
          </span>
          <button type="button" :disabled="uiAtMax" aria-label="Увеличить масштаб" @click="uiBigger">
            +
          </button>
        </div>
      </section>

      <button
        type="button"
        class="profile-item"
        :disabled="isDefault"
        @click="resetAppearance"
      >
        Сбросить размеры
      </button>

      <button type="button" class="profile-item is-danger" @click="onLogout">Выйти</button>
    </div>

    <button
      type="button"
      class="ui-profile profile-trigger"
      :aria-expanded="open"
      aria-haspopup="menu"
      @click="open = !open"
    >
      <span class="ui-avatar">{{ initials }}</span>
      <span class="ui-profile-copy">
        <b>{{ auth.user?.full_name || auth.user?.username }}</b>
        <small>{{ roleLabel }}</small>
      </span>
      <span class="profile-caret" aria-hidden="true">⌄</span>
    </button>
  </div>
</template>
