<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/common/AppIcon.vue'
import { useLibrary } from '@/composables/useLibrary'
import DocumentsTable from './DocumentsTable.vue'
import ChunkTable from './ChunkTable.vue'
import ChunkDetailDialog from './ChunkDetailDialog.vue'
import ConflictDialog from './ConflictDialog.vue'
import UploadDialog from './UploadDialog.vue'

const props = defineProps({ modelValue: Boolean, scenario: { type: String, default: 'normal' } })
const emit = defineEmits(['update:modelValue'])
const { t } = useI18n()
const { chunks, approve, publish, unpublish, removeChunks, hasConflict } = useLibrary()
const open = computed({ get: () => props.modelValue, set: value => emit('update:modelValue', value) })
const activeTab = ref('documents')
const documentScope = ref('')
const detailOpen = ref(false)
const detailId = ref('')
const conflictOpen = ref(false)
const conflictId = ref('')
const uploadOpen = ref(false)
const documentVersion = ref(0)
const loadStatus = ref('idle')
const actionError = ref(false)
const failedActions = new Set()
let loadTimer

/** 加载状态只模拟界面分支；重试后展示本地样例，不暗示已经接入业务接口。 */
function loadLibrary(retry = false) {
  clearTimeout(loadTimer)
  loadStatus.value = 'loading'
  loadTimer = setTimeout(() => {
    loadStatus.value = props.scenario === 'admin-load-fail' && !retry ? 'error' : 'ready'
  }, 350)
}

/** 首次演示失败不修改数据，同一动作再次提交恢复正常，便于检查可重试交互。 */
function actionBlocked(action, ids) {
  actionError.value = false
  const key = `${action}:${[...ids].sort().join(',')}`
  if (props.scenario !== 'action-fail' || failedActions.has(key)) return false
  failedActions.add(key)
  actionError.value = true
  ElMessage.error(t('library.actionFailedTitle'))
  return true
}

/** 从文档数量进入全部块视图，保留来源范围并与全局审核列表区分。 */
function openDocumentChunks(id) {
  documentScope.value = id
}

/** 详情以编号关联共享数据，操作后立即反映当前状态，而不保留过期副本。 */
function openDetail(id) {
  detailId.value = id
  detailOpen.value = true
}

/** 所有入口复用同一状态检查和确认流程，避免详情与批量按钮行为不一致。 */
async function handleAction(action, ids) {
  const current = chunks.filter(chunk => ids.includes(chunk.id) && !chunk.deleted)
  if (!current.length) { ElMessage.warning(t('library.staleOperation')); return }
  if (action === 'conflict') {
    if (current[0].status !== 'pending' || !hasConflict(current[0])) { ElMessage.warning(t('library.staleOperation')); return }
    conflictId.value = current[0].id
    conflictOpen.value = true
    return
  }
  let count = 0
  if (['approve', 'publish'].includes(action) && actionBlocked(action, ids)) return
  if (action === 'approve') count = approve(ids)
  if (action === 'publish') count = publish(ids)
  if (action === 'unpublish' || action === 'delete') {
    const eligible = current.filter(chunk => chunk.status === (action === 'delete' ? 'offline' : 'published') && !hasConflict(chunk))
    if (!eligible.length) { ElMessage.warning(t('library.staleOperation')); return }
    const message = action === 'delete'
      ? t('library.deleteConfirm', { count: eligible.length, ids: eligible.map(chunk => chunk.id).join('、') })
      : t('library.unpublishConfirm', { id: eligible[0].id })
    try {
      await ElMessageBox.confirm(message, t(action === 'delete' ? 'library.deleteTitle' : 'library.unpublishTitle'), {
        confirmButtonText: t(action === 'delete' ? 'library.confirmDelete' : 'library.confirmUnpublish'),
        cancelButtonText: t('common.cancel'), type: 'warning', closeOnClickModal: false,
      })
    } catch { return }
    if (actionBlocked(action, eligible.map(chunk => chunk.id))) return
    count = action === 'delete' ? removeChunks(eligible.map(chunk => chunk.id)) : unpublish([eligible[0].id])
    if (action === 'delete' && eligible.some(chunk => chunk.id === detailId.value)) detailOpen.value = false
  }
  if (!count) { ElMessage.warning(t('library.staleOperation')); return }
  const messageKeys = { approve: 'approvedSuccess', publish: 'publishedSuccess', unpublish: 'unpublishedSuccess', delete: 'deletedSuccess' }
  ElMessage.success(t(`library.${messageKeys[action]}`, { count }))
}

/** 新文件登记后重新展示未筛选的文档列表，避免上传结果被旧查询条件隐藏。 */
function documentAdded() {
  activeTab.value = 'documents'
  documentScope.value = ''
  documentVersion.value += 1
}

watch(activeTab, () => { documentScope.value = ''; actionError.value = false })
watch(() => props.modelValue, value => {
  if (value) { activeTab.value = 'documents'; documentScope.value = ''; actionError.value = false; failedActions.clear(); loadLibrary() }
  else { clearTimeout(loadTimer); detailOpen.value = false; conflictOpen.value = false; uploadOpen.value = false }
})
watch(() => props.scenario, () => { failedActions.clear(); actionError.value = false; if (props.modelValue) loadLibrary() })
onBeforeUnmount(() => clearTimeout(loadTimer))
</script>

<template>
  <el-drawer v-model="open" :title="t('library.title')" direction="rtl" size="50%" class="fixflow-library-drawer" :modal="false" :lock-scroll="false" append-to-body :close-on-click-modal="false">
    <el-tabs v-model="activeTab" class="library-main-tabs">
      <el-tab-pane name="documents"><template #label><span class="library-tab-label"><AppIcon name="files" />{{ t('library.documents') }}</span></template></el-tab-pane>
      <el-tab-pane name="chunks"><template #label><span class="library-tab-label"><AppIcon name="list-checks" />{{ t('library.review') }}</span></template></el-tab-pane>
    </el-tabs>
    <div class="library-content">
      <div v-if="loadStatus === 'loading'" :aria-label="t('library.loadingLibrary')" role="status"><el-skeleton :rows="7" animated /><p class="muted">{{ t('library.loadingLibrary') }}</p></div>
      <div v-else-if="loadStatus === 'error'"><el-alert :title="t('library.loadFailedTitle')" :description="t('library.loadFailed')" type="error" :closable="false" /><el-button type="primary" class="library-retry" @click="loadLibrary(true)"><AppIcon name="refresh-cw" />{{ t('common.retry') }}</el-button></div>
      <template v-else-if="loadStatus === 'ready'">
        <el-alert v-if="actionError" :title="t('library.actionFailedTitle')" :description="t('library.actionFailed')" type="error" :closable="false" class="library-action-error" />
        <DocumentsTable v-if="activeTab === 'documents' && !documentScope" :key="documentVersion" :scenario="scenario" @open-chunks="openDocumentChunks" @upload="uploadOpen = true" />
        <ChunkTable v-else :key="`${activeTab}:${documentScope}`" :document-id="documentScope" @back="documentScope = ''" @detail="openDetail" @action="handleAction" />
      </template>
    </div>
  </el-drawer>
  <ChunkDetailDialog v-model="detailOpen" :chunk-id="detailId" :allow-actions="activeTab === 'chunks'" @action="handleAction" />
  <ConflictDialog v-model="conflictOpen" :chunk-id="conflictId" :scenario="scenario" />
  <UploadDialog v-model="uploadOpen" :scenario="scenario" @added="documentAdded" />
</template>

<style>
.fixflow-library-drawer { min-width: 680px; border-left: 1px solid var(--border); background: var(--surface-raised); box-shadow: -8px 0 30px rgb(0 0 0 / 6%); }
.fixflow-library-drawer .el-drawer__header { margin: 0; padding: 24px; min-height: 64px; border-bottom: 1px solid var(--border); background: var(--surface); color: var(--text); }
.fixflow-library-drawer .el-drawer__title { font-size: 16px; font-weight: 600; }
.fixflow-library-drawer .el-drawer__body { display: flex; flex-direction: column; padding: 0; overflow: hidden; }
.library-main-tabs { flex: none; background: var(--surface); }
.library-main-tabs > .el-tabs__header { margin: 0; padding: 0 24px; }
.library-main-tabs > .el-tabs__content { display: none; }
.library-main-tabs .el-tabs__item { height: 49px; font-size: 13px; }
.library-tab-label { display: inline-flex; align-items: center; gap: 8px; }
.library-content { padding: 24px; overflow: auto; min-height: 0; }
.library-retry { margin-top: 16px; }
.library-action-error { margin-bottom: 20px; }
.library-filter { margin-bottom: 23px; }
.library-filter-fields { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 20px; }
.library-filter .el-form-item { margin-bottom: 12px; }
.library-filter .el-form-item__label { color: var(--muted); font-size: 12px; line-height: 18px; margin-bottom: 8px; }
.library-filter .el-input, .library-filter .el-select { width: 100%; }
.library-filter-actions { display: flex; justify-content: flex-end; margin-top: 2px; }
.library-table-toolbar { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; min-height: 36px; margin-bottom: 14px; }
.library-table-toolbar h3 { margin: 0; font-size: 13px; font-weight: 600; color: var(--text); }
.library-table-section .el-table { border: 1px solid var(--border); border-radius: 5px; font-size: 12px; }
.library-table-section .el-table th.el-table__cell { font-weight: 400; color: var(--muted); }
.library-table-section .el-table .el-table__cell { padding: 14px 0; }
.library-table-section .el-table .cell { padding: 0 12px; }
.el-dialog.library-dialog { max-width: calc(100vw - 32px); padding: 0; border: 1px solid var(--border); border-radius: 7px; overflow: hidden; }
.library-dialog .el-dialog__header { margin: 0; padding: 22px 24px; border-bottom: 1px solid var(--border); }
.library-dialog .el-dialog__title { font-size: 16px; font-weight: 600; }
.library-dialog .el-dialog__headerbtn { top: 15px; right: 13px; }
.library-dialog .el-dialog__body { max-height: 65vh; overflow: auto; padding: 24px; color: var(--text); }
.library-dialog .el-dialog__footer { border-top: 1px solid var(--border); padding: 16px 24px; }
.library-error { color: var(--danger); font-size: 12px; margin: 15px 0 0; }
@media (max-width: 760px) {
  .fixflow-library-drawer { width: 100% !important; min-width: 0; }
  .library-content { padding: 20px 16px; }
  .fixflow-library-drawer .el-drawer__header { padding: 20px 16px; }
  .library-main-tabs > .el-tabs__header { padding: 0 16px; }
  .library-filter-fields { gap: 12px; }
}
@media (max-width: 480px) {
  .library-filter-fields { grid-template-columns: minmax(0, 1fr); gap: 0; }
  .library-dialog .el-dialog__body { padding: 20px 16px; }
}
</style>
