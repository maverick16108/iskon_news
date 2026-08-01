<script setup lang="ts">
import { watch, ref, onBeforeUnmount } from 'vue'

/** Всплывающие сообщения поверх страницы.
 *
 * Раньше уведомления жили в потоке вверху экрана: правишь пост внизу
 * длинной страницы, нажимаешь кнопку — и ответа не видишь. Здесь они
 * закреплены у нижнего края и не зависят от прокрутки.
 */
const props = defineProps<{ error?: string; notice?: string }>()
const emit = defineEmits<{ 'clear-error': []; 'clear-notice': [] }>()

const NOTICE_TIMEOUT = 6000

let timer: ReturnType<typeof setTimeout> | undefined
const noticeVisible = ref(false)

// Удачное действие само уходит с глаз, ошибка остаётся: её нужно прочитать
watch(
  () => props.notice,
  (value) => {
    clearTimeout(timer)
    noticeVisible.value = Boolean(value)
    if (value) timer = setTimeout(() => emit('clear-notice'), NOTICE_TIMEOUT)
  },
  { immediate: true },
)

onBeforeUnmount(() => clearTimeout(timer))
</script>

<template>
  <Teleport to="body">
    <div class="toast-stack" role="status" aria-live="polite">
      <Transition name="toast">
        <div v-if="error" class="toast toast-error">
          <span>{{ error }}</span>
          <button class="toast-close" type="button" aria-label="Закрыть" @click="emit('clear-error')">
            ×
          </button>
        </div>
      </Transition>
      <Transition name="toast">
        <div v-if="notice && noticeVisible" class="toast toast-success">
          <span>{{ notice }}</span>
          <button
            class="toast-close"
            type="button"
            aria-label="Закрыть"
            @click="emit('clear-notice')"
          >
            ×
          </button>
        </div>
      </Transition>
    </div>
  </Teleport>
</template>
