<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import {
  CHANNEL_TITLE,
  FALLBACK_POST_LIMITS,
  api,
  type ArticleDetail,
  type ArticleImage,
  type ArticleVideo,
  type Post,
  type PostLimits,
  type TelegramState,
} from '@/api'
import NavIcon from '@/components/NavIcon.vue'
import ToastStack from '@/components/ToastStack.vue'
import {
  POST_STATUS_LABELS,
  POST_STATUS_TONE,
  QUALITY_LABELS,
  QUALITY_TONE,
  formatDate,
} from '@/labels'

const route = useRoute()
const articleId = Number(route.params.id)

const article = ref<ArticleDetail | null>(null)
const allowedTags = ref<string[]>([])
const telegramState = ref<TelegramState | null>(null)
const loading = ref(true)
const generating = ref(false)
const saving = ref(false)
const error = ref('')
const notice = ref('')

// Черновик, который правит редактор
const draft = ref({ hashtags: '', title: '', body: '', signature: '' })

const post = computed<Post | null>(() => article.value?.post ?? null)

// Границы длины приходят вместе со статьёй: они заданы в шаблоне промпта,
// назначенном её источнику, и у разных новостей разные. До ответа сервера
// считаем по запасным, чтобы счётчик не мигал пустотой.
const limits = computed<PostLimits>(() => article.value?.post_limits ?? FALLBACK_POST_LIMITS)

/** Сборка поста повторяет серверную — по ней же считается длина.
 *  Подпись: строка источника, ниже название канала жирным. В канал оно
 *  уходит ссылкой на t.me/iskconru, здесь показываем сам текст. */
const rendered = computed(() => {
  const head = `${draft.value.hashtags} **${draft.value.title}**`.trim()
  const tail = `${draft.value.signature}\n**${CHANNEL_TITLE}**`.trim()
  return `${head}\n\n${draft.value.body.trim()}\n\n${tail}`
})

const charCount = computed(() => rendered.value.length)

// Предел Telegram на одно сообщение. Границы из настроек держат модель,
// а редактору изредка нужен пост длиннее — дальше этого уже нельзя.
const HARD_LIMIT = 4096

// Подпись к альбому короче: пост длиннее уйдёт отдельным сообщением
// под фотографиями. Это не ошибка, но редактор должен знать заранее.
const CAPTION_LIMIT = 1024

const counterClass = computed(() => {
  if (charCount.value > HARD_LIMIT) return 'over'
  if (charCount.value > limits.value.max_chars || charCount.value < limits.value.min_chars)
    return 'near'
  return 'ok'
})

const canPublish = computed(
  () =>
    charCount.value <= HARD_LIMIT &&
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

const refetching = ref(false)

/** Заново прочитать страницу источника. */
async function refetchArticle() {
  refetching.value = true
  error.value = ''
  notice.value = ''
  try {
    const before = {
      images: article.value?.images.length ?? 0,
      videos: article.value?.videos.length ?? 0,
      chars: article.value?.content?.length ?? 0,
    }
    article.value = await api.post<ArticleDetail>(`/api/articles/${articleId}/refetch`)

    const images = article.value.images.length - before.images
    const videos = article.value.videos.length - before.videos
    const chars = (article.value.content?.length ?? 0) - before.chars

    const changes = [
      images ? `фотографий ${images > 0 ? '+' : ''}${images}` : '',
      videos ? `роликов ${videos > 0 ? '+' : ''}${videos}` : '',
      chars ? `текста ${chars > 0 ? '+' : ''}${chars} симв.` : '',
    ].filter(Boolean)

    notice.value = changes.length
      ? `Перечитано: ${changes.join(', ')}`
      : 'Перечитано, на странице источника ничего не изменилось'
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Не удалось перечитать новость'
  } finally {
    refetching.value = false
  }
}

/** Сделать фотографию главной: она уйдёт в альбом первой. */
async function makeCover(image: ArticleImage) {
  if (image.is_cover) return

  const images = article.value?.images ?? []
  const previous = images.map((i) => ({ id: i.id, cover: i.is_cover, selected: i.is_selected }))

  // Красим сразу: щелчок должен отзываться мгновенно
  images.forEach((i) => (i.is_cover = i.id === image.id))
  image.is_selected = true

  try {
    await api.patch<ArticleImage>(`/api/articles/${articleId}/images/${image.id}`, {
      is_cover: true,
    })
  } catch (e) {
    previous.forEach((p) => {
      const found = images.find((i) => i.id === p.id)
      if (found) {
        found.is_cover = p.cover
        found.is_selected = p.selected
      }
    })
    error.value = e instanceof Error ? e.message : 'Не удалось назначить главную'
  }
}

/** Вставляет ссылку на ролик в конец текста поста. */
function addVideoLink(video: ArticleVideo) {
  if (!post.value || draft.value.body.includes(video.url)) return
  draft.value.body = `${draft.value.body.trimEnd()}\n\n${video.url}`
}

/** Куда уйдёт пост — подтягиваем, чтобы предупредить до нажатия кнопки. */
async function loadTelegramState() {
  try {
    telegramState.value = await api.get<TelegramState>('/api/settings/telegram/state')
  } catch {
    // не критично: публиковать это не мешает
  }
}

const publishHint = computed(() => {
  const state = telegramState.value
  if (!state || post.value?.status === 'published') return ''

  if (!state.is_enabled) {
    return 'Вещание выключено: пост получит статус «опубликован», но в канал не уйдёт. Включается в разделе «Публикация в канал».'
  }
  if (!state.ready.length) {
    return 'Вещание включено, но ни один канал не готов принять пост — проверьте права бота в разделе «Публикация в канал».'
  }

  const where = `Уйдёт в ${state.ready.join(', ')}.`
  return state.blocked.length
    ? `${where} Не сможет опубликовать в ${state.blocked.join(', ')} — отправка прервётся на этом канале.`
    : where
})

async function publish() {
  saving.value = true
  error.value = ''
  notice.value = ''
  try {
    // Сначала сохраняем правки, иначе опубликуется прошлая версия
    await api.patch<Post>(`/api/articles/${articleId}/post`, draft.value)
    const result = await api.post<Post>(`/api/articles/${articleId}/publish`)
    if (article.value) article.value.post = result

    // Разделяем два разных исхода: пост мог просто получить статус в базе,
    // а мог реально уйти подписчикам. Раньше сообщение было одно на оба,
    // и выключенное вещание выглядело как пропажа поста.
    notice.value = result.telegram_url
      ? 'Опубликован в канале'
      : 'Пост отмечен опубликованным, но в канал не отправлялся: вещание выключено в разделе «Публикация в канал»'
    await loadTelegramState()
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

// Телеграм принимает в одном альбоме не больше десяти фотографий
const MAX_PHOTOS = 10

const togglingAll = ref(false)

const allSelected = computed(() => {
  const images = article.value?.images ?? []
  if (!images.length) return false
  return selectedImages.value.length >= Math.min(images.length, MAX_PHOTOS)
})

/** Отметить все фотографии разом — или снять отметку со всех. */
async function toggleAllImages() {
  const images = article.value?.images ?? []
  if (!images.length) return

  const select = !allSelected.value
  // Больше десяти телеграм всё равно не возьмёт, поэтому лишние не отмечаем
  const limit = select ? MAX_PHOTOS : images.length
  const previous = images.map((image) => image.is_selected)

  let position = 0
  for (const image of images) {
    image.is_selected = select && position < limit
    if (select) position += 1
  }

  togglingAll.value = true
  error.value = ''
  try {
    await Promise.all(
      images.map((image, index) =>
        image.is_selected === previous[index]
          ? null
          : api.patch<ArticleImage>(`/api/articles/${articleId}/images/${image.id}`, {
              is_selected: image.is_selected,
            }),
      ),
    )
    if (select && images.length > MAX_PHOTOS) {
      notice.value = `Отмечены первые ${MAX_PHOTOS} фотографий — больше телеграм в одном посте не покажет`
    }
  } catch (e) {
    images.forEach((image, index) => (image.is_selected = previous[index]))
    error.value = e instanceof Error ? e.message : 'Не удалось изменить выбор фото'
  } finally {
    togglingAll.value = false
  }
}

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

// --- Правка через модель --------------------------------------------------

const instruction = ref('')
const refining = ref(false)

/** Готовые формулировки: чаще всего просят именно это. */
const QUICK_FIXES = [
  'Сделай короче на 150 символов',
  'Убери последний абзац',
  'Добавь больше конкретики: числа, имена, места',
  'Сделай заголовок короче и живее',
]

async function refinePost() {
  if (!instruction.value.trim()) return

  refining.value = true
  error.value = ''
  notice.value = ''
  try {
    const result = await api.post<Post>(`/api/articles/${articleId}/refine`, {
      instruction: instruction.value.trim(),
    })
    if (article.value) article.value.post = result
    syncDraft()
    notice.value = `Правка внесена: ${result.char_count} символов`
    instruction.value = ''
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Не удалось внести правку'
  } finally {
    refining.value = false
  }
}

// --- Размер поста ---------------------------------------------------------

const resizing = ref(false)

// Короче этого пост делать нечего. Ниже нижней границы канала опускаться
// можно: она держит модель при первой переработке, а редактор вправе
// оставить короткую новость короткой.
const SHORTEST_POST = 200

// Какой длины должен получиться пост. Пока ползунок не трогали, он стоит
// на текущей длине — так видно, что менять ничего и не просили.
const targetChars = ref(0)
const targetMoved = ref(false)

watch(
  charCount,
  (value) => {
    if (!targetMoved.value) targetChars.value = value
  },
  { immediate: true },
)

/** Докуда тянется ползунок. Заметно выше рекомендуемого: изредка нужен
 *  пост на две-три тысячи символов, и до них надо доезжать. */
const sliderMax = computed(() =>
  Math.min(HARD_LIMIT, Math.max(2000, limits.value.max_chars * 3, charCount.value + 200)),
)

function onTargetInput(event: Event) {
  targetMoved.value = true
  targetChars.value = Number((event.target as HTMLInputElement).value)
}

/** На сколько символов просим изменить пост. */
const resizeDelta = computed(() => targetChars.value - charCount.value)

const resizeHint = computed(() => {
  const delta = resizeDelta.value
  if (!delta) return 'столько же — подвиньте ползунок'
  return delta < 0 ? `короче на ${-delta}` : `длиннее на ${delta}`
})

/** Выше рекомендуемого — можно, но стоит сказать об этом вслух. */
const overRecommended = computed(() => targetChars.value > limits.value.max_chars)

/** С фотографиями такой пост уйдёт отдельным сообщением под альбомом. */
const willSplit = computed(
  () => targetChars.value > CAPTION_LIMIT && selectedImages.value.length > 0,
)

const canResize = computed(() => !!post.value && !resizing.value && resizeDelta.value !== 0)

/** Переделать пост под заданную длину — пересобирает модель, а не обрезка. */
async function resizePost() {
  if (!canResize.value) return

  const target = targetChars.value
  resizing.value = true
  error.value = ''
  notice.value = ''
  try {
    const result = await api.post<Post>(`/api/articles/${articleId}/resize`, { target })
    if (article.value) article.value.post = result
    syncDraft()
    // Ползунок отпускаем: он снова встанет на новую длину поста
    targetMoved.value = false
    targetChars.value = result.char_count
    notice.value = `Пост пересобран: ${result.char_count} символов (просили около ${target})`
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Не удалось пересобрать пост'
  } finally {
    resizing.value = false
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

// --- Текст на весь экран ---------------------------------------------------
// Пост правят целиком, а в поле видно четыре строки: чтобы перечитать
// написанное, приходится крутить внутреннюю полосу прокрутки.

const bodyFullscreen = ref(false)

function onEscape(event: KeyboardEvent) {
  if (event.key === 'Escape' && bodyFullscreen.value) bodyFullscreen.value = false
}

onMounted(() => document.addEventListener('keydown', onEscape))
onBeforeUnmount(() => document.removeEventListener('keydown', onEscape))

onMounted(async () => {
  try {
    allowedTags.value = await api.get<string[]>('/api/hashtags')
  } catch {
    // без подсказок теги можно ввести вручную
  }
  await Promise.all([load(), loadTelegramState()])
})
</script>

<template>
  <div class="editor-view">
    <!-- Заглушки повторяют будущую разметку, чтобы при появлении данных
         страница не прыгала: та же панель сверху, те же две карточки -->
    <template v-if="loading">
      <div class="ws-control-bar" aria-busy="true">
        <span class="skeleton skeleton-block" style="width: 92px; height: 30px" />
        <span class="skeleton skeleton-block" style="width: 130px; height: 30px" />
        <span class="row-end row">
          <span class="skeleton skeleton-block" style="width: 110px; height: 22px" />
          <span class="skeleton skeleton-block" style="width: 160px; height: 30px" />
        </span>
      </div>

      <div class="editor-grid" aria-busy="true">
      <section class="ws-surface">
        <div class="ws-surface-head">
          <h2 class="ws-surface-title">Исходная статья</h2>
          <span class="skeleton skeleton-block" style="width: 96px; height: 20px" />
        </div>
        <div class="ws-surface-body stack">
          <span class="skeleton skeleton-text" style="width: 70%; height: 18px" />
          <span class="skeleton skeleton-text" style="width: 40%" />
          <span class="skeleton skeleton-block" style="height: 320px" />
        </div>
      </section>
      <section class="ws-surface">
        <div class="ws-surface-head">
          <h2 class="ws-surface-title">Пост для канала</h2>
          <span class="skeleton skeleton-block" style="width: 74px; height: 20px" />
        </div>
        <div class="ws-surface-body stack">
          <span class="skeleton skeleton-text" style="width: 30%" />
          <span class="skeleton skeleton-block" style="height: 34px" />
          <span class="skeleton skeleton-block" style="height: 120px" />
          <span class="skeleton skeleton-text" style="width: 30%" />
          <span class="skeleton skeleton-block" style="height: 34px" />
          <span class="skeleton skeleton-text" style="width: 30%" />
          <span class="skeleton skeleton-block" style="height: 200px" />
          <span class="skeleton skeleton-text" style="width: 45%" />
          <span class="skeleton skeleton-block" style="height: 90px" />
        </div>
      </section>
      </div>
    </template>

    <template v-else-if="article">
      <div class="ws-control-bar">
        <RouterLink class="ws-btn ws-btn-quiet" :to="{ name: 'articles' }">← К ленте</RouterLink>
        <a class="ws-btn ws-btn-quiet" :href="article.url" target="_blank" rel="noopener">
          Открыть оригинал
        </a>
        <button
          class="ws-btn ws-btn-quiet"
          type="button"
          :disabled="refetching"
          title="Заново прочитать страницу источника: текст, фотографии и ролики"
          @click="refetchArticle"
        >
          {{ refetching ? 'Перечитываем…' : 'Перечитать новость' }}
        </button>
        <a
          v-if="post?.telegram_url"
          class="ws-btn ws-btn-quiet"
          :href="post.telegram_url"
          target="_blank"
          rel="noopener"
          title="Пост, как он вышел в канале"
        >
          Открыть в канале
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

      <ToastStack
        :error="error"
        :notice="notice"
        @clear-error="error = ''"
        @clear-notice="notice = ''"
      />
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
            <!-- Дайджест ISKCON Connection ссылается на dandavats напрямую,
                 поэтому один сюжет часто приходит из нескольких источников -->
            <div v-if="article.repeats.length" class="repeat-note">
              <b>Эта новость есть и в других источниках.</b>
              <ul class="repeat-list">
                <li v-for="(entry, index) in article.repeats" :key="index">
                  <b>{{ entry.source }}</b>

                  <!-- Двойник — отдельная карточка со своим постом. Совпадение
                       по адресу — та же самая карточка, и пост у неё этот же. -->
                  <template v-if="entry.article_id">
                    <span class="muted">— отдельная карточка:</span>
                    <RouterLink :to="{ name: 'article', params: { id: entry.article_id } }">
                      открыть у нас
                    </RouterLink>
                    <span
                      class="ws-badge"
                      :class="entry.post_status ? POST_STATUS_TONE[entry.post_status] : 'neutral'"
                    >
                      {{ entry.post_status ? POST_STATUS_LABELS[entry.post_status] : 'поста нет' }}
                    </span>
                  </template>

                  <template v-else>
                    <span class="muted">— тот же адрес, это та же карточка:</span>
                    <RouterLink :to="{ name: 'article', params: { id: article.id } }">
                      открыть у нас
                    </RouterLink>
                    <span
                      class="ws-badge"
                      :class="post ? POST_STATUS_TONE[post.status] : 'neutral'"
                    >
                      {{ post ? POST_STATUS_LABELS[post.status] : 'поста нет' }}
                    </span>
                  </template>

                  <a
                    v-if="entry.url"
                    :href="entry.url"
                    target="_blank"
                    rel="noopener"
                  >
                    на сайте источника
                  </a>
                  <a
                    v-if="entry.article_id ? entry.telegram_url : post?.telegram_url"
                    :href="(entry.article_id ? entry.telegram_url : post?.telegram_url) as string"
                    target="_blank"
                    rel="noopener"
                  >
                    пост в канале
                  </a>
                </li>
              </ul>
            </div>

            <div v-if="article.content || article.summary" class="source-text">
              {{ article.content || article.summary }}
            </div>
            <!-- Пустой текст — обычное дело, а не сбой: на dandavats так
                 выглядят публикации с видео или аудиозаписью, где на странице
                 стоит один плеер. Пишем это прямо, чтобы не гадать. -->
            <p v-else class="alert alert-info" style="margin: 0">
              На странице источника нет текста — только заголовок. Обычно так
              выглядят публикации с видеозаписью или аудиолекцией: весь материал
              в плеере, пересказывать нечего.
              <a :href="article.url" target="_blank" rel="noopener">Открыть оригинал</a>
              и посмотреть, что там.
            </p>
          </div>
        </section>

        <!-- Пост -->
        <section class="ws-surface">
          <div class="ws-surface-head">
            <h2 class="ws-surface-title">Пост для канала</h2>
            <span class="char-counter" :class="counterClass">
              {{ charCount }} / {{ limits.max_chars }}
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
              <label class="ws-field-label">
                Текст поста
                <button
                  class="ws-btn ws-btn-quiet ws-control-sm"
                  type="button"
                  title="Открыть текст на весь экран"
                  @click="bodyFullscreen = true"
                >
                  На весь экран
                </button>
              </label>
              <textarea v-model="draft.body" class="ws-input"></textarea>
            </div>

            <div class="ws-field">
              <label class="ws-field-label">Размер поста</label>
              <div>
                <div class="resizer" :class="{ 'is-busy': resizing }">
                  <div class="resizer-scale">
                    <span>{{ SHORTEST_POST }}</span>
                    <span class="resizer-band">
                      рекомендуемые {{ limits.min_chars }}–{{ limits.max_chars }}
                    </span>
                    <span>{{ sliderMax }}</span>
                  </div>

                  <input
                    class="resizer-slider"
                    type="range"
                    :min="SHORTEST_POST"
                    :max="sliderMax"
                    step="10"
                    :value="targetChars"
                    :disabled="!post || resizing"
                    aria-label="Нужная длина поста"
                    @input="onTargetInput"
                  />

                  <div class="resizer-readout">
                    <span class="resizer-now">
                      Сейчас <b>{{ charCount }}</b>
                    </span>
                    <span class="resizer-arrow" aria-hidden="true">→</span>
                    <span class="resizer-next" :class="{ 'is-over': overRecommended }">
                      Станет <b>≈&nbsp;{{ targetChars }}</b>
                      <small>{{ resizeHint }}</small>
                    </span>
                    <button
                      class="ws-btn ws-btn-primary resizer-apply"
                      type="button"
                      :disabled="!canResize"
                      @click="resizePost"
                    >
                      {{ resizing ? 'Пересобираем…' : 'Пересобрать' }}
                    </button>
                  </div>
                </div>

                <small v-if="overRecommended" class="ws-help">
                  Выше рекомендуемых {{ limits.max_chars }} — так тоже можно,
                  предел Telegram {{ HARD_LIMIT }}.
                  <template v-if="willSplit">
                    Длиннее {{ CAPTION_LIMIT }} подпись к альбому не вмещает, поэтому
                    текст уйдёт отдельным сообщением под фотографиями.
                  </template>
                </small>
                <small class="ws-help">
                  Двигайте ползунок и жмите «Пересобрать» — текст заново напишет
                  модель по исходной статье, вручную ничего не обрезается.
                  Модель берёт сохранённый пост, поэтому свои правки сохраните заранее.
                </small>
              </div>
            </div>

            <div class="ws-field">
              <label class="ws-field-label">Подпись источника</label>
              <div>
                <input v-model="draft.signature" class="ws-input" placeholder="«ISKCON News» website" />
                <small class="muted">
                  В посте выйдет: {{ draft.signature }}, следующей строкой —
                  «{{ CHANNEL_TITLE }}» жирной ссылкой на канал.
                </small>
              </div>
            </div>

            <div class="ws-field">
              <label class="ws-field-label">
                Фотографии — отметьте те, что пойдут в пост
                <span class="muted">
                  ({{ selectedImages.length }} из {{ article.images.length }})</span
                >
                <button
                  v-if="article.images.length"
                  class="ws-btn ws-btn-quiet ws-control-sm"
                  type="button"
                  :disabled="togglingAll"
                  style="margin-left: 10px"
                  @click="toggleAllImages"
                >
                  {{ allSelected ? 'Снять выбор' : 'Выбрать все' }}
                </button>
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
                    <!-- Значки крепятся к самой миниатюре, а не к карточке:
                         иначе «убрать» уезжает на подпись под фотографией -->
                    <div class="gallery-media">
                      <!-- Файл берём у себя, а не по прямой ссылке: источник
                           закрыт Cloudflare и отдаёт 403 в том числе на картинки -->
                      <img
                        class="gallery-thumb"
                        :src="`/api/articles/${articleId}/images/${image.id}/raw`"
                        :alt="image.caption_ru || image.caption || ''"
                        loading="lazy"
                      />
                      <!-- Главная уходит в альбом первой: именно её видно
                           в ленте канала под свёрнутым постом -->
                      <button
                        type="button"
                        class="cover-mark"
                        :class="{ 'is-on': image.is_cover }"
                        :title="image.is_cover ? 'Это главная фотография поста' : 'Сделать главной'"
                        :aria-pressed="image.is_cover"
                        @click.stop="makeCover(image)"
                      >
                        <NavIcon name="star" />
                      </button>
                      <span v-if="image.is_selected" class="gallery-mark" aria-hidden="true">
                        <NavIcon name="tick" />
                      </span>
                      <button
                        type="button"
                        class="gallery-remove"
                        title="Убрать фотографию"
                        @click.stop="removeImage(image)"
                      >
                        <NavIcon name="close" />
                      </button>
                    </div>
                    <span v-if="image.is_uploaded" class="gallery-badge">своя</span>
                    <span v-else-if="image.from_video" class="gallery-badge">видео</span>
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

            <!-- Ролики из новости. Файл в канал не отправить — Telegram
                 покажет ссылку карточкой, поэтому её и вставляем в текст. -->
            <div v-if="article.videos.length" class="ws-field">
              <label class="ws-field-label">
                Видео из новости
                <span class="muted">({{ article.videos.length }})</span>
              </label>
              <div class="video-list">
                <div v-for="video in article.videos" :key="video.id" class="video-card">
                  <img
                    v-if="video.thumbnail_url"
                    class="video-poster"
                    :src="video.thumbnail_url"
                    alt=""
                    loading="lazy"
                  />
                  <div class="video-body">
                    <a class="video-link" :href="video.url" target="_blank" rel="noopener">
                      {{ video.url }}
                    </a>
                    <div class="muted" style="font-size: 11px">{{ video.provider }}</div>
                  </div>
                  <button
                    class="ws-btn ws-btn-quiet"
                    type="button"
                    :disabled="!post || draft.body.includes(video.url)"
                    @click="addVideoLink(video)"
                  >
                    {{ draft.body.includes(video.url) ? 'Уже в тексте' : 'Вставить в текст' }}
                  </button>
                </div>
              </div>
            </div>

            <div v-if="post" class="ws-field">
              <label class="ws-field-label">Попросить модель поправить</label>
              <div>
                <div class="row">
                  <input
                    v-model="instruction"
                    class="ws-input"
                    style="flex: 1"
                    placeholder="Например: убери второй абзац и добавь, сколько было коров"
                    :disabled="refining"
                    @keydown.enter.prevent="refinePost"
                  />
                  <button
                    class="ws-btn ws-btn-primary"
                    type="button"
                    :disabled="refining || !instruction.trim()"
                    @click="refinePost"
                  >
                    {{ refining ? 'Правим…' : 'Поправить' }}
                  </button>
                </div>
                <div class="row" style="margin-top: 6px; gap: 6px">
                  <button
                    v-for="hint in QUICK_FIXES"
                    :key="hint"
                    type="button"
                    class="ws-chip"
                    :disabled="refining"
                    @click="((instruction = hint), refinePost())"
                  >
                    {{ hint }}
                  </button>
                </div>
                <small class="muted">
                  Правка ложится на текущий текст, включая ваши ручные изменения.
                  Ограничения те же: ничего сверх статьи, теги из списка,
                  предел {{ limits.max_chars }} символов.
                </small>
              </div>
            </div>

            <div class="ws-field">
              <label class="ws-field-label">Предпросмотр</label>
              <div class="post-preview">{{ rendered }}</div>
            </div>

            <p v-if="charCount > HARD_LIMIT" class="alert alert-error">
              Превышен предел Telegram на {{ charCount - HARD_LIMIT }} символов —
              такое сообщение не уйдёт.
            </p>
            <p v-else-if="charCount > CAPTION_LIMIT && selectedImages.length" class="alert">
              В посте {{ charCount }} символов — в подпись к альбому ({{ CAPTION_LIMIT }})
              он не влезет и уйдёт отдельным сообщением под фотографиями.
            </p>
            <p v-else-if="charCount < limits.min_chars" class="alert">
              Короче рекомендуемых {{ limits.min_chars }} на
              {{ limits.min_chars - charCount }} символов — пост вышел скупым.
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

            <!-- Что именно сделает кнопка — видно до нажатия, а не после -->
            <p v-if="publishHint" class="publish-hint muted">{{ publishHint }}</p>

            <p v-if="post?.telegram_url" class="publish-hint">
              Пост в канале:
              <a :href="post.telegram_url" target="_blank" rel="noopener">
                {{ post.telegram_url }}
              </a>
            </p>

            <p v-if="post?.ai_error" class="alert alert-error">{{ post.ai_error }}</p>
          </div>
        </section>
      </div>
    </template>

    <!-- Текст поста на весь экран: правится тут же, а не только читается -->
    <div v-if="bodyFullscreen" class="fullscreen" @click.self="bodyFullscreen = false">
      <div class="fullscreen-box">
        <div class="fullscreen-head">
          <b>Текст поста</b>
          <span class="char-counter" :class="counterClass">
            {{ charCount }} / {{ limits.max_chars }}
          </span>
          <button
            class="ws-btn ws-btn-quiet ws-control-sm fullscreen-close"
            type="button"
            @click="bodyFullscreen = false"
          >
            Закрыть (Esc)
          </button>
        </div>
        <textarea v-model="draft.body" class="ws-input fullscreen-text"></textarea>
        <div class="fullscreen-foot">
          <span class="muted">Правки те же, что и в карточке — не забудьте сохранить.</span>
          <button class="ws-btn ws-btn-primary" :disabled="saving || !post" @click="save">
            {{ saving ? 'Сохраняем…' : 'Сохранить' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
