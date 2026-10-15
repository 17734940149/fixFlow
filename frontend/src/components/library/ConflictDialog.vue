<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'
import { useLibrary } from '@/composables/useLibrary'

const props = defineProps({ modelValue: Boolean, chunkId: { type: String, default: '' }, scenario: { type: String, default: 'normal' } })
const emit = defineEmits(['update:modelValue', 'resolved'])
const { t } = useI18n()
const { chunks, resolveConflict } = useLibrary()
const open = computed({ get: () => props.modelValue, set: value => emit('update:modelValue', value) })
const fresh = computed(() => chunks.find(chunk => chunk.id === props.chunkId && !chunk.deleted))
const old = computed(() => chunks.find(chunk => chunk.id === fresh.value?.conflict && !chunk.deleted))
const choice = ref('')
const error = ref('')
const failedAttempt = ref(false)

/** 每次打开重新确认选择，防止上一次的决定被带入另一组冲突。 */
function resetChoice() {
  choice.value = ''
  error.value = ''
  failedAttempt.value = false
}

/** 提交时验证新旧状态，再同步变更，避免旧记录已下架时继续套用替换规则。 */
function confirmChoice() {
  if (!choice.value) { error.value = 'chooseRequired'; return }
  if (props.scenario === 'action-fail' && !failedAttempt.value) { failedAttempt.value = true; error.value = 'actionFailed'; return }
  if (!resolveConflict(props.chunkId, choice.value)) { error.value = 'conflictChanged'; return }
  ElMessage.success(t(choice.value === 'new' ? 'library.keptNew' : 'library.keptOld'))
  emit('resolved')
  open.value = false
}

watch(() => props.modelValue, value => { if (value) resetChoice() })
</script>

<template>
  <el-dialog v-model="open" :title="t('library.conflictTitle')" width="720px" class="library-dialog" append-to-body :close-on-click-modal="false">
    <el-alert :title="t('library.conflictHintTitle')" :description="t('library.conflictHint')" type="info" :closable="false" />
    <el-radio-group v-model="choice" class="conflict-choices" @change="error = ''">
      <el-radio v-if="old" value="old" class="conflict-choice">
        <div><strong>{{ t('library.keepOld', { id: old.id }) }}</strong><p class="conflict-original">{{ old.answer }}</p><small>{{ old.source }} · {{ t(`library.${old.status}`) }}</small></div>
      </el-radio>
      <el-radio v-if="fresh" value="new" class="conflict-choice">
        <div><strong>{{ t('library.keepNew', { id: fresh.id }) }}</strong><p class="conflict-original">{{ fresh.answer }}</p><small>{{ fresh.source }} · {{ t(`library.${fresh.status}`) }}</small></div>
      </el-radio>
    </el-radio-group>
    <p v-if="error" class="library-error" role="alert">{{ t(`library.${error}`) }}</p>
    <template #footer><el-button @click="open = false">{{ t('common.cancel') }}</el-button><el-button type="primary" @click="confirmChoice">{{ t('library.confirmChoice') }}</el-button></template>
  </el-dialog>
</template>

<style scoped>
.conflict-choices { display: flex; flex-direction: column; gap: 16px; width: 100%; margin-top: 18px; }
.conflict-choice { display: flex; width: 100%; height: auto; margin: 0; align-items: flex-start; padding: 20px; border: 1px solid var(--border); border-radius: 5px; }
.conflict-choice.is-checked { border-color: var(--accent); background: var(--accent-soft); }
.conflict-choice :deep(.el-radio__input) { margin-top: 2px; }
.conflict-choice :deep(.el-radio__label) { white-space: normal; min-width: 0; padding-left: 14px; color: var(--text); }
.conflict-original { white-space: pre-wrap; overflow-wrap: anywhere; font-size: 13px; line-height: 1.9; margin: 14px 0; }
.conflict-choice small { display: block; color: var(--muted); line-height: 1.7; font-size: 12px; }
</style>
