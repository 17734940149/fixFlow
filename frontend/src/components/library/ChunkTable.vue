<script setup>
import { computed, nextTick, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/common/AppIcon.vue'
import { chunkStatuses } from '@/data/library'
import { useLibrary } from '@/composables/useLibrary'
import ChunkActions from './ChunkActions.vue'
import LibraryPagination from './LibraryPagination.vue'

const props = defineProps({ documentId: { type: String, default: '' } })
const emit = defineEmits(['detail', 'action', 'back'])
const { t } = useI18n()
const { documents, chunks, documentOf, hasConflict, isSelectable } = useLibrary()
const status = ref('pending')
const filter = reactive({ name: '', source: props.documentId })
const applied = reactive({ name: '', source: props.documentId })
const page = ref(1)
const pageSize = 10
const table = ref()
const selected = ref([])
const scoped = computed(() => Boolean(props.documentId))
const scopedDocument = computed(() => documents.find(document => document.id === props.documentId))
const canSelect = computed(() => !scoped.value && status.value !== 'published')
const filtered = computed(() => chunks.filter(chunk => !chunk.deleted &&
  (scoped.value ? chunk.doc === props.documentId : chunk.status === status.value) &&
  (!applied.name || `${chunk.id} ${chunk.answer}`.toLocaleLowerCase().includes(applied.name.toLocaleLowerCase())) &&
  (!applied.source || chunk.doc === applied.source),
))
const rows = computed(() => filtered.value.slice((page.value - 1) * pageSize, page.value * pageSize))
const bulkAction = computed(() => ({ pending: 'approve', reviewed: 'publish', offline: 'delete' })[status.value])
const bulkKey = computed(() => ({ pending: 'bulkApprove', reviewed: 'bulkPublish', offline: 'bulkDelete' })[status.value])

/** 状态和页码变化后清除选择，防止不可见记录被误当成当前页批量操作。 */
function clearSelection() {
  selected.value = []
  nextTick(() => table.value?.clearSelection())
}

/** 固定查询快照，并从第一页展示，避免筛选后停留在已经不存在的页码。 */
function applyFilter() {
  Object.assign(applied, { name: filter.name.trim(), source: scoped.value ? props.documentId : filter.source })
  page.value = 1
  clearSelection()
}

/** 文档全部块视图保留文档范围，重置不会意外跳到其他来源。 */
function resetFilter() {
  Object.assign(filter, { name: '', source: props.documentId })
  applyFilter()
}

/** 再次排除冲突记录，保证即使通过程序触发选择也不能绕过冲突处理。 */
function selectRows(selection) {
  selected.value = selection.filter(isSelectable).map(chunk => chunk.id)
}

/** 列表摘要只压缩空白，不改写原文；详情仍展示原始段落。 */
function excerpt(chunk) {
  return (chunk.answer || '').trim().replace(/\s+/g, ' ').slice(0, 80)
}

/** 数量按原始状态统计，与筛选条件分离以说明各审核阶段的总体分布。 */
function statusCount(value) {
  return chunks.filter(chunk => !chunk.deleted && chunk.status === value).length
}

watch(status, () => { page.value = 1; clearSelection() })
watch(page, clearSelection)
watch(() => chunks.map(chunk => `${chunk.id}:${chunk.status}:${Boolean(chunk.deleted)}`).join(','), () => {
  page.value = Math.min(page.value, Math.max(1, Math.ceil(filtered.value.length / pageSize)))
  clearSelection()
})
</script>

<template>
  <div v-if="scoped" class="document-breadcrumb">
    <el-button @click="emit('back')">{{ t('library.backDocuments') }}</el-button>
    <span>{{ scopedDocument?.name }} / {{ t('library.allDocumentChunks') }}</span>
  </div>
  <el-tabs v-else v-model="status" class="chunk-status-tabs">
    <el-tab-pane v-for="item in chunkStatuses" :key="item" :name="item" :label="`${t(`library.${item}`)} ${statusCount(item)}`" />
  </el-tabs>
  <el-form label-position="top" class="library-filter" @submit.prevent="applyFilter">
    <div class="library-filter-fields">
      <el-form-item :label="t('library.chunkQuery')"><el-input v-model="filter.name" :placeholder="t('library.chunkPlaceholder')" clearable /></el-form-item>
      <el-form-item :label="t('library.sourceDocument')">
        <el-select v-model="filter.source" :disabled="scoped" :placeholder="t('library.allDocuments')">
          <el-option :label="t('library.allDocuments')" value="" />
          <el-option v-for="document in documents" :key="document.id" :label="document.name" :value="document.id" />
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
      <h3>{{ scoped ? t('library.allDocumentChunks') : t('library.chunkList', { status: t(`library.${status}`) }) }}</h3>
      <div v-if="canSelect" class="bulk-actions">
        <span v-if="selected.length">{{ t('library.selected', { count: selected.length }) }}</span>
        <el-button type="primary" :disabled="!selected.length" @click="emit('action', bulkAction, selected)"><AppIcon :name="status === 'offline' ? 'trash-2' : 'check'" />{{ t(`library.${bulkKey}`, { count: selected.length }) }}</el-button>
      </div>
    </div>
    <el-table ref="table" :data="rows" row-key="id" :empty-text="t('library.noChunks')" @selection-change="selectRows">
      <el-table-column v-if="canSelect" type="selection" width="42" :selectable="isSelectable" />
      <el-table-column :label="t('library.chunkColumn')" min-width="255">
        <template #default="{ row }">
          <button class="chunk-link" type="button" @click="emit('detail', row.id)"><span class="chunk-id">{{ row.id }}</span><span class="chunk-excerpt">{{ excerpt(row) }}</span></button>
          <el-tag v-if="hasConflict(row)" type="danger" size="small" effect="plain" class="conflict-tag">{{ t('library.conflictPending') }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column :label="t('library.sourceDocument')" min-width="145"><template #default="{ row }">{{ documentOf(row)?.name || '—' }}</template></el-table-column>
      <el-table-column v-if="scoped" :label="t('library.status')" width="100"><template #default="{ row }"><el-tag effect="plain" size="small">{{ t(`library.${row.status}`) }}</el-tag></template></el-table-column>
      <el-table-column :label="t('library.operations')" width="115">
        <template #default="{ row }"><el-button v-if="scoped" link type="primary" @click="emit('detail', row.id)">{{ t('library.detail') }}</el-button><ChunkActions v-else :chunk="row" @action="(action, ids) => emit('action', action, ids)" /></template>
      </el-table-column>
    </el-table>
    <LibraryPagination v-model:current-page="page" :total="filtered.length" :page-size="pageSize" />
  </section>
</template>

<style scoped>
.document-breadcrumb { display: flex; align-items: center; gap: 12px; padding-bottom: 22px; color: var(--muted); font-size: 12px; }
.chunk-status-tabs { margin: -8px 0 19px; }
.chunk-link { display: block; width: 100%; border: 0; padding: 0; background: none; text-align: left; color: var(--text); font: inherit; cursor: pointer; }
.chunk-link:hover .chunk-id { text-decoration: underline; }
.chunk-id { display: block; color: var(--accent); font-weight: 600; margin-bottom: 7px; }
.chunk-excerpt { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; font-size: 12px; line-height: 1.75; }
.conflict-tag { margin-top: 8px; }
.bulk-actions { display: flex; align-items: center; gap: 10px; color: var(--muted); font-size: 12px; }
</style>
