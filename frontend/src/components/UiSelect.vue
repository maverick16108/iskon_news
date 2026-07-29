<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'

import type { SelectOption } from '@/components/select'

const props = withDefaults(
  defineProps<{
    modelValue: string | number
    options: SelectOption[]
    disabled?: boolean
    placeholder?: string
    small?: boolean
    /** Ширина по содержимому вместо растягивания на всю строку */
    auto?: boolean
  }>(),
  { disabled: false, placeholder: 'Выберите', small: false, auto: false },
)

const emit = defineEmits<{ 'update:modelValue': [string | number] }>()

const open = ref(false)
const activeIndex = ref(-1)
const trigger = ref<HTMLButtonElement | null>(null)
const list = ref<HTMLUListElement | null>(null)

// Список рендерится через Teleport в body: иначе его обрезает
// горизонтальная прокрутка таблиц (.table-wrap { overflow-x: auto }).
const pos = ref({ top: 0, left: 0, width: 0, maxHeight: 280, above: false })

const selected = computed(() => props.options.find((o) => o.value === props.modelValue))
const label = computed(() => selected.value?.label ?? props.placeholder)

function updatePosition() {
  const el = trigger.value
  if (!el) return

  const rect = el.getBoundingClientRect()
  const gap = 4
  const below = window.innerHeight - rect.bottom - gap - 8
  const above = rect.top - gap - 8
  const wanted = props.options.length * 32 + 10

  const openAbove = below < Math.min(wanted, 180) && above > below

  pos.value = {
    top: openAbove ? Math.max(8, rect.top - gap - Math.min(wanted, above)) : rect.bottom + gap,
    left: rect.left,
    width: rect.width,
    maxHeight: Math.max(120, Math.min(280, openAbove ? above : below)),
    above: openAbove,
  }
}

async function openList() {
  if (props.disabled) return
  updatePosition()
  open.value = true
  activeIndex.value = props.options.findIndex((o) => o.value === props.modelValue)
  await nextTick()
  scrollActiveIntoView()
}

function closeList() {
  open.value = false
  activeIndex.value = -1
}

function toggle() {
  open.value ? closeList() : openList()
}

function choose(option: SelectOption) {
  emit('update:modelValue', option.value)
  closeList()
  trigger.value?.focus()
}

function scrollActiveIntoView() {
  if (activeIndex.value < 0) return
  const node = list.value?.children[activeIndex.value] as HTMLElement | undefined
  node?.scrollIntoView({ block: 'nearest' })
}

function move(step: number) {
  if (!props.options.length) return
  const next = activeIndex.value + step
  activeIndex.value = (next + props.options.length) % props.options.length
  scrollActiveIntoView()
}

function onKeydown(event: KeyboardEvent) {
  if (props.disabled) return

  if (!open.value) {
    if (['Enter', ' ', 'ArrowDown', 'ArrowUp'].includes(event.key)) {
      event.preventDefault()
      openList()
    }
    return
  }

  switch (event.key) {
    case 'Escape':
      event.preventDefault()
      closeList()
      trigger.value?.focus()
      break
    case 'ArrowDown':
      event.preventDefault()
      move(1)
      break
    case 'ArrowUp':
      event.preventDefault()
      move(-1)
      break
    case 'Home':
      event.preventDefault()
      activeIndex.value = 0
      scrollActiveIntoView()
      break
    case 'End':
      event.preventDefault()
      activeIndex.value = props.options.length - 1
      scrollActiveIntoView()
      break
    case 'Enter':
    case ' ':
      event.preventDefault()
      if (activeIndex.value >= 0) choose(props.options[activeIndex.value])
      break
    case 'Tab':
      closeList()
      break
  }
}

function onDocumentPointerDown(event: PointerEvent) {
  const target = event.target as Node
  if (trigger.value?.contains(target) || list.value?.contains(target)) return
  closeList()
}

// Список позиционируется фиксированно, поэтому при прокрутке страницы
// его надо либо двигать, либо закрывать. Закрываем — так предсказуемее.
function onScrollOrResize() {
  if (open.value) closeList()
}

watch(open, (isOpen) => {
  if (isOpen) {
    document.addEventListener('pointerdown', onDocumentPointerDown, true)
    window.addEventListener('scroll', onScrollOrResize, true)
    window.addEventListener('resize', onScrollOrResize)
  } else {
    document.removeEventListener('pointerdown', onDocumentPointerDown, true)
    window.removeEventListener('scroll', onScrollOrResize, true)
    window.removeEventListener('resize', onScrollOrResize)
  }
})

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onDocumentPointerDown, true)
  window.removeEventListener('scroll', onScrollOrResize, true)
  window.removeEventListener('resize', onScrollOrResize)
})
</script>

<template>
  <button
    ref="trigger"
    type="button"
    class="ui-select"
    :class="{ 'is-open': open, 'is-small': small, 'is-auto': auto, 'is-disabled': disabled }"
    :disabled="disabled"
    role="combobox"
    aria-haspopup="listbox"
    :aria-expanded="open"
    @click="toggle"
    @keydown="onKeydown"
  >
    <span class="ui-select-value" :class="{ 'is-placeholder': !selected }">{{ label }}</span>
    <span class="ui-select-caret" aria-hidden="true">⌄</span>
  </button>

  <Teleport to="body">
    <ul
      v-if="open"
      ref="list"
      class="ui-select-list"
      role="listbox"
      :style="{
        top: `${pos.top}px`,
        left: `${pos.left}px`,
        minWidth: `${pos.width}px`,
        maxHeight: `${pos.maxHeight}px`,
      }"
    >
      <li
        v-for="(option, index) in options"
        :key="option.value"
        class="ui-select-option"
        :class="{
          'is-active': index === activeIndex,
          'is-selected': option.value === modelValue,
        }"
        role="option"
        :aria-selected="option.value === modelValue"
        @mouseenter="activeIndex = index"
        @click="choose(option)"
      >
        <span class="ui-select-check" aria-hidden="true">{{
          option.value === modelValue ? '✓' : ''
        }}</span>
        <span>
          {{ option.label }}
          <small v-if="option.hint" class="ui-select-hint">{{ option.hint }}</small>
        </span>
      </li>
    </ul>
  </Teleport>
</template>
