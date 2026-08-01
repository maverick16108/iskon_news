<script setup lang="ts">
/** Гаруда — орёл, вахана Вишну.
 *
 * Силуэт намеренно из крупных форм: тот же рисунок идёт в фавикон,
 * а там он ужимается до 16 пикселей, и мелкие детали пропадут.
 * `plain` — без плашки, одним цветом (для свёрнутого меню и печати).
 */
withDefaults(defineProps<{ size?: number; plain?: boolean }>(), { size: 34, plain: false })
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
    <g
      :fill="plain ? 'currentColor' : '#fff'"
      transform="translate(32 33) scale(.84) translate(-32 -32)"
    >
      <!-- Гребень -->
      <path d="M32 3 26 11.5h12L32 3Z" />
      <!-- Голова -->
      <circle cx="32" cy="18" r="8.4" />
      <!-- Клюв -->
      <path d="M28.6 23 32 34.5 35.4 23h-6.8Z" />
      <!-- Левое крыло -->
      <path
        d="M25 27.5 6.6 9.9C4.9 8.2 2.2 9.8 2.8 12.1l3 11.6-4.2-1.6c-1.9-.7-3.3 1.7-1.9 3.2l6 6.3-3.2.7c-2 .4-2.2 3.2-.3 3.9L25 43.5V27.5Z"
      />
      <!-- Правое крыло -->
      <path
        d="M39 27.5 57.4 9.9c1.7-1.7 4.4-.1 3.8 2.2l-3 11.6 4.2-1.6c1.9-.7 3.3 1.7 1.9 3.2l-6 6.3 3.2.7c2 .4 2.2 3.2.3 3.9L39 43.5V27.5Z"
      />
      <!-- Корпус и хвост -->
      <path d="M24.6 27.5h14.8l1.6 17.3h-4.7l2.3 11.4L32 61l-6.6-4.8 2.3-11.4H23l1.6-17.3Z" />
    </g>
  </svg>
</template>
