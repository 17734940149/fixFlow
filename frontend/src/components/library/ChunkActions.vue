<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useLibrary } from '@/composables/useLibrary'

const props = defineProps({ chunk: { type: Object, required: true } })
const emit = defineEmits(['action'])
const { t } = useI18n()
const { hasConflict } = useLibrary()
const action = computed(() => {
  if (props.chunk.status === 'pending') return hasConflict(props.chunk) ? 'conflict' : 'approve'
  return { reviewed: 'publish', published: 'unpublish', offline: 'delete' }[props.chunk.status]
})
</script>

<template>
  <el-button v-if="action" link :type="action === 'delete' ? 'danger' : 'primary'" @click="emit('action', action, [chunk.id])">{{ t(`library.${action}`) }}</el-button>
</template>
