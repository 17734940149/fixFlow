<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useLibrary } from '@/composables/useLibrary'
import ChunkActions from './ChunkActions.vue'

const props = defineProps({ modelValue: Boolean, chunkId: { type: String, default: '' }, allowActions: { type: Boolean, default: true } })
const emit = defineEmits(['update:modelValue', 'action'])
const { t } = useI18n()
const { chunks, documentOf, metadata, hasConflict } = useLibrary()
const open = computed({ get: () => props.modelValue, set: value => emit('update:modelValue', value) })
const chunk = computed(() => chunks.find(item => item.id === props.chunkId && !item.deleted))
const fields = computed(() => chunk.value ? metadata(chunk.value) : null)
</script>

<template>
  <el-dialog v-model="open" :title="t('library.detailTitle', { id: chunkId })" width="720px" class="library-dialog" append-to-body :close-on-click-modal="false">
    <div v-if="chunk" class="chunk-detail">
      <div class="chunk-detail-heading"><el-tag effect="plain" size="small">{{ t(`library.${chunk.status}`) }}</el-tag><span>{{ documentOf(chunk)?.name }}</span></div>
      <h3>{{ chunk.id }}</h3>
      <dl class="chunk-fields">
        <dt>chunk_id</dt><dd>{{ fields.chunk_id }}</dd>
        <dt>document_id</dt><dd>{{ fields.document_id }}</dd>
        <dt>chunk_index</dt><dd>{{ fields.chunk_index ?? '—' }}</dd>
        <dt>{{ t('library.characterCount') }}</dt><dd>{{ fields.character_count }}</dd>
      </dl>
      <h4>{{ t('library.originalContent') }}</h4>
      <div class="chunk-original">{{ chunk.answer }}</div>
      <h4>{{ t('library.source') }}</h4>
      <div class="chunk-source">{{ chunk.source }}</div>
      <details class="chunk-debug"><summary>{{ t('library.debugFields') }}</summary><pre>{{ JSON.stringify(fields, null, 2) }}</pre></details>
      <el-alert v-if="hasConflict(chunk)" :title="t('library.conflictTitle')" :description="t('library.conflictHint')" type="warning" :closable="false" />
      <div v-if="allowActions" class="chunk-detail-actions"><ChunkActions :chunk="chunk" @action="(action, ids) => emit('action', action, ids)" /></div>
    </div>
    <el-empty v-else :description="t('library.chunkMissing')" />
    <template #footer><el-button @click="open = false">{{ t('common.close') }}</el-button></template>
  </el-dialog>
</template>

<style scoped>
.chunk-detail-heading { display: flex; justify-content: space-between; align-items: center; gap: 12px; color: var(--muted); font-size: 12px; }
.chunk-detail h3 { margin: 22px 0; font-size: 18px; color: var(--text); }
.chunk-fields { display: grid; grid-template-columns: 140px minmax(0, 1fr); gap: 16px; margin: 0 0 26px; font-size: 12px; }
.chunk-fields dt { color: var(--muted); font-weight: 600; }
.chunk-fields dd { margin: 0; overflow-wrap: anywhere; }
.chunk-detail h4 { color: var(--muted); font-size: 12px; font-weight: 400; margin: 22px 0 10px; }
.chunk-original, .chunk-source { white-space: pre-wrap; overflow-wrap: anywhere; padding: 18px; border: 1px solid var(--border); border-radius: 5px; background: var(--surface-raised); color: var(--text); line-height: 1.9; font-size: 13px; }
.chunk-debug { border-top: 1px solid var(--border); padding-top: 16px; margin: 20px 0; font-size: 12px; }
.chunk-debug summary { cursor: pointer; color: var(--text); }
.chunk-debug pre { padding: 15px; margin: 15px 0 0; overflow: auto; background: var(--surface-raised); white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.75; }
.chunk-detail-actions { margin-top: 22px; }
@media (max-width: 520px) { .chunk-fields { grid-template-columns: 105px minmax(0, 1fr); } }
</style>
