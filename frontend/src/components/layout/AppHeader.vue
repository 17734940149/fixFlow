<script setup>
import { useI18n } from 'vue-i18n'
import { useWorkspace } from '@/composables/useWorkspace'
import { usePreferences } from '@/composables/usePreferences'
import AppIcon from '@/components/common/AppIcon.vue'

defineEmits(['open-library'])
const { t } = useI18n()
const { state, auth, logout } = useWorkspace()
const { language, setLanguage } = usePreferences()
</script>

<template>
  <header class="app-header">
    <div class="header-start">
      <a class="brand" href="#" aria-label="FixFlow"><span class="brand-mark"><AppIcon name="workflow" /></span><strong>FixFlow</strong></a>
      <el-button v-if="state.user?.role === 'admin'" plain type="primary" @click="$emit('open-library')">
        <AppIcon name="database" />{{ t('chat.library') }}
      </el-button>
    </div>
    <div class="header-end">
      <el-button text :aria-label="t('common.language')" @click="setLanguage(language === 'zh' ? 'en' : 'zh')">
        <span :class="{ 'language-active': language === 'zh' }">ZH</span><span class="language-divider">/</span><span :class="{ 'language-active': language === 'en' }">EN</span>
      </el-button>
      <el-button v-if="auth.restoring" text disabled>{{ t('account.restoringSession') }}</el-button>
      <el-button v-else-if="!state.user" text :disabled="auth.pending" @click="state.loginOpen = true"><AppIcon name="log-in" />{{ t('account.login') }}</el-button>
      <el-button v-else text :loading="auth.pending" :disabled="auth.pending" @click="logout"><AppIcon name="log-out" />{{ t(auth.pending ? 'account.loggingOut' : 'account.logout') }}</el-button>
    </div>
  </header>
</template>
