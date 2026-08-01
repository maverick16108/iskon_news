<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

/** Поле даты со своим календарём.
 *
 * Системный из <input type="date"> выглядит чужеродно: у каждой платформы
 * свой, и в тёмной теме он остаётся светлым. Здесь та же логика, но своя
 * разметка — как и с выпадающими списками.
 *
 * Значение наружу отдаём строкой ГГГГ-ММ-ДД: в таком виде его ждёт бэкенд,
 * и в таком же виде хранит <input type="date">, если понадобится вернуться.
 */
const props = defineProps<{ modelValue: string; disabled?: boolean; placeholder?: string }>()
const emit = defineEmits<{ 'update:modelValue': [string] }>()

const MONTHS = [
  'январь', 'февраль', 'март', 'апрель', 'май', 'июнь',
  'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь',
]
const WEEKDAYS = ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс']

const open = ref(false)
const root = ref<HTMLElement | null>(null)

// Какой месяц показан в календаре — не то же, что выбранная дата
const shownYear = ref(new Date().getFullYear())
const shownMonth = ref(new Date().getMonth())

const selected = computed(() => {
  const [y, m, d] = props.modelValue.split('-').map(Number)
  return props.modelValue && y ? new Date(y, m - 1, d) : null
})

const label = computed(() => {
  const date = selected.value
  if (!date) return props.placeholder || 'Не задана'
  return date.toLocaleDateString('ru-RU')
})

/** Дни месяца плюс хвосты соседних, чтобы сетка была прямоугольной. */
const days = computed(() => {
  const first = new Date(shownYear.value, shownMonth.value, 1)
  // В России неделя начинается с понедельника, а getDay() считает с воскресенья
  const shift = (first.getDay() + 6) % 7

  const cells: { date: Date; outside: boolean }[] = []
  for (let i = 0; i < 42; i += 1) {
    const date = new Date(shownYear.value, shownMonth.value, 1 - shift + i)
    cells.push({ date, outside: date.getMonth() !== shownMonth.value })
  }
  return cells
})

const today = new Date()

function isSame(a: Date, b: Date | null) {
  return (
    !!b &&
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  )
}

function toValue(date: Date) {
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${date.getFullYear()}-${month}-${day}`
}

function pick(date: Date) {
  emit('update:modelValue', toValue(date))
  open.value = false
}

function shiftMonth(step: number) {
  const date = new Date(shownYear.value, shownMonth.value + step, 1)
  shownYear.value = date.getFullYear()
  shownMonth.value = date.getMonth()
}

function toggle() {
  if (props.disabled) return
  open.value = !open.value
}

function clear() {
  emit('update:modelValue', '')
  open.value = false
}

// Открывая календарь, показываем месяц выбранной даты, а не текущий
watch(open, (value) => {
  if (!value) return
  const date = selected.value ?? new Date()
  shownYear.value = date.getFullYear()
  shownMonth.value = date.getMonth()
})

function onDocumentClick(event: MouseEvent) {
  if (!root.value?.contains(event.target as Node)) open.value = false
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') open.value = false
}

onMounted(() => {
  document.addEventListener('click', onDocumentClick)
  document.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  document.removeEventListener('click', onDocumentClick)
  document.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <div ref="root" class="ui-date">
    <button
      type="button"
      class="ws-input ui-date-field"
      :class="{ 'is-empty': !modelValue }"
      :disabled="disabled"
      :aria-expanded="open"
      @click.stop="toggle"
    >
      <span>{{ label }}</span>
      <svg class="ui-date-icon" viewBox="0 0 20 20" fill="none" stroke="currentColor" aria-hidden="true">
        <rect x="3" y="4.5" width="14" height="12" rx="2" stroke-width="1.5" />
        <path d="M3 8h14M7 3v3M13 3v3" stroke-width="1.5" stroke-linecap="round" />
      </svg>
    </button>

    <div v-if="open" class="ui-date-pop" @click.stop>
      <div class="ui-date-head">
        <button type="button" class="ui-date-nav" title="Предыдущий месяц" @click="shiftMonth(-1)">
          ‹
        </button>
        <span class="ui-date-title">{{ MONTHS[shownMonth] }} {{ shownYear }}</span>
        <button type="button" class="ui-date-nav" title="Следующий месяц" @click="shiftMonth(1)">
          ›
        </button>
      </div>

      <div class="ui-date-grid">
        <span v-for="name in WEEKDAYS" :key="name" class="ui-date-weekday">{{ name }}</span>
        <button
          v-for="cell in days"
          :key="cell.date.toISOString()"
          type="button"
          class="ui-date-day"
          :class="{
            'is-outside': cell.outside,
            'is-today': isSame(cell.date, today),
            'is-selected': isSame(cell.date, selected),
          }"
          @click="pick(cell.date)"
        >
          {{ cell.date.getDate() }}
        </button>
      </div>

      <div class="ui-date-foot">
        <button type="button" class="ws-btn ws-btn-quiet" @click="clear">Очистить</button>
        <button type="button" class="ws-btn ws-btn-quiet" @click="pick(new Date())">Сегодня</button>
      </div>
    </div>
  </div>
</template>
