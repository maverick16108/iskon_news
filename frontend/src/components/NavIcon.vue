<script setup lang="ts">
/** Иконки навигации. Рисуем сами, чтобы не тянуть библиотеку ради восьми штук. */
defineProps<{ name: string }>()
</script>

<template>
  <svg
    class="nav-icon"
    viewBox="0 0 20 20"
    fill="none"
    stroke="currentColor"
    stroke-width="1.6"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <!-- Лента новостей -->
    <template v-if="name === 'feed'">
      <rect x="2.5" y="3.5" width="15" height="13" rx="2" />
      <path d="M5.5 7.5h6M5.5 10.5h9M5.5 13.5h9" />
    </template>

    <!-- Источники -->
    <template v-else-if="name === 'sources'">
      <circle cx="5" cy="15" r="1.6" />
      <path d="M3.5 4.5a12 12 0 0 1 12 12M3.5 9a7.5 7.5 0 0 1 7.5 7.5" />
    </template>

    <!-- Пользователи -->
    <template v-else-if="name === 'users'">
      <circle cx="8" cy="7" r="3" />
      <path d="M2.5 16.5c0-3 2.5-4.5 5.5-4.5s5.5 1.5 5.5 4.5" />
      <path d="M14 5.2a2.8 2.8 0 0 1 0 5.4M15.5 12.4c1.5.6 2.5 1.8 2.5 4.1" />
    </template>

    <!-- Промпты -->
    <template v-else-if="name === 'prompts'">
      <path d="M4 3.5h9l3.5 3.5v9.5a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-12a1 1 0 0 1 1-1z" />
      <path d="M12.5 3.5V7h3.5M6 11h8M6 14h5" />
    </template>

    <!-- Настройки модели -->
    <template v-else-if="name === 'model'">
      <circle cx="10" cy="10" r="2.4" />
      <path
        d="M10 2.5v2M10 15.5v2M2.5 10h2M15.5 10h2M4.7 4.7l1.4 1.4M13.9 13.9l1.4 1.4M15.3 4.7l-1.4 1.4M6.1 13.9l-1.4 1.4"
      />
    </template>

    <!-- Журнал действий -->
    <template v-else-if="name === 'audit'">
      <path d="M3.5 4a1 1 0 0 1 1-1h8l4 4v9a1 1 0 0 1-1 1h-11a1 1 0 0 1-1-1z" />
      <path d="M12.5 3v4h4" />
      <path d="M6.5 12.5l2 2 4-4.5" />
    </template>

    <!-- Публикация в канал -->
    <template v-else-if="name === 'telegram'">
      <path d="M17.5 3.5 2.5 9.2l4.6 1.7 1.8 4.9 2.4-3 4 3z" />
      <path d="M7.1 10.9 17.5 3.5" />
    </template>

    <!-- Фотографии -->
    <template v-else-if="name === 'photo'">
      <rect x="2.5" y="4.5" width="15" height="11" rx="2" />
      <circle cx="7" cy="8.5" r="1.4" />
      <path d="M3 13.5l4-3.5 3.5 3 3-2.5 3.5 3" />
    </template>

    <!-- Загрузить -->
    <template v-else-if="name === 'upload'">
      <path d="M10 13.5V3.5M6.5 7 10 3.5 13.5 7" />
      <path d="M3.5 12.5v3a1 1 0 0 0 1 1h11a1 1 0 0 0 1-1v-3" />
    </template>

    <!-- Свернуть панель -->
    <template v-else-if="name === 'collapse'">
      <rect x="2.5" y="3.5" width="15" height="13" rx="2" />
      <path d="M8 3.5v13" />
    </template>
  </svg>
</template>
