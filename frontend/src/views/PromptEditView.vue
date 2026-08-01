<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { api, type PlaceholderInfo, type PromptTemplate } from '@/api'
import NavIcon from '@/components/NavIcon.vue'
import ToastStack from '@/components/ToastStack.vue'

const route = useRoute()
const router = useRouter()

const promptId = computed(() => {
  const raw = route.params.id
  return raw === undefined ? null : Number(raw)
})
const isNew = computed(() => promptId.value === null)

const placeholders = ref<PlaceholderInfo[]>([])
const original = ref<PromptTemplate | null>(null)
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const expanded = ref(false)
const bodyField = ref<HTMLTextAreaElement | null>(null)

const form = reactive({ name: '', description: '', body: '', is_default: false })

const dirty = computed(() => {
  if (isNew.value) return form.name.trim().length > 0 && form.body.trim().length >= 20
  const p = original.value
  return (
    !!p &&
    (form.name !== p.name ||
      form.description !== (p.description ?? '') ||
      form.body !== p.body ||
      form.is_default !== p.is_default)
  )
})

async function load() {
  loading.value = true
  try {
    const all = await api.get<PromptTemplate[]>('/api/prompts')

    if (isNew.value) {
      // Отталкиваемся от действующего шаблона: писать промпт с нуля незачем
      const base = all.find((p) => p.is_default) ?? all[0]
      Object.assign(form, {
        name: '',
        description: '',
        body: base?.body ?? '',
        is_default: false,
      })
    } else {
      const found = all.find((p) => p.id === promptId.value)
      if (!found) {
        error.value = 'Шаблон не найден'
        return
      }
      original.value = found
      Object.assign(form, {
        name: found.name,
        description: found.description ?? '',
        body: found.body,
        is_default: found.is_default,
      })
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Не удалось загрузить шаблон'
  } finally {
    loading.value = false
  }
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

async function save() {
  saving.value = true
  error.value = ''
  try {
    const payload = {
      name: form.name.trim(),
      description: form.description.trim() || null,
      body: form.body,
      is_default: form.is_default,
    }

    if (isNew.value) {
      await api.post<PromptTemplate>('/api/prompts', payload)
    } else {
      await api.patch<PromptTemplate>(`/api/prompts/${promptId.value}`, payload)
    }
    router.push({ name: 'prompts' })
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Не удалось сохранить'
  } finally {
    saving.value = false
  }
}

function goBack() {
  if (dirty.value && !confirm('Изменения не сохранены. Уйти со страницы?')) return
  router.push({ name: 'prompts' })
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
      <button class="ws-btn ws-btn-quiet" type="button" @click="goBack">← К списку</button>
      <span class="muted" style="font-size: 13px">
        {{ isNew ? 'Новый шаблон' : original?.name }}
      </span>
      <span class="row-end row">
        <button
          class="ws-btn ws-btn-primary"
          type="button"
          :disabled="saving || !dirty"
          @click="save"
        >
          {{ saving ? 'Сохраняем…' : 'Сохранить' }}
        </button>
      </span>
    </div>

    <ToastStack :error="error" @clear-error="error = ''" />

    <section class="ws-surface">
      <div class="ws-surface-head">
        <h2 class="ws-surface-title">Шаблон промпта</h2>
        <button class="ws-btn ws-btn-quiet" type="button" @click="expanded = !expanded">
          {{ expanded ? 'Свернуть поле' : 'Развернуть поле' }}
        </button>
      </div>

      <div v-if="loading" class="ws-surface-body stack">
        <span class="skeleton skeleton-text" style="width: 30%" />
        <span class="skeleton skeleton-block" style="height: 34px" />
        <span class="skeleton skeleton-block" style="height: 320px" />
      </div>

      <form v-else class="ws-surface-body stack" @submit.prevent="save">
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
              :class="{ 'is-expanded': expanded }"
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
              разбираться ответ модели. Поле можно тянуть за нижний правый угол.
            </small>
          </div>
        </div>

        <label class="row" style="gap: 8px; cursor: pointer">
          <span class="ui-check" :class="{ 'is-on': form.is_default }">
            <input
              v-model="form.is_default"
              type="checkbox"
              :disabled="original?.is_default"
            />
            <NavIcon name="tick" />
          </span>
          <span>Применять к источникам, которым свой шаблон не назначен</span>
        </label>

        <div class="row">
          <button class="ws-btn ws-btn-primary" type="submit" :disabled="saving || !dirty">
            {{ saving ? 'Сохраняем…' : 'Сохранить' }}
          </button>
          <button class="ws-btn ws-btn-quiet" type="button" @click="goBack">Отмена</button>
        </div>
      </form>
    </section>
  </div>
</template>
