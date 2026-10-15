<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps({ modelValue: Boolean, source: Object, fullDocument: Boolean, failPreview: Boolean })
const emit = defineEmits(['update:modelValue'])
const { t } = useI18n()
const open = computed({ get: () => props.modelValue, set: (value) => emit('update:modelValue', value) })
const phase = ref('ready')
let previewTimer

// 只演示原稿的加载与恢复交互，业务数据来自已保存的示例快照。
function loadPreview(retry = false) {
  clearTimeout(previewTimer)
  if (!props.fullDocument) { phase.value = 'ready'; return }
  phase.value = 'loading'
  previewTimer = setTimeout(() => { phase.value = props.failPreview && !retry ? 'failed' : 'ready' }, 350)
}

watch(() => props.modelValue, (value) => {
  if (value) loadPreview()
  else clearTimeout(previewTimer)
})
onBeforeUnmount(() => clearTimeout(previewTimer))
</script>

<template>
  <el-dialog v-model="open" :title="t(fullDocument ? 'chat.previewTitle' : source?.kind === 'web' ? 'chat.webSource' : 'chat.source')" :width="fullDocument ? '90vw' : '760px'" class="source-dialog">
    <div v-if="phase === 'loading'" class="preview-state" role="status">{{ t('chat.previewLoading') }}</div>
    <div v-else-if="phase === 'failed'" class="preview-state"><el-alert :title="t('chat.previewFailed')" type="error" :closable="false" /><el-button @click="loadPreview(true)">{{ t('chat.retryPreview') }}</el-button></div>
    <template v-else-if="source">
      <p v-if="fullDocument" class="dialog-intro">{{ t('chat.previewHint') }}</p>
      <h3>{{ source.documentName }}</h3>
      <p class="muted">{{ fullDocument ? source.documentName : source.source }}</p>
      <div class="source-document">{{ fullDocument ? source.documentText : source.answer }}</div>
    </template>
    <template #footer><el-button @click="open = false">{{ t('common.close') }}</el-button></template>
  </el-dialog>
</template>

<style scoped>
.preview-state { min-height: 220px; display: flex; flex-direction: column; justify-content: center; align-items: center; gap: 20px; color: var(--muted); }
.preview-state .el-alert { max-width: 460px; }
</style>
