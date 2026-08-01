<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { api, type PlaceholderInfo, type PromptPreview, type PromptTemplate } from '@/api'
import { formatDate } from '@/labels'

const prompts = ref<PromptTemplate[]>([])
const placeholders = ref<PlaceholderInfo[]>([])
const loading = ref(true)
const saving = ref(false)
const previewing = ref(false)
const error = ref('')
const notice = ref('')
const preview = ref<PromptPreview | null>(null)

const editing = ref<PromptTemplate | null>(null)
const creating = ref(false)
const bodyField = ref<HTMLTextAreaElement | null>(null)

const form = reactive({ name: '', description: '', body: '', is_default: false })

const isOpen = computed(() => creating.value || editing.value !== null)

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

function startCreate() {
  const base = prompts.value.find((p) => p.is_default) ?? prompts.value[0]
  Object.assign(form, {
    name: '',
    description: '',
    // Отталкиваемся от действующего шаблона: писать промпт с нуля незачем
    body: base?.body ?? '',
    is_default: false,
  })
  editing.value = null
  creating.value = true
  preview.value = null
}

function startEdit(prompt: PromptTemplate) {
  Object.assign(form, {
    name: prompt.name,
    description: prompt.description ?? '',
    body: prompt.body,
    is_default: prompt.is_default,
  })
  creating.value = false
  editing.value = prompt
  preview.value = null
}

function close() {
  creating.value = false
  editing.value = null
  preview.value = null
}

function insertPlaceholder(token: string) {
  const field = bodyField.value
  if (!field) {
    form.body += token
    return
  }
  const start = field.selectionStart ?? form.body.length
  const end = field.selectionEnd ?? start
  form.body = form.body.slice(0, start) + token + form.body.slice(end)
  // Возвращаем курсор сразу после вставленного плейсхолдера
  requestAnimationFrame(() => {
    field.focus()
    field.setSelectionRange(start + token.length, start + token.length)
  })
}

async function showPreview() {
  previewing.value = true
  error.value = ''
  try {
    preview.value = await api.post<PromptPreview>('/api/prompts/preview', {
      name: form.name || 'предпросмотр',
      description: null,
      body: form.body,
      is_default: false,
    })
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Не удалось собрать предпросмотр'
  } finally {
    previewing.value = false
  }
}

async function save() {
  saving.value = true
  error.value = ''
  notice.value = ''
  try {
    const payload = {
      name: form.name.trim(),
      description: form.description.trim() || null,
      body: form.body,
      is_default: form.is_default,
    }

    if (editing.value) {
      await api.patch<PromptTemplate>(`/api/prompts/${editing.value.id}`, payload)
      notice.value = `Шаблон «${payload.name}» сохранён`
    } else {
      await api.post<PromptTemplate>('/api/prompts', payload)
      notice.value = `Шаблон «${payload.name}» создан`
    }
    close()
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Не удалось сохранить'
  } finally {
    saving.value = false
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

onMounted(async () => {
  try {
    placeholders.value = await api.get<PlaceholderInfo[]>('/api/prompts/placeholders')
  } catch {
    // подсказки не критичны
  }
  await load()
})
</script>

<template>
  <div>
    <div class="ws-control-bar">
      <span class="muted" style="font-size: 13px">Шаблонов: {{ prompts.length }}</span>
      <span class="row-end">
        <button class="ws-btn ws-btn-primary" @click="isOpen ? close() : startCreate()">
          {{ isOpen ? 'Отмена' : 'Новый шаблон' }}
        </button>
      </span>
    </div>

    <p v-if="error" class="alert alert-error" style="margin-bottom: 12px">{{ error }}</p>
    <p v-if="notice" class="alert alert-success" style="margin-bottom: 12px">{{ notice }}</p>

    <section v-if="isOpen" class="ws-surface" style="margin-bottom: 16px">
      <div class="ws-surface-head">
        <h2 class="ws-surface-title">
          {{ editing ? `Правка: ${editing.name}` : 'Новый шаблон' }}
        </h2>
      </div>

      <form class="ws-surface-body stack" @submit.prevent="save">
        <div class="ws-field">
          <label class="ws-field-label">Название</label>
          <input v-model="form.name" class="ws-input" required maxlength="255" />
        </div>

        <div class="ws-field">
          <label class="ws-field-label">Пояснение (необязательно)</label>
          <input
            v-model="form.description"
            class="ws-input"
            maxlength="512"
            placeholder="Для каких источников подходит"
          />
        </div>

        <div class="ws-field">
          <label class="ws-field-label">Инструкция для модели</label>
          <div>
            <textarea
              ref="bodyField"
              v-model="form.body"
              class="ws-input prompt-body"
              required
              minlength="20"
            ></textarea>
            <div class="placeholder-list" style="margin-top: 8px">
              <button
                v-for="item in placeholders"
                :key="item.token"
                type="button"
                class="placeholder-chip"
                :title="item.description"
                @click="insertPlaceholder(item.token)"
              >
                {{ item.token }}
              </button>
            </div>
            <small class="muted">
              Плейсхолдеры подставляются при обращении к модели. Блок «Формат ответа»
              дописывается автоматически и в шаблоне не нужен — без него перестал бы
              разбираться ответ модели.
            </small>
          </div>
        </div>

        <label class="row" style="gap: 6px; cursor: pointer">
          <input v-model="form.is_default" type="checkbox" :disabled="editing?.is_default" />
          <span>Применять к источникам, которым свой шаблон не назначен</span>
        </label>

        <div class="row">
          <button class="ws-btn ws-btn-primary" type="submit" :disabled="saving">
            {{ saving ? 'Сохраняем…' : 'Сохранить' }}
          </button>
          <button
            class="ws-btn"
            type="button"
            :disabled="previewing || form.body.length < 20"
            @click="showPreview"
          >
            {{ previewing ? 'Собираем…' : 'Показать целиком' }}
          </button>
          <button class="ws-btn ws-btn-quiet" type="button" @click="close">Отмена</button>
        </div>

        <div v-if="preview" class="ws-field">
          <label class="ws-field-label">
            Промпт целиком
            <span class="muted">— {{ preview.chars }} символов</span>
          </label>
          <div class="prompt-preview">{{ preview.rendered }}</div>
        </div>
      </form>
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
              <td>
                <b>{{ prompt.name }}</b>
                <span v-if="prompt.is_default" class="ws-badge healthy" style="margin-left: 8px">
                  по умолчанию
                </span>
              </td>
              <td class="wrap muted">{{ prompt.description || '—' }}</td>
              <td class="num">{{ prompt.used_by_sources || '—' }}</td>
              <td>
                {{ formatDate(prompt.updated_at) }}
                <div v-if="prompt.updated_by" class="muted" style="font-size: 11px">
                  {{ prompt.updated_by }}
                </div>
              </td>
              <td>
                <div class="row" style="gap: 6px; justify-content: flex-end">
                  <button class="ws-btn ws-btn-quiet" @click="startEdit(prompt)">Править</button>
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
