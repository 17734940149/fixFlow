<script setup>
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useWorkspace } from '@/composables/useWorkspace'
import AppIcon from '@/components/common/AppIcon.vue'
import SourcePreview from './SourcePreview.vue'
import { demoWebSource } from '@/data/search'

const props = defineProps({ message: { type: Object, required: true } })
const { t } = useI18n()
const { state, running, retryAnswer } = useWorkspace()
const preview = ref(false)
const fullDocument = ref(false)
const source = ref(null)
const statusKey = computed(() => ({ thinking: 'thinking', complete: 'finished', stopped: 'stopped', failed: 'failed' })[props.message.status])
const documents = computed(() => [...new Map((props.message.sources || []).map((item) => [item.doc, item])).values()])
const citations = computed(() => [
  ...(state.user?.role === 'admin' ? props.message.sources || [] : []),
  ...(props.message.network ? [demoWebSource] : []),
])
const executionSteps = computed(() => ['understand', 'searchLibrary', ...(props.message.network ? ['searchWeb'] : []), 'compose'])

// 普通用户打开文档全文；管理员引用可查看原文块，保留不同角色的信息层级。
function openSource(item, full = false) {
  source.value = item
  fullDocument.value = full
  preview.value = true
}
</script>

<template>
  <div v-if="message.role === 'user'" class="chat-message user-message">{{ message.text }}</div>
  <article v-else class="chat-message assistant-message">
    <div class="assistant-title"><AppIcon name="sparkles" /><strong>FixFlow</strong></div>
    <details class="thinking-summary">
      <summary><AppIcon :name="message.status === 'thinking' ? 'loader-circle' : 'circle-check'" :class="{ spinning: message.status === 'thinking' }" /><span>{{ t(`chat.${statusKey}`) }}</span><AppIcon name="chevron-right" class="summary-chevron" /></summary>
      <div class="thinking-content">
        <template v-if="state.user?.role === 'admin'">
          <p class="muted">{{ t('chat.demoTrace') }}</p>
          <div v-for="(key, index) in executionSteps" :key="key" class="execution-step"><span class="step-number">{{ index + 1 }}</span><div><strong>{{ t(`chat.${key}`) }}</strong><p>{{ key === 'understand' ? message.question : key === 'searchLibrary' ? (message.sources || []).map(item => item.id).join(', ') : key === 'searchWeb' ? demoWebSource.answer : t(`chat.${statusKey}`) }}</p></div></div>
        </template>
        <template v-else-if="message.status === 'complete' && !message.noResult"><strong>{{ t('chat.summary') }}</strong><p class="muted">{{ t('chat.summaryHint') }}</p></template>
        <template v-else><strong>{{ t(message.noResult ? 'chat.noResult' : `chat.${statusKey}`) }}</strong><p class="muted">{{ t(message.noResult ? 'chat.noResultHint' : message.status === 'failed' ? 'chat.failureHint' : message.status === 'stopped' ? 'chat.stoppedHint' : 'chat.running') }}</p></template>
        <div v-if="message.status === 'complete' && !message.noResult && documents.length" class="reference-documents">
          <span>{{ t('chat.reference') }}</span><el-button v-for="item in documents" :key="item.doc" size="small" @click="openSource(item, true)"><AppIcon name="files" />{{ item.documentName }}</el-button>
        </div>
      </div>
    </details>
    <div v-if="message.status === 'complete' && !message.noResult" class="answer-body">
      <p v-for="(paragraph, index) in message.text.split(/\n\s*\n/)" :key="index">{{ paragraph }}</p>
      <template v-if="message.network"><h3>{{ t('chat.network') }}</h3><p>{{ demoWebSource.answer }}</p></template>
      <div v-if="citations.length" class="answer-sources">
        <el-popover v-for="(item, index) in citations" :key="item.id" placement="top" width="320" trigger="hover">
          <template #reference><el-button text size="small" @click="openSource(item)">[{{ index + 1 }}] {{ item.id }}</el-button></template>
          <strong>{{ item.documentName }}</strong><p>{{ item.answer.slice(0, 130) }}</p><small>{{ item.source }}</small>
        </el-popover>
      </div>
      <p class="answer-disclaimer">{{ t('chat.demoDisclaimer') }}</p>
    </div>
    <el-alert v-else-if="message.noResult" :title="t('chat.noResult')" :description="t('chat.noResultHint')" type="info" :closable="false" show-icon />
    <el-alert v-else-if="message.status === 'failed'" :title="t('chat.failed')" :description="t('chat.failureHint')" type="error" :closable="false" />
    <p v-else-if="message.status === 'stopped'" class="muted">{{ t('chat.stoppedHint') }}</p>
    <el-button v-if="['failed', 'stopped'].includes(message.status)" class="retry-answer" :disabled="running" @click="retryAnswer(message)"><AppIcon name="refresh-cw" />{{ t('chat.retry') }}</el-button>
    <SourcePreview v-model="preview" :source="source" :full-document="fullDocument" :fail-preview="state.scenario === 'document-preview-fail'" />
  </article>
</template>
