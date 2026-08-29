<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { api, type PromptTemplate } from '@/api'
import ToastStack from '@/components/ToastStack.vue'
import { formatDate } from '@/labels'

const prompts = ref<PromptTemplate[]>([])
const loading = ref(true)
const error = ref('')
const notice = ref('')

async function load() {
  loading.value = true
  try {
    prompts.value = await api.get<PromptTemplate[]>('/api/prompts')
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Не удалось загрузить шаблоны'
  } finally {
    loading.value = false
  }
}

async function makeDefault(prompt: PromptTemplate) {
  error.value = ''
  try {
    await api.patch<PromptTemplate>(`/api/prompts/${prompt.id}`, { is_default: true })
    notice.value = `«${prompt.name}» теперь применяется по умолчанию`
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Не удалось назначить'
  }
}

async function remove(prompt: PromptTemplate) {
  if (!confirm(`Удалить шаблон «${prompt.name}»?`)) return
  error.value = ''
  try {
    await api.delete(`/api/prompts/${prompt.id}`)
    notice.value = `Шаблон «${prompt.name}» удалён`
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Не удалось удалить'
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="ws-control-bar">
      <span class="muted" style="font-size: 13px">Шаблонов: {{ prompts.length }}</span>
      <span class="row-end">
        <RouterLink class="ws-btn ws-btn-primary" :to="{ name: 'prompt-new' }">
          Новый шаблон
        </RouterLink>
      </span>
    </div>

    <ToastStack
      :error="error"
      :notice="notice"
      @clear-error="error = ''"
      @clear-notice="notice = ''"
    />

    <section class="ws-surface">
      <div class="ws-surface-head"><h2 class="ws-surface-title">Шаблоны промптов</h2></div>

      <div v-if="loading" class="ws-surface-body stack">
        <span class="skeleton skeleton-text" style="width: 40%" />
        <span class="skeleton skeleton-block" style="height: 60px" />
        <span class="skeleton skeleton-text" style="width: 30%" />
        <span class="skeleton skeleton-block" style="height: 60px" />
      </div>

      <div v-else class="table-wrap">
        <table class="ws-table">
          <thead>
            <tr>
              <th>Название</th>
              <th>Пояснение</th>
              <th>Длина поста</th>
              <th>Источников</th>
              <th>Изменён</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="prompt in prompts" :key="prompt.id">
              <td class="cell-title">
                <b>{{ prompt.name }}</b>
                <span v-if="prompt.is_default" class="ws-badge healthy" style="margin-left: 8px">
                  по умолчанию
                </span>
              </td>
              <td class="wrap muted" data-label="Пояснение">{{ prompt.description || '—' }}</td>
              <td class="num" data-label="Длина поста">
                {{ prompt.post_min_chars }}–{{ prompt.post_max_chars }}
              </td>
              <td class="num" data-label="Источников">{{ prompt.used_by_sources || '—' }}</td>
              <td data-label="Изменён">
                {{ formatDate(prompt.updated_at) }}
                <div v-if="prompt.updated_by" class="muted" style="font-size: 11px">
                  {{ prompt.updated_by }}
                </div>
              </td>
              <td>
                <div class="row" style="gap: 6px; justify-content: flex-end">
                  <RouterLink
                    class="ws-btn ws-btn-quiet"
                    :to="{ name: 'prompt-edit', params: { id: prompt.id } }"
                  >
                    Править
                  </RouterLink>
                  <button
                    v-if="!prompt.is_default"
                    class="ws-btn ws-btn-quiet"
                    @click="makeDefault(prompt)"
                  >
                    Сделать основным
                  </button>
                  <button
                    class="ws-btn ws-btn-danger"
                    :disabled="prompt.is_default || prompt.used_by_sources > 0"
                    :title="
                      prompt.is_default
                        ? 'Шаблон по умолчанию удалить нельзя'
                        : prompt.used_by_sources
                          ? 'Шаблон используют источники'
                          : ''
                    "
                    @click="remove(prompt)"
                  >
                    Удалить
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>
