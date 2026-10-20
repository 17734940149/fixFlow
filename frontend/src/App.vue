<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import en from 'element-plus/es/locale/lang/en'
import { useWorkspace } from '@/composables/useWorkspace'
import { useAuth } from '@/composables/useAuth'
import DemoToolbar from '@/components/layout/DemoToolbar.vue'
import AppHeader from '@/components/layout/AppHeader.vue'
import SessionSidebar from '@/components/layout/SessionSidebar.vue'
import ChatWorkspace from '@/components/chat/ChatWorkspace.vue'
import LoginDialog from '@/components/account/LoginDialog.vue'
import SettingsDialog from '@/components/account/SettingsDialog.vue'
import LibraryDrawer from '@/components/library/LibraryDrawer.vue'

const { locale, t } = useI18n()
const { state, auth, logout } = useWorkspace()
const { restoreSession, verifySession } = useAuth()
const elementLocale = computed(() => locale.value === 'en' ? en : zhCn)
const settingsOpen = ref(false)
const libraryOpen = ref(false)

// 后端返回的角色变化立即收起管理抽屉，避免降权后继续显示之前打开的管理内容。
watch(() => state.user?.role, (role) => {
  if (!role) settingsOpen.value = false
  if (role !== 'admin') libraryOpen.value = false
})

// 返回页面时向服务器复核身份，让停用、到期和角色变动能够及时反映到当前界面。
function checkSessionOnFocus() {
  if (auth.user && !auth.restoring && !auth.pending) void verifySession()
}

// 挂载只恢复服务端认可的身份，销毁时释放监听，防止重新挂载造成重复校验请求。
onMounted(() => {
  void restoreSession()
  window.addEventListener('focus', checkSessionOnFocus)
})
onBeforeUnmount(() => window.removeEventListener('focus', checkSessionOnFocus))
</script>

<template>
  <el-config-provider :locale="elementLocale">
    <div class="app-shell">
      <DemoToolbar />
      <AppHeader @open-library="libraryOpen = true" />
      <el-alert v-if="auth.noticeKey" :title="t(auth.noticeKey)" type="warning" :closable="false" show-icon>
        <el-button v-if="auth.noticeKey === 'account.sessionCheckFailed'" text :disabled="auth.restoring || auth.pending" @click="verifySession">{{ t('common.retry') }}</el-button>
        <el-button v-else-if="auth.noticeKey === 'account.logoutFailed'" text :disabled="auth.restoring || auth.pending" @click="logout">{{ t('account.retryLogout') }}</el-button>
      </el-alert>
      <div class="workspace-layout"><SessionSidebar @open-settings="settingsOpen = true" /><ChatWorkspace /></div>
    </div>
    <LoginDialog />
    <SettingsDialog v-if="state.user" v-model="settingsOpen" />
    <LibraryDrawer v-if="state.user?.role === 'admin'" v-model="libraryOpen" :scenario="state.scenario" />
  </el-config-provider>
</template>
