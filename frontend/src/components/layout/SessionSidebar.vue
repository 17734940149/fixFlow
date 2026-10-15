<script setup>
import { useI18n } from 'vue-i18n'
import { useWorkspace } from '@/composables/useWorkspace'
import AppIcon from '@/components/common/AppIcon.vue'

defineEmits(['open-settings'])
const { t } = useI18n()
const { state, running, newChat, selectSession } = useWorkspace()
</script>

<template>
  <aside class="session-sidebar">
    <el-button class="new-chat" @click="newChat"><AppIcon name="square-pen" />{{ t('chat.newChat') }}</el-button>
    <div class="side-heading">{{ t('chat.mySessions') }}</div>
    <div class="session-list">
      <div v-if="!state.user" class="side-empty">{{ t('chat.guestSessions') }}</div>
      <div v-else-if="!state.sessions.length" class="side-empty">{{ t('chat.noSessions') }}</div>
      <button v-for="session in state.sessions" :key="session.id" class="session-item" :class="{ selected: session.id === state.activeSession }" :disabled="running" @click="selectSession(session)">
        <AppIcon name="message-square" /><span>{{ session.title }}</span>
      </button>
    </div>
    <div v-if="state.user" class="sidebar-footer">
      <button class="identity-button" @click="$emit('open-settings')">
        <img v-if="state.user.avatar" :src="state.user.avatar" :alt="t('account.avatar')" />
        <AppIcon v-else name="user-round" /><span>{{ state.user.name }}</span>
      </button>
      <el-button text circle :aria-label="t('account.settings')" @click="$emit('open-settings')"><AppIcon name="settings" /></el-button>
    </div>
  </aside>
</template>
