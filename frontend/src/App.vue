<script setup>
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import en from 'element-plus/es/locale/lang/en'
import { useWorkspace } from '@/composables/useWorkspace'
import DemoToolbar from '@/components/layout/DemoToolbar.vue'
import AppHeader from '@/components/layout/AppHeader.vue'
import SessionSidebar from '@/components/layout/SessionSidebar.vue'
import ChatWorkspace from '@/components/chat/ChatWorkspace.vue'
import LoginDialog from '@/components/account/LoginDialog.vue'
import SettingsDialog from '@/components/account/SettingsDialog.vue'
import LibraryDrawer from '@/components/library/LibraryDrawer.vue'

const { locale } = useI18n()
const { state } = useWorkspace()
const elementLocale = computed(() => locale.value === 'en' ? en : zhCn)
const settingsOpen = ref(false)
const libraryOpen = ref(false)

// 登出后立即销毁管理界面；这只是演示可见性控制，真实权限仍需后端鉴权。
watch(() => state.user, (user) => {
  if (!user) { settingsOpen.value = false; libraryOpen.value = false }
})
</script>

<template>
  <el-config-provider :locale="elementLocale">
    <div class="app-shell">
      <DemoToolbar />
      <AppHeader @open-library="libraryOpen = true" />
      <div class="workspace-layout"><SessionSidebar @open-settings="settingsOpen = true" /><ChatWorkspace /></div>
    </div>
    <LoginDialog />
    <SettingsDialog v-if="state.user" v-model="settingsOpen" />
    <LibraryDrawer v-if="state.user?.role === 'admin'" v-model="libraryOpen" :scenario="state.scenario" />
  </el-config-provider>
</template>
