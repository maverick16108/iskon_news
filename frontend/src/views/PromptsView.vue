<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { FALLBACK_POST_LIMITS, api, type PostLimits, type PromptTemplate } from '@/api'
import ToastStack from '@/components/ToastStack.vue'
import { formatDate } from '@/labels'

const prompts = ref<PromptTemplate[]>([])
const loading = ref(true)
const error = ref('')
const notice = ref('')

// --- Длина поста ----------------------------------------------------------
// Живёт здесь, а не в настройках подключения: это требование к тексту,
// и в шаблон она подставляется через {min_chars} и {max_chars}.

// Дальше этого не пустит уже Telegram: предел одного сообщения.
const POST_CHARS_FLOOR = 200
const POST_CHARS_CEILING = 4096

const limits = ref<PostLimits>({ ...FALLBACK_POST_LIMITS })
const limitsForm = reactive({ ...FALLBACK_POST_LIMITS })
const savingLimits = ref(false)

const rangeError = computed(() =>
  limitsForm.min_chars > limitsForm.max_chars ? 'Нижняя граница больше верхней' : '',
)

const limitsDirty = computed(
  () =>
    limitsForm.min_chars !== limits.value.min_chars ||
    limitsForm.max_chars !== limits.value.max_chars,
)

async function loadLimits() {
  try {
    limits.value = await api.get<PostLimits>('/api/settings/llm/post-limits')
    Object.assign(limitsForm, limits.value)
  } catch {
    // не критично: список шаблонов важнее
  }
}

async function saveLimits() {
  if (rangeError.value || !limitsDirty.value) return

  savingLimits.value = true
  error.value = ''
  notice.value = ''
  try {
    limits.value = await api.patch<PostLimits>('/api/settings/llm/post-limits', {
      min_chars: limitsForm.min_chars,
      max_chars: limitsForm.max_chars,
    })
    Object.assign(limitsForm, limits.value)
    notice.value = `Длина поста: ${limits.value.min_chars}–${limits.value.max_chars} символов`
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Не удалось сохранить длину'
  } finally {
    savingLimits.value = false
  }
}

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

onMounted(() => {
  void load()
  void loadLimits()
})
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
      <div class="ws-surface-head"><h2 class="ws-surface-title">Длина поста</h2></div>

      <div class="ws-surface-body">
        <div class="ws-field" :class="{ 'is-invalid': !!rangeError }">
          <label class="ws-field-label">Границы</label>
          <div>
            <div class="range-row">
              <label class="range-input">
                <span>от</span>
                <input
                  v-model.number="limitsForm.min_chars"
                  class="ws-input"
                  type="number"
                  :min="POST_CHARS_FLOOR"
                  :max="POST_CHARS_CEILING"
                  step="50"
                />
              </label>
              <label class="range-input">
                <span>до</span>
                <input
                  v-model.number="limitsForm.max_chars"
                  class="ws-input"
                  type="number"
                  :min="POST_CHARS_FLOOR"
                  :max="POST_CHARS_CEILING"
                  step="50"
                />
              </label>
              <span class="range-unit">символов</span>
              <button
                class="ws-btn ws-btn-primary"
                type="button"
                :disabled="savingLimits || !limitsDirty || !!rangeError"
                @click="saveLimits"
              >
                {{ savingLimits ? 'Сохраняем…' : 'Сохранить' }}
              </button>
            </div>
            <small v-if="rangeError" class="range-alert">{{ rangeError }}</small>
            <small class="ws-help">
              Подставляются в шаблон вместо <code>{min_chars}</code> и
              <code>{max_chars}</code>. Считается по всему посту — с хэштегами,
              заголовком и подписью. Это ориентир для модели: в редакторе длину
              можно поднять и выше — ползунком «Размер поста». Дальше
              {{ POST_CHARS_CEILING }} символов не пустит уже Telegram.
            </small>
          </div>
        </div>
      </div>
    </section>

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
