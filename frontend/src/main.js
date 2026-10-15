import { createApp } from 'vue'
import {
  ElAlert, ElButton, ElConfigProvider, ElDialog, ElDrawer, ElEmpty,
  ElForm, ElFormItem, ElInput, ElOption, ElPagination, ElPopover,
  ElProgress, ElRadio, ElRadioButton, ElRadioGroup, ElSelect, ElSkeleton, ElTable, ElTableColumn,
  ElTabPane, ElTabs, ElTag, ElTooltip, ElUpload,
} from 'element-plus'
import 'element-plus/dist/index.css'
import App from './App.vue'
import i18n from './lang'
import './assets/fonts.css'
import './styles/theme.css'
import './styles/app.css'

const app = createApp(App).use(i18n)
// 按现有页面注册组件，避免把未使用的组件逻辑一起交给浏览器下载。
const components = [
  ElAlert, ElButton, ElConfigProvider, ElDialog, ElDrawer, ElEmpty,
  ElForm, ElFormItem, ElInput, ElOption, ElPagination, ElPopover,
  ElProgress, ElRadio, ElRadioButton, ElRadioGroup, ElSelect, ElSkeleton, ElTable, ElTableColumn,
  ElTabPane, ElTabs, ElTag, ElTooltip, ElUpload,
]
components.forEach((component) => app.component(component.name, component))
app.mount('#app')
