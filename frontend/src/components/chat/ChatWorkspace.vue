<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useWorkspace } from '@/composables/useWorkspace'
import AppIcon from '@/components/common/AppIcon.vue'
import ChatMessage from './ChatMessage.vue'

const { t } = useI18n()
const { state, auth, running, submitting, sendQuestion, stopAnswer } = useWorkspace()
const scrollArea = ref()
const count = computed(() => [...state.draft].length)
const unavailable = computed(() => auth.restoring || auth.pending || submitting.value)

// 只在消息数量或生成状态变化时滚到底部，输入和偏好修改不会打断用户阅读。
watch(() => state.messages.map((message) => `${message.id}:${message.status}`).join(','), async () => {
  await nextTick()
  scrollArea.value?.scrollTo({ top: scrollArea.value.scrollHeight, behavior: 'auto' })
})
</script>

<template>
  <main class="chat-workspace">
    <div class="workspace-heading"><h1>{{ t('chat.title') }}</h1><span class="muted">{{ t(running ? 'chat.running' : state.activeSession ? 'chat.mySessions' : 'chat.newChat') }}</span></div>
    <div ref="scrollArea" class="chat-scroll">
      <div class="chat-inner" :class="{ 'is-empty': !state.messages.length }">
        <div v-if="!state.messages.length" class="empty-chat"><span class="empty-icon"><AppIcon name="workflow" /></span><h2>{{ t('chat.welcome') }}</h2><p>{{ t('chat.welcomeHint') }}</p></div>
        <ChatMessage v-for="message in state.messages" :key="message.id" :message="message" />
      </div>
    </div>
    <div class="composer-wrap">
      <form class="composer" @submit.prevent="sendQuestion">
        <el-input v-model="state.draft" type="textarea" resize="none" :rows="2" :disabled="running || unavailable" :placeholder="t('chat.placeholder')" :aria-label="t('chat.inputLabel')" @keydown.ctrl.enter.prevent="sendQuestion" />
        <div class="composer-bottom"><span class="question-count" :class="{ 'over-limit': count > 1000 }">{{ count }} / 1000</span><el-button v-if="running" @click="stopAnswer"><AppIcon name="square" />{{ t('chat.stop') }}</el-button><el-button v-else type="primary" native-type="submit" :disabled="unavailable"><AppIcon name="arrow-up" />{{ t('chat.send') }}</el-button></div>
      </form>
      <div class="composer-error" role="status">{{ state.errorKey ? t(state.errorKey) : '' }}</div>
    </div>
  </main>
</template>
