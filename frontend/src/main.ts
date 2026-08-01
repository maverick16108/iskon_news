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

// Chrome считает клик по ссылке «видимым фокусом» и рисует вокруг неё обводку —
// после перехода по пункту меню она оставалась висеть. Отличаем мышь от
// клавиатуры сами: обводку показываем только тем, кто ходит табом, иначе
// пришлось бы убирать её совсем и потерять навигацию с клавиатуры.
document.addEventListener('pointerdown', () => {
  document.documentElement.classList.remove('kbd-nav')
})

document.addEventListener('keydown', (event) => {
  if (event.key === 'Tab') document.documentElement.classList.add('kbd-nav')
})

createApp(App).use(createPinia()).use(router).mount('#app')
