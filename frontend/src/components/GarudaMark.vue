<script setup lang="ts">
/** Гаруда — орёл, вахана Вишну.
 *
 * Крупный кадр: голова в профиль и три маховых пера, уходящих за левый
 * край. Мелких деталей нет намеренно — тот же рисунок идёт в фавикон,
 * а там он ужимается до 16 пикселей.
 *
 * `plain` — без плашки, двухцветный (для светлого фона).
 */
withDefaults(defineProps<{ size?: number; plain?: boolean }>(), { size: 34, plain: false })

// Перья обрезаются рамкой слева — так кадр читается как приближение,
// а не как маленькая птица в пустом поле.
const FEATHERS = [
  { d: 'M-4 15C10 15 22 20 31 29', width: 8, strong: true },
  { d: 'M-4 29C8 29.5 18 34 25 41', width: 7, strong: true },
  { d: 'M-2 42C7 42.6 14 46 19 51', width: 6, strong: false },
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

    <g transform="translate(33 32) scale(1.06) translate(-32 -30)">
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
              : 'var(--garuda-soft, #6b7f9c)'
            : feather.strong
              ? '#fff'
              : 'rgba(255,255,255,.55)'
        "
      />

      <!-- Голова в профиль с крючковатым клювом -->
      <path
        d="M27 30.5c1-9.6 9.2-17 18.9-17 4.6 0 8.8 1.7 12 4.4l6.6 5.6-8.4-.9 3 6.2-7.5-3.6c-2.6 4.2-7.2 7-12.5 7-2.3 0-4.5-.5-6.4-1.5z"
        :fill="plain ? 'currentColor' : '#fff'"
      />
    </g>
  </svg>
</template>
