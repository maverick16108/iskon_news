/** Настройки внешнего вида: тема и масштаб.
 *
 * Масштаб один на всё — zoom по оболочке увеличивает и текст, и отступы,
 * и элементы управления. Отдельный регулятор шрифта только путал.
 *
 * Состояние на уровне модуля: оно одно на приложение и переживает
 * перемонтирование компонентов. Значения хранятся в localStorage.
 */

import { ref, watch } from 'vue'

export type Theme = 'light' | 'dark'

const STORAGE_KEY = 'iskcon-appearance'

export const SCALE_STEPS = [0.8, 0.9, 1, 1.1, 1.25, 1.4] as const
const DEFAULT_STEP = SCALE_STEPS.indexOf(1)

interface Appearance {
  theme: Theme
  scaleStep: number
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, Math.round(value)))
}

function load(): Appearance {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return { theme: 'light', scaleStep: DEFAULT_STEP }

    const saved = JSON.parse(raw) as Partial<Appearance> & { uiStep?: number }
    return {
      theme: saved.theme === 'dark' ? 'dark' : 'light',
      // uiStep — из прежней версии с двумя регуляторами
      scaleStep: clamp(saved.scaleStep ?? saved.uiStep ?? DEFAULT_STEP, 0, SCALE_STEPS.length - 1),
    }
  } catch {
    return { theme: 'light', scaleStep: DEFAULT_STEP }
  }
}

const initial = load()

export const theme = ref<Theme>(initial.theme)
export const scaleStep = ref(initial.scaleStep)

export function apply() {
  const root = document.documentElement
  root.dataset.theme = theme.value
  root.style.setProperty('--ui-scale', String(SCALE_STEPS[scaleStep.value]))
}

function persist() {
  try {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ theme: theme.value, scaleStep: scaleStep.value }),
    )
  } catch {
    // Приватный режим браузера — настройки просто не переживут перезагрузку
  }
}

watch([theme, scaleStep], () => {
  apply()
  persist()
})

export function setTheme(value: Theme) {
  theme.value = value
}

export function scaleUp() {
  scaleStep.value = Math.min(SCALE_STEPS.length - 1, scaleStep.value + 1)
}

export function scaleDown() {
  scaleStep.value = Math.max(0, scaleStep.value - 1)
}

export function resetScale() {
  scaleStep.value = DEFAULT_STEP
}

export const isDefaultScale = () => scaleStep.value === DEFAULT_STEP

export function scalePercent() {
  return `${Math.round(SCALE_STEPS[scaleStep.value] * 100)}%`
}
