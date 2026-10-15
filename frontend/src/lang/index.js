import { createI18n } from 'vue-i18n'
import zh from './zh'
import en from './en'
import { readStorage } from '@/utils/storage'

export default createI18n({
  legacy: false,
  locale: readStorage('fixflow:language', 'zh') === 'en' ? 'en' : 'zh',
  fallbackLocale: 'zh',
  messages: { zh, en },
})
