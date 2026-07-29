<script setup lang="ts">
withDefaults(
  defineProps<{
    /** Ширины колонок в процентах — по ним рисуются полоски */
    columns?: number[]
    rows?: number
  }>(),
  { rows: 8 },
)
</script>

<template>
  <div class="table-wrap" aria-busy="true" aria-live="polite">
    <span class="sr-only">Загружаем данные</span>
    <table class="ws-table">
      <tbody>
        <tr v-for="row in rows" :key="row">
          <td v-for="(width, index) in columns ?? [40, 15, 12, 15, 12, 8]" :key="index">
            <span
              class="skeleton skeleton-text"
              :style="{ width: `${width}%`, opacity: 1 - row * 0.06 }"
            />
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
