import { computed, reactive } from 'vue'
import { sampleChunks, sampleDocuments } from '@/data/library'

// 问答与管理页面共享一份状态，避免下架后新查询仍引用已失效内容。
const documents = reactive(sampleDocuments.map(document => ({ ...document })))
const chunks = reactive(sampleChunks.map(chunk => ({ ...chunk })))
const publishedChunks = computed(() => chunks.filter(chunk => !chunk.deleted && chunk.status === 'published'))
let documentSequence = sampleDocuments.length

/** 用稳定文档编号关联来源，避免名称修改或语言切换影响关系。 */
function documentOf(chunk) {
  return documents.find(document => document.id === chunk?.doc)
}

/** 全部块视图忽略审核状态，但排除已删除记录，便于核对文档解析结果。 */
function documentChunks(documentId) {
  return chunks.filter(chunk => chunk.doc === documentId && !chunk.deleted)
}

/** 集中生成调试信息，确保详情和问答来源使用一致的字段定义。 */
function metadata(chunk) {
  return {
    chunk_id: chunk.id,
    document_id: chunk.doc,
    chunk_index: Number(chunk.source?.match(/Chunk\s*(\d+)/)?.[1]) || null,
    status: chunk.status,
    source_location: chunk.source || null,
    character_count: [...(chunk.answer || '')].length,
  }
}

/** 冲突必须先人工处理，不能通过列表的单条或批量审核绕过确认。 */
function hasConflict(chunk) {
  return Boolean(chunk?.conflict && !chunk.conflictResolved)
}

/** 只允许对具有批量操作语义的状态勾选，已发布内容必须单条确认下架。 */
function isSelectable(chunk) {
  return !chunk.deleted && !hasConflict(chunk) && ['pending', 'reviewed', 'offline'].includes(chunk.status)
}

/** 每次操作重新检查当前状态，避免详情与列表切换后使用过期选择修改数据。 */
function transition(ids, from, to) {
  const selected = chunks.filter(chunk => ids.includes(chunk.id) && !chunk.deleted && chunk.status === from && !hasConflict(chunk))
  selected.forEach(chunk => { chunk.status = to })
  return selected.length
}

/** 审核只改变审核阶段，必须经过后续发布才允许检索。 */
function approve(ids) {
  return transition(ids, 'pending', 'reviewed')
}

/** 发布仅接受已审核记录，防止待审核内容直接变为可用知识。 */
function publish(ids) {
  return transition(ids, 'reviewed', 'published')
}

/** 下架立即移出新查询候选，历史展示仍保留原编号。 */
function unpublish(ids) {
  return transition(ids, 'published', 'offline')
}

/** 删除仅针对已下架记录，用软删除维持本次演示中的来源编号关联。 */
function removeChunks(ids) {
  const selected = chunks.filter(chunk => ids.includes(chunk.id) && !chunk.deleted && chunk.status === 'offline' && !hasConflict(chunk))
  selected.forEach(chunk => { chunk.deleted = true })
  return selected.length
}

/** 一次同步完成新旧状态变更，保留新块时仍需发布，避免未经发布直接参与检索。 */
function resolveConflict(id, choice) {
  const fresh = chunks.find(chunk => chunk.id === id && !chunk.deleted)
  const old = chunks.find(chunk => chunk.id === fresh?.conflict && !chunk.deleted)
  if (!fresh || fresh.status !== 'pending' || !hasConflict(fresh) || old?.status !== 'published') return false
  if (!['old', 'new'].includes(choice)) return false
  fresh.conflictResolved = true
  if (choice === 'new') {
    fresh.status = 'reviewed'
    old.status = 'offline'
    old.replacedBy = fresh.id
  } else {
    fresh.status = 'offline'
    fresh.keptOld = true
  }
  return true
}

/** 只登记本地文件，不模拟已完成解析；后续接入服务时由真实解析结果创建正文块。 */
function addLocalDocument(file, displayName) {
  const name = displayName.trim() || file.name
  if (documents.some(document => document.name.trim() === name)) return null
  const document = {
    id: `D${String(++documentSequence).padStart(3, '0')}`,
    name,
    fileName: file.name,
    stage: 'pendingIntegration',
    uploadedAt: new Intl.DateTimeFormat('sv-SE', {
      timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
    }).format(new Date()),
    originalFile: file,
    example: false,
  }
  documents.unshift(document)
  return document
}

/** 返回共享资料库操作，保持界面组件只负责筛选展示和交互反馈。 */
export function useLibrary() {
  return {
    documents, chunks, publishedChunks, documentOf, documentChunks, metadata, hasConflict, isSelectable,
    approve, publish, unpublish,
    removeChunks, resolveConflict, addLocalDocument,
  }
}
