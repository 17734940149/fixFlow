import { computed, ref, watch } from 'vue'
import i18n from '@/lang'
import { readStorage, writeStorage } from '@/utils/storage'

export const themes = ['jade', 'mono', 'blue', 'graphite']
const savedTheme = readStorage('fixflow:theme', 'jade')
const theme = ref(themes.includes(savedTheme) ? savedTheme : 'jade')

// 偏好独立于登录状态，切换语言或主题不会重建业务组件和清空用户草稿。
export function usePreferences() {
  return {
    theme,
    language: i18n.global.locale,
    isEnglish: computed(() => i18n.global.locale.value === 'en'),
    setLanguage,
    setTheme,
  }
}

// 同步文档语言供辅助阅读工具识别，文案变化由 Vue 国际化完成。
function setLanguage(value) {
  if (!['zh', 'en'].includes(value)) return
  i18n.global.locale.value = value
}

// 只接受已有主题编号，避免无效的本地配置破坏页面配色。
function setTheme(value) {
  if (themes.includes(value)) theme.value = value
}

watch(theme, (value) => {
  document.documentElement.dataset.theme = value
  writeStorage('fixflow:theme', value)
}, { immediate: true })

watch(i18n.global.locale, (value) => {
  document.documentElement.lang = value === 'en' ? 'en' : 'zh-CN'
  writeStorage('fixflow:language', value)
}, { immediate: true })
