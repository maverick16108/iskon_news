/** Настройки внешнего вида: тема, размер шрифта, масштаб интерфейса.
 *
 * Состояние на уровне модуля — оно одно на всё приложение и переживает
 * перемонтирование компонентов. Значения хранятся в localStorage.
 */

import { ref, watch } from 'vue'

export type Theme = 'light' | 'dark'

const STORAGE_KEY = 'iskcon-appearance'

// Шрифт масштабируем через токены темы, а не зумом: так текст растёт,
// а разметка остаётся на месте.
export const FONT_STEPS = [0.85, 0.92, 1, 1.1, 1.2, 1.35] as const
// Масштаб интерфейса — zoom по всей оболочке, растут и отступы, и контролы.
export const UI_STEPS = [0.8, 0.9, 1, 1.1, 1.25, 1.5] as const

interface Appearance {
  theme: Theme
  fontStep: number
  uiStep: number
}

const DEFAULTS: Appearance = {
  theme: 'light',
  fontStep: FONT_STEPS.indexOf(1),
  uiStep: UI_STEPS.indexOf(1),
}

function load(): Appearance {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return { ...DEFAULTS }
    const saved = JSON.parse(raw) as Partial<Appearance>
    return {
      theme: saved.theme === 'dark' ? 'dark' : 'light',
      fontStep: clamp(saved.fontStep ?? DEFAULTS.fontStep, 0, FONT_STEPS.length - 1),
      uiStep: clamp(saved.uiStep ?? DEFAULTS.uiStep, 0, UI_STEPS.length - 1),
    }
  } catch {
    return { ...DEFAULTS }
  }
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, Math.round(value)))
}

const initial = load()

export const theme = ref<Theme>(initial.theme)
export const fontStep = ref(initial.fontStep)
export const uiStep = ref(initial.uiStep)

export function apply() {
  const root = document.documentElement
  root.dataset.theme = theme.value
  root.style.setProperty('--font-scale', String(FONT_STEPS[fontStep.value]))
  root.style.setProperty('--ui-scale', String(UI_STEPS[uiStep.value]))
}

function persist() {
  try {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ theme: theme.value, fontStep: fontStep.value, uiStep: uiStep.value }),
    )
  } catch {
    // Приватный режим браузера — настройки просто не переживут перезагрузку
  }
}

watch([theme, fontStep, uiStep], () => {
  apply()
  persist()
})

export function toggleTheme() {
  theme.value = theme.value === 'dark' ? 'light' : 'dark'
}

export function setTheme(value: Theme) {
  theme.value = value
}

export function fontBigger() {
  fontStep.value = Math.min(FONT_STEPS.length - 1, fontStep.value + 1)
}

export function fontSmaller() {
  fontStep.value = Math.max(0, fontStep.value - 1)
}

export function uiBigger() {
  uiStep.value = Math.min(UI_STEPS.length - 1, uiStep.value + 1)
}

export function uiSmaller() {
  uiStep.value = Math.max(0, uiStep.value - 1)
}

export function resetAppearance() {
  fontStep.value = DEFAULTS.fontStep
  uiStep.value = DEFAULTS.uiStep
}

export function percent(steps: readonly number[], index: number) {
  return `${Math.round(steps[index] * 100)}%`
}
