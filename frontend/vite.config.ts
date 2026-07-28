import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      // Ходим на бэкенд через тот же origin — иначе httpOnly-кука сессии
      // не поедет вместе с запросом.
      '/api': {
        // 8000 на этой машине занят другим проектом, поэтому 8001
        target: 'http://127.0.0.1:8001',
        changeOrigin: true,
      },
    },
  },
})
