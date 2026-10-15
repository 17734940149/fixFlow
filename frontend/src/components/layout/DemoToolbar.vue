<script setup>
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { getHealth } from '@/api/health'
import { useWorkspace } from '@/composables/useWorkspace'
import AppIcon from '@/components/common/AppIcon.vue'

const { t } = useI18n()
const { state } = useWorkspace()
const serviceStatus = ref('serviceChecking')

// 通过真实健康接口展示连接结果，模拟业务仍可在后端未启动时独立演示。
async function checkService() {
  serviceStatus.value = 'serviceChecking'
  try {
    const response = await getHealth()
    serviceStatus.value = response.status === 'ok' ? 'serviceOnline' : 'serviceOffline'
  } catch {
    serviceStatus.value = 'serviceOffline'
  }
}
onMounted(checkService)
</script>

<template>
  <div class="demo-toolbar">
    <el-tooltip :content="t('common.demoHint')">
      <span class="demo-label"><AppIcon name="circle-help" />{{ t('common.demo') }}</span>
    </el-tooltip>
    <div class="demo-controls">
      <el-button text size="small" :title="t('common.checkService')" @click="checkService">
        <span class="service-dot" :class="{ online: serviceStatus === 'serviceOnline' }" />
        {{ t(`common.${serviceStatus}`) }}
      </el-button>
      <label class="scenario-label" for="demo-scenario">{{ t('common.scenario') }}</label>
      <el-select id="demo-scenario" v-model="state.scenario" size="small" :aria-label="t('common.scenario')" style="width: 170px">
        <el-option value="normal" :label="t('common.normal')" />
        <el-option value="library-only" :label="t('common.libraryOnly')" />
        <el-option value="no-result" :label="t('common.noResult')" />
        <el-option value="search-fail" :label="t('common.searchFail')" />
        <el-option value="answer-fail" :label="t('common.answerFail')" />
        <el-option value="process-fail" :label="t('common.processFail')" />
        <el-option value="upload-fail" :label="t('common.uploadFail')" />
        <el-option value="admin-load-fail" :label="t('common.adminLoadFail')" />
        <el-option value="document-preview-fail" :label="t('common.previewFail')" />
        <el-option value="action-fail" :label="t('common.actionFail')" />
      </el-select>
    </div>
  </div>
</template>
