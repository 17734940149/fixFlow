<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/common/AppIcon.vue'
import { useLibrary } from '@/composables/useLibrary'
import LibraryPagination from './LibraryPagination.vue'

const props = defineProps({ scenario: { type: String, default: 'normal' } })
const emit = defineEmits(['open-chunks', 'upload'])
const { t } = useI18n()
const { documents, documentChunks } = useLibrary()
const filter = reactive({ name: '', stage: '' })
const applied = reactive({ name: '', stage: '' })
const page = ref(1)
const pageSize = 10
const stages = ['complete', 'pendingIntegration', 'processing', 'failed']
const stageKeys = { complete: 'stageComplete', pendingIntegration: 'stagePendingIntegration', processing: 'stageProcessing', failed: 'stageFailed' }
const processingDemo = reactive({ documentId: '', stage: '', progress: 0, step: '' })
let processingTimer
const filtered = computed(() => documents.filter(document => (
  (!applied.name || `${document.name} ${document.fileName}`.toLocaleLowerCase().includes(applied.name.toLocaleLowerCase())) &&
  (!applied.stage || stageOf(document) === applied.stage)
)))
const rows = computed(() => filtered.value.slice((page.value - 1) * pageSize, page.value * pageSize))

/** 点击查询才应用条件，避免输入过程中列表不断变化打断用户核对。 */
function applyFilter() {
  Object.assign(applied, { name: filter.name.trim(), stage: filter.stage })
  page.value = 1
}

/** 同时重置输入和已应用条件，确保查询结果与界面字段一致。 */
function resetFilter() {
  Object.assign(filter, { name: '', stage: '' })
  applyFilter()
}

/** 处理演示仅覆盖内置示例的展示状态，真实文件不会被标为已解析或产生假正文。 */
function stageOf(document) {
  return document.example && processingDemo.documentId === document.id ? processingDemo.stage : document.stage
}

/** 用内置文档呈现进度与失败重试，不改变原有块数据或调用尚未接入的解析服务。 */
function startProcessing(documentId, fail = true) {
  clearInterval(processingTimer)
  Object.assign(processingDemo, { documentId, stage: 'processing', progress: 8, step: 'processReading' })
  processingTimer = setInterval(() => {
    processingDemo.progress = Math.min(100, processingDemo.progress + 24)
    processingDemo.step = processingDemo.progress < 40 ? 'processExtracting' : 'processSplitting'
    if (fail && processingDemo.progress >= 72) { processingDemo.stage = 'failed'; clearInterval(processingTimer) }
    else if (processingDemo.progress === 100) { processingDemo.stage = 'complete'; clearInterval(processingTimer) }
  }, 300)
}

watch(() => props.scenario, scenario => {
  clearInterval(processingTimer)
  Object.assign(processingDemo, { documentId: '', stage: '', progress: 0, step: '' })
  const example = documents.find(document => document.example)
  if (scenario === 'process-fail' && example) startProcessing(example.id)
}, { immediate: true })
onBeforeUnmount(() => clearInterval(processingTimer))
watch(() => filtered.value.length, total => { page.value = Math.min(page.value, Math.max(1, Math.ceil(total / pageSize))) })
</script>

<template>
  <el-alert v-if="scenario === 'process-fail'" :title="t('library.processDemoTitle')" :description="t('library.processDemoHint')" type="info" :closable="false" class="process-demo-notice" />
  <el-form label-position="top" class="library-filter" @submit.prevent="applyFilter">
    <div class="library-filter-fields">
      <el-form-item :label="t('library.documentName')">
        <el-input v-model="filter.name" :placeholder="t('library.documentNamePlaceholder')" clearable />
      </el-form-item>
      <el-form-item :label="t('library.processStatus')">
        <el-select v-model="filter.stage" :placeholder="t('library.all')">
          <el-option :label="t('library.all')" value="" />
          <el-option v-for="stage in stages" :key="stage" :label="t(`library.${stageKeys[stage]}`)" :value="stage" />
        </el-select>
      </el-form-item>
    </div>
    <div class="library-filter-actions">
      <el-button type="primary" native-type="submit"><AppIcon name="search" />{{ t('library.query') }}</el-button>
      <el-button @click="resetFilter"><AppIcon name="rotate-ccw" />{{ t('library.reset') }}</el-button>
    </div>
  </el-form>
  <section class="library-table-section">
    <div class="library-table-toolbar">
      <h3>{{ t('library.documentList') }}</h3>
      <el-button type="primary" @click="emit('upload')"><AppIcon name="upload" />{{ t('library.uploadDocument') }}</el-button>
    </div>
    <el-table :data="rows" row-key="id" :empty-text="t('library.noDocuments')">
      <el-table-column :label="t('library.documentName')" min-width="190">
        <template #default="{ row }"><strong class="document-name">{{ row.name }}</strong><small class="document-file">{{ row.fileName }}</small></template>
      </el-table-column>
      <el-table-column :label="t('library.processStatus')" min-width="130">
        <template #default="{ row }">
          <el-tooltip :disabled="stageOf(row) !== 'pendingIntegration'" :content="t('library.pendingIntegrationHint')" placement="top">
            <span class="document-stage" :class="{ complete: stageOf(row) === 'complete' }">{{ t(`library.${stageKeys[stageOf(row)] || 'stagePendingIntegration'}`) }}</span>
          </el-tooltip>
          <template v-if="row.example && processingDemo.documentId === row.id">
            <div v-if="stageOf(row) === 'processing'" class="process-progress"><small>{{ t(`library.${processingDemo.step}`) }}</small><el-progress :percentage="processingDemo.progress" :stroke-width="5" /></div>
            <div v-else-if="stageOf(row) === 'failed'"><p class="process-error">{{ t('library.processFailed') }}</p><el-button size="small" @click="startProcessing(row.id, false)"><AppIcon name="refresh-cw" />{{ t('common.retry') }}</el-button></div>
          </template>
        </template>
      </el-table-column>
      <el-table-column :label="t('library.chunkCount')" width="105">
        <template #default="{ row }"><el-button link type="primary" @click="emit('open-chunks', row.id)">{{ t('library.count', { count: documentChunks(row.id).length }) }}</el-button></template>
      </el-table-column>
      <el-table-column :label="t('library.uploadedAt')" min-width="145">
        <template #default="{ row }"><small>{{ row.uploadedAt }} <span v-if="row.example">({{ t('library.example') }})</span></small></template>
      </el-table-column>
    </el-table>
    <LibraryPagination v-model:current-page="page" :total="filtered.length" :page-size="pageSize" />
  </section>
</template>

<style scoped>
.process-demo-notice { margin-bottom: 20px; }
.process-progress { margin-top: 8px; }
.process-progress :deep(.el-progress__text) { font-size: 11px !important; min-width: 30px; }
.process-error { margin: 8px 0; color: var(--danger); line-height: 1.6; font-size: 12px; }
.document-name { display: block; font-weight: 600; color: var(--text); }
.document-file { display: block; margin-top: 5px; color: var(--muted); }
.document-stage.complete { color: var(--accent); }
.document-stage.complete::before { content: ''; display: inline-block; width: 4px; height: 4px; margin-right: 6px; vertical-align: middle; border-radius: 50%; background: currentColor; }
</style>
