import { createRouter, createWebHistory } from 'vue-router'

import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
      meta: { public: true, title: 'Вход' },
    },
    {
      path: '/',
      name: 'articles',
      component: () => import('@/views/ArticlesView.vue'),
      meta: { title: 'Лента новостей' },
    },
    {
      path: '/articles/:id',
      name: 'article',
      component: () => import('@/views/ArticleEditorView.vue'),
      meta: { title: 'Подготовка поста' },
    },
    {
      path: '/sources',
      name: 'sources',
      component: () => import('@/views/SourcesView.vue'),
      meta: { title: 'Источники' },
    },
    {
      path: '/users',
      name: 'users',
      component: () => import('@/views/UsersView.vue'),
      meta: { title: 'Пользователи', superadmin: true },
    },
    {
      path: '/prompts',
      name: 'prompts',
      component: () => import('@/views/PromptsView.vue'),
      meta: { title: 'Промпты', superadmin: true },
    },
    {
      path: '/settings/llm',
      name: 'llm-settings',
      component: () => import('@/views/LlmSettingsView.vue'),
      meta: { title: 'Настройки модели', superadmin: true },
    },
    {
      path: '/settings/telegram',
      name: 'telegram-settings',
      component: () => import('@/views/TelegramSettingsView.vue'),
      meta: { title: 'Публикация в канал', superadmin: true },
    },
    {
      path: '/audit',
      name: 'audit',
      component: () => import('@/views/AuditView.vue'),
      meta: { title: 'Журнал действий', superadmin: true },
    },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  await auth.restore()

  if (to.meta.public) {
    return auth.isAuthenticated ? { name: 'articles' } : true
  }

  if (!auth.isAuthenticated) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }

  if (to.meta.superadmin && !auth.isSuperadmin) {
    return { name: 'articles' }
  }

  return true
})

export default router
