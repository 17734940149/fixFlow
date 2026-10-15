<script setup>
import { useI18n } from 'vue-i18n'

defineProps({ currentPage: { type: Number, required: true }, total: { type: Number, required: true }, pageSize: { type: Number, default: 10 } })
const emit = defineEmits(['update:currentPage'])
const { t } = useI18n()
</script>

<template>
  <div class="library-pagination">
    <span>{{ t('library.paginationTotal', { count: total, size: pageSize }) }}</span>
    <el-pagination :current-page="currentPage" :page-size="pageSize" :total="total" layout="prev, pager, next" :hide-on-single-page="false" @current-change="emit('update:currentPage', $event)" />
  </div>
</template>

<style scoped>
.library-pagination { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 18px; color: var(--muted); font-size: 12px; }
@media (max-width: 560px) { .library-pagination { flex-wrap: wrap; } }
</style>
