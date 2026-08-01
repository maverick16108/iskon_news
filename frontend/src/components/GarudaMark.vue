<script setup lang="ts">
/** Гаруда — орёл, вахана Вишну.
 *
 * Голова в профиль и веер маховых перьев за ней. Композиция намеренно
 * диагональная: тот же рисунок идёт в фавикон, а там нужен квадрат.
 * Мелких деталей нет — на 16 пикселях они всё равно пропадут.
 *
 * `plain` — без плашки, двухцветный (для светлого фона).
 */
withDefaults(defineProps<{ size?: number; plain?: boolean }>(), { size: 34, plain: false })

// Маховые перья: от кончика слева к голове справа, сверху вниз
const FEATHERS = [
  { d: 'M3 12.5C17 12.8 30 17.5 40.5 26', width: 5, strong: true },
  { d: 'M4.5 19.5C17 20 28.5 24.5 37.5 31.5', width: 4.4, strong: true },
  { d: 'M7 26.5C18 27.2 27.5 31.5 34.5 37.5', width: 3.8, strong: false },
  { d: 'M10.5 33.5C20 34.4 27 38 31.5 43.5', width: 3.2, strong: false },
  { d: 'M15 40.5C22 41.6 26.5 44.6 29 49', width: 2.7, strong: false },
]
</script>

<template>
  <svg
    class="garuda"
    :width="size"
    :height="size"
    viewBox="0 0 64 64"
    role="img"
    aria-label="Гаруда"
  >
    <rect v-if="!plain" width="64" height="64" rx="15" fill="currentColor" />

    <path
      v-for="(feather, index) in FEATHERS"
      :key="index"
      :d="feather.d"
      fill="none"
      stroke-linecap="round"
      :stroke-width="feather.width"
      :stroke="
        plain
          ? feather.strong
            ? 'currentColor'
            : 'var(--garuda-soft, #6b7f85)'
          : feather.strong
            ? '#fff'
            : 'rgba(255,255,255,.62)'
      "
    />

    <!-- Голова в профиль с крючковатым клювом -->
    <path
      d="M38 22.6c1.4-4.9 6-8.3 11.2-8.3 3.6 0 6.8 1.6 8.9 4.2l4.6 5.6-6.1-1.3 1.4 4.3-4.9-2.6c-1.9 1.7-4.4 2.7-7.1 2.7-1.5 0-3-.3-4.3-.9z"
      :fill="plain ? 'currentColor' : '#fff'"
    />
    <circle cx="49.5" cy="20.4" r="1.5" :fill="plain ? '#fff' : 'currentColor'" />
  </svg>
</template>
