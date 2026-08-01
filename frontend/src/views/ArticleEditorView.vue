<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import { MAX_POST_CHARS, api, type ArticleDetail, type ArticleImage, type Post } from '@/api'
import NavIcon from '@/components/NavIcon.vue'
import { POST_STATUS_LABELS, POST_STATUS_TONE, QUALITY_LABELS, QUALITY_TONE, formatDate } from '@/labels'

const route = useRoute()
const articleId = Number(route.params.id)

const article = ref<ArticleDetail | null>(null)
const allowedTags = ref<string[]>([])
const loading = ref(true)
const generating = ref(false)
const saving = ref(false)
const error = ref('')
const notice = ref('')

// Черновик, который правит редактор
const draft = ref({ hashtags: '', title: '', body: '', signature: '' })

const post = computed<Post | null>(() => article.value?.post ?? null)

/** Сборка поста повторяет серверную: хэштеги и жирный заголовок одной строкой. */
const rendered = computed(() => {
  const head = `${draft.value.hashtags} **${draft.value.title}**`.trim()
  const tail = `${draft.value.signature}\nНовости ИСККОН t.me/iskconru`.trim()
  return `${head}\n\n${draft.value.body.trim()}\n\n${tail}`
})

const charCount = computed(() => rendered.value.length)

const counterClass = computed(() => {
  if (charCount.value > MAX_POST_CHARS) return 'over'
  if (charCount.value > MAX_POST_CHARS - 100) return 'near'
  return 'ok'
})

const canPublish = computed(
  () =>
    charCount.value <= MAX_POST_CHARS &&
    draft.value.hashtags.trim().length > 0 &&
    draft.value.title.trim().length > 0 &&
    post.value?.status !== 'published',
)

function syncDraft() {
  if (post.value) {
    draft.value = {
      hashtags: post.value.hashtags,
      title: post.value.title,
      body: post.value.body,
      signature: post.value.signature,
    }
  }
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    article.value = await api.get<ArticleDetail>(`/api/articles/${articleId}`)
    syncDraft()
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Не удалось загрузить статью'
  } finally {
    loading.value = false
  }
}

async function generate() {
  generating.value = true
  error.value = ''
  notice.value = ''
  try {
    const result = await api.post<Post>(`/api/articles/${articleId}/rewrite`)

    // Тем же проходом переводятся подписи к фотографиям, поэтому перечитываем
    // статью целиком, а не только пост — иначе в галерее останутся английские.
    article.value = await api.get<ArticleDetail>(`/api/articles/${articleId}`)
    syncDraft()

    const translated = article.value.images.filter((i) => i.caption_ru).length
    notice.value =
      `Готово: ${result.char_count} символов, модель ${result.ai_model}` +
      (translated ? `, переведено подписей к фото: ${translated}` : '')
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Переработка не удалась'
  } finally {
    generating.value = false
  }
}

async function save() {
  saving.value = true
  error.value = ''
  notice.value = ''
  try {
    const result = await api.patch<Post>(`/api/articles/${articleId}/post`, draft.value)
    if (article.value) article.value.post = result
    notice.value = 'Изменения сохранены'
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Не удалось сохранить'
  } finally {
    saving.value = false
  }
}

async function publish() {
  saving.value = true
  error.value = ''
  notice.value = ''
  try {
    // Сначала сохраняем правки, иначе опубликуется прошлая версия
    await api.patch<Post>(`/api/articles/${articleId}/post`, draft.value)
    const result = await api.post<Post>(`/api/articles/${articleId}/publish`)
    if (article.value) article.value.post = result
    notice.value = 'Пост опубликован'
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Не удалось опубликовать'
  } finally {
    saving.value = false
  }
}

async function unpublish() {
  saving.value = true
  error.value = ''
  try {
    const result = await api.post<Post>(`/api/articles/${articleId}/unpublish`)
    if (article.value) article.value.post = result
    notice.value = 'Пост снят с публикации'
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Не удалось снять с публикации'
  } finally {
    saving.value = false
  }
}

async function copyPost() {
  try {
    await navigator.clipboard.writeText(rendered.value)
    notice.value = 'Пост скопирован в буфер обмена'
  } catch {
    error.value = 'Браузер не дал доступ к буферу обмена'
  }
}

function addTag(tag: string) {
  const current = draft.value.hashtags.split(/\s+/).filter(Boolean)
  if (current.includes(tag)) {
    draft.value.hashtags = current.filter((t) => t !== tag).join(' ')
  } else {
    draft.value.hashtags = [...current, tag].join(' ')
  }
}

function isActiveTag(tag: string) {
  return draft.value.hashtags.split(/\s+/).includes(tag)
}

const selectedImages = computed(() => article.value?.images.filter((i) => i.is_selected) ?? [])

async function toggleImage(image: ArticleImage) {
  // Отмечаем сразу, не дожидаясь сервера — щелчок должен быть мгновенным
  const previous = image.is_selected
  image.is_selected = !previous
  try {
    await api.patch<ArticleImage>(`/api/articles/${articleId}/images/${image.id}`, {
      is_selected: image.is_selected,
    })
  } catch (e) {
    image.is_selected = previous
    error.value = e instanceof Error ? e.message : 'Не удалось изменить выбор фото'
  }
}

// --- Свои фотографии ------------------------------------------------------

const dropActive = ref(false)
const uploading = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)
// Счётчик нужен, потому что dragleave срабатывает и при переходе
// между дочерними элементами зоны
let dragDepth = 0

async function uploadFiles(files: FileList | File[] | null) {
  const list = Array.from(files ?? []).filter((file) => file.type.startsWith('image/'))
  if (!list.length) {
    error.value = 'Перетащите изображения — другие файлы не подойдут'
    return
  }

  uploading.value = true
  error.value = ''
  notice.value = ''
  try {
    const body = new FormData()
    list.forEach((file) => body.append('files', file))

    // FormData несёт свой Content-Type с границей, поэтому обычную обёртку
    // api.post здесь не используем — она навязывает application/json.
    const response = await fetch(`/api/articles/${articleId}/images`, {
      method: 'POST',
      credentials: 'include',
      body,
    })
    if (!response.ok) {
      const detail = await response.json().catch(() => null)
      throw new Error(detail?.detail ?? `Ошибка ${response.status}`)
    }

    article.value = await api.get<ArticleDetail>(`/api/articles/${articleId}`)
    notice.value = `Добавлено фотографий: ${list.length}`
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Не удалось загрузить'
  } finally {
    uploading.value = false
    dropActive.value = false
    dragDepth = 0
    if (fileInput.value) fileInput.value.value = ''
  }
}

function onDrop(event: DragEvent) {
  dragDepth = 0
  dropActive.value = false
  uploadFiles(event.dataTransfer?.files ?? null)
}

function onDragEnter() {
  dragDepth += 1
  dropActive.value = true
}

function onDragLeave() {
  dragDepth = Math.max(0, dragDepth - 1)
  if (!dragDepth) dropActive.value = false
}

async function removeImage(image: ArticleImage) {
  if (!confirm('Убрать эту фотографию из статьи?')) return
  error.value = ''
  try {
    await api.delete(`/api/articles/${articleId}/images/${image.id}`)
    if (article.value) {
      article.value.images = article.value.images.filter((i) => i.id !== image.id)
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Не удалось убрать фотографию'
  }
}

async function copyImageLinks() {
  // Копируем исходные адреса — они пригодятся при ручной публикации.
  // Локальные копии остаются у нас на случай, если источник их удалит.
  const links = selectedImages.value.map((i) => i.url).join('\n')
  try {
    await navigator.clipboard.writeText(links)
    notice.value = `Ссылок скопировано: ${selectedImages.value.length}`
  } catch {
    error.value = 'Браузер не дал доступ к буферу обмена'
  }
}

onMounted(async () => {
  try {
    allowedTags.value = await api.get<string[]>('/api/hashtags')
  } catch {
    // без подсказок теги можно ввести вручную
  }
  await load()
})
</script>

<template>
  <div>
    <div v-if="loading" class="editor-grid" aria-busy="true">
      <section class="ws-surface">
        <div class="ws-surface-head"><h2 class="ws-surface-title">Исходная статья</h2></div>
        <div class="ws-surface-body stack">
          <span class="skeleton skeleton-text" style="width: 70%; height: 18px" />
          <span class="skeleton skeleton-text" style="width: 40%" />
          <span class="skeleton skeleton-block" style="height: 320px" />
        </div>
      </section>
      <section class="ws-surface">
        <div class="ws-surface-head"><h2 class="ws-surface-title">Пост для канала</h2></div>
        <div class="ws-surface-body stack">
          <span class="skeleton skeleton-text" style="width: 30%" />
          <span class="skeleton skeleton-block" style="height: 70px" />
          <span class="skeleton skeleton-text" style="width: 30%" />
          <span class="skeleton skeleton-block" style="height: 34px" />
          <span class="skeleton skeleton-text" style="width: 30%" />
          <span class="skeleton skeleton-block" style="height: 200px" />
        </div>
      </section>
    </div>

    <template v-else-if="article">
      <div class="ws-control-bar">
        <RouterLink class="ws-btn ws-btn-quiet" :to="{ name: 'articles' }">← К ленте</RouterLink>
        <a class="ws-btn ws-btn-quiet" :href="article.url" target="_blank" rel="noopener">
          Открыть оригинал
        </a>

        <span class="row-end row">
          <span
            v-if="post"
            class="ws-badge"
            :class="POST_STATUS_TONE[post.status]"
          >
            {{ POST_STATUS_LABELS[post.status] }}
          </span>
          <button
            class="ws-btn ws-btn-primary"
            :disabled="generating || article.content_quality === 'empty'"
            @click="generate"
          >
            {{ generating ? 'Обрабатываем…' : post ? 'Переработать заново' : 'Переработать через ИИ' }}
          </button>
        </span>
      </div>

      <p v-if="error" class="alert alert-error" style="margin-bottom: 12px">{{ error }}</p>
      <p v-if="notice" class="alert alert-success" style="margin-bottom: 12px">{{ notice }}</p>
      <p
        v-if="article.content_quality === 'excerpt'"
        class="alert alert-info"
        style="margin-bottom: 12px"
      >
        По этой статье доступен только анонс из RSS, полный текст сайт не отдал. Пост выйдет
        коротким — проверьте его особенно внимательно.
      </p>

      <div class="editor-grid">
        <!-- Оригинал -->
        <section class="ws-surface">
          <div class="ws-surface-head">
            <h2 class="ws-surface-title">Исходная статья</h2>
            <span class="ws-badge" :class="QUALITY_TONE[article.content_quality]">
              {{ QUALITY_LABELS[article.content_quality] }}
            </span>
          </div>
          <div class="ws-surface-body">
            <h3 style="margin-bottom: 8px">{{ article.title }}</h3>
            <p class="muted" style="font-size: 12px; margin-bottom: 12px">
              {{ article.author || 'Автор не указан' }} · {{ formatDate(article.published_at) }}
            </p>
            <div class="source-text">{{ article.content || article.summary || 'Текста нет' }}</div>
          </div>
        </section>

        <!-- Пост -->
        <section class="ws-surface">
          <div class="ws-surface-head">
            <h2 class="ws-surface-title">Пост для канала</h2>
            <span class="char-counter" :class="counterClass">
              {{ charCount }} / {{ MAX_POST_CHARS }}
            </span>
          </div>

          <div class="ws-surface-body stack">
            <div class="ws-field">
              <label class="ws-field-label">Хэштеги (только из принятых на канале)</label>
              <input v-model="draft.hashtags" class="ws-input" placeholder="#ятры #фестивали" />
              <div class="tag-picker">
                <button
                  v-for="tag in allowedTags"
                  :key="tag"
                  type="button"
                  class="ws-chip"
                  :class="{ 'is-active': isActiveTag(tag) }"
                  :title="isActiveTag(tag) ? 'Убрать тег' : 'Поставить тег'"
                  @click="addTag(tag)"
                >
                  {{ tag }}
                </button>
              </div>
            </div>

            <div class="ws-field">
              <label class="ws-field-label">Заголовок (выводится жирным)</label>
              <input v-model="draft.title" class="ws-input" />
            </div>

            <div class="ws-field">
              <label class="ws-field-label">Текст поста</label>
              <textarea v-model="draft.body" class="ws-input"></textarea>
            </div>

            <div class="ws-field">
              <label class="ws-field-label">Подпись источника</label>
              <input v-model="draft.signature" class="ws-input" placeholder="«ISKCON News» website" />
            </div>

            <div class="ws-field">
              <label class="ws-field-label">
                Фотографии — отметьте те, что пойдут в пост
                <span class="muted">
                  ({{ selectedImages.length }} из {{ article.images.length }})</span
                >
              </label>
              <div>
                <div v-if="article.images.length" class="gallery" style="margin-bottom: 10px">
                  <div
                    v-for="image in article.images"
                    :key="image.id"
                    class="gallery-item"
                    :class="{ 'is-selected': image.is_selected }"
                    role="button"
                    tabindex="0"
                    :aria-pressed="image.is_selected"
                    @click="toggleImage(image)"
                    @keydown.enter.prevent="toggleImage(image)"
                    @keydown.space.prevent="toggleImage(image)"
                  >
                    <!-- Файл берём у себя, а не по прямой ссылке: источник
                         закрыт Cloudflare и отдаёт 403 в том числе на картинки -->
                    <img
                      class="gallery-thumb"
                      :src="`/api/articles/${articleId}/images/${image.id}/raw`"
                      :alt="image.caption_ru || image.caption || ''"
                      loading="lazy"
                    />
                    <span v-if="image.is_selected" class="gallery-mark" aria-hidden="true">✓</span>
                    <button
                      type="button"
                      class="gallery-remove"
                      title="Убрать фотографию"
                      @click.stop="removeImage(image)"
                    >
                      ×
                    </button>
                    <span v-if="image.is_uploaded" class="gallery-badge">своя</span>
                    <span class="gallery-caption">
                      {{ image.caption_ru || image.caption || 'Без подписи' }}
                      <span
                        v-if="image.caption_ru && image.caption"
                        class="gallery-caption-original"
                        >{{ image.caption }}</span
                      >
                    </span>
                  </div>
                </div>

                <div
                  class="dropzone"
                  :class="{ 'is-over': dropActive, 'is-busy': uploading }"
                  role="button"
                  tabindex="0"
                  @click="fileInput?.click()"
                  @keydown.enter.prevent="fileInput?.click()"
                  @dragenter.prevent="onDragEnter"
                  @dragover.prevent
                  @dragleave.prevent="onDragLeave"
                  @drop.prevent="onDrop"
                >
                  <NavIcon name="upload" style="width: 22px; height: 22px" />
                  <span v-if="uploading">Загружаем…</span>
                  <span v-else>
                    Перетащите свои фотографии сюда или нажмите, чтобы выбрать
                  </span>
                </div>
                <input
                  ref="fileInput"
                  type="file"
                  accept="image/jpeg,image/png,image/webp,image/avif"
                  multiple
                  hidden
                  @change="uploadFiles(($event.target as HTMLInputElement).files)"
                />
              </div>
            </div>

            <div class="ws-field">
              <label class="ws-field-label">Предпросмотр</label>
              <div class="post-preview">{{ rendered }}</div>
            </div>

            <p v-if="charCount > MAX_POST_CHARS" class="alert alert-error">
              Превышен лимит на {{ charCount - MAX_POST_CHARS }} символов — опубликовать нельзя.
            </p>

            <div class="row">
              <button class="ws-btn" :disabled="saving || !post" @click="save">Сохранить</button>
              <button class="ws-btn ws-btn-quiet" :disabled="!post" @click="copyPost">
                Скопировать текст
              </button>
              <button
                class="ws-btn ws-btn-quiet"
                :disabled="!selectedImages.length"
                @click="copyImageLinks"
              >
                Ссылки на фото ({{ selectedImages.length }})
              </button>
              <span class="row-end row">
                <button
                  v-if="post?.status === 'published'"
                  class="ws-btn ws-btn-danger"
                  :disabled="saving"
                  @click="unpublish"
                >
                  Снять с публикации
                </button>
                <button
                  v-else
                  class="ws-btn ws-btn-primary"
                  :disabled="saving || !canPublish || !post"
                  @click="publish"
                >
                  Опубликовать
                </button>
              </span>
            </div>

            <p v-if="post?.ai_error" class="alert alert-error">{{ post.ai_error }}</p>
          </div>
        </section>
      </div>
    </template>
  </div>
</template>
