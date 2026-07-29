import { createPinia } from 'pinia'
import { createApp } from 'vue'

// Тема UIUIDS — порядок важен: токены, затем база, затем компоненты
import './assets/theme/tokens.css'
import './assets/theme/base.css'
import './assets/theme/system-contract.css'
import './assets/theme/workspace-pages.css'
import './assets/app.css'

import { apply as applyAppearance } from './appearance'
import App from './App.vue'
import router from './router'

document.body.classList.add('workspace-body')
applyAppearance()

createApp(App).use(createPinia()).use(router).mount('#app')
