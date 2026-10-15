<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/common/AppIcon.vue'
import { useLibrary } from '@/composables/useLibrary'

const props = defineProps({ modelValue: Boolean, scenario: { type: String, default: 'normal' } })
const emit = defineEmits(['update:modelValue', 'added'])
const { t } = useI18n()
const { documents, addLocalDocument } = useLibrary()
const open = computed({ get: () => props.modelValue, set: value => emit('update:modelValue', value) })
const file = ref(null)
const uploadFiles = ref([])
const displayName = ref('')
const nameEdited = ref(false)
const errors = reactive({ file: '', name: '', upload: '' })
const uploading = ref(false)
const progress = ref(0)
const failedAttempt = ref(false)
let uploadTimer

/** 替换文件时保留用户主动填写的显示名称，重名失败后也不丢弃已选择的文件。 */
function chooseFile(uploadFile) {
  if (uploading.value) return
  file.value = uploadFile.raw || null
  uploadFiles.value = [uploadFile]
  errors.file = ''
  errors.name = ''
  errors.upload = ''
  failedAttempt.value = false
  if (!nameEdited.value) displayName.value = file.value?.name || ''
}

/** 文件类型以扩展名验证，避免部分浏览器对文档返回空的媒体类型导致误拦截。 */
function validateFile() {
  if (!file.value) return 'fileRequired'
  if (file.value.size > 100 * 1024 * 1024) return 'fileTooLarge'
  if (!/\.(pdf|docx|txt|md)$/i.test(file.value.name)) return 'fileUnsupported'
  return ''
}

/** 通过所有校验才登记本地文件，重复名称只暂停本次提交，不清空文件或修改其他记录。 */
function submitFile() {
  if (uploading.value) return
  errors.file = validateFile()
  errors.name = ''
  errors.upload = ''
  if (errors.file) return
  const effectiveName = displayName.value.trim() || file.value.name
  if (documents.some(document => document.name.trim() === effectiveName)) { errors.name = 'nameDuplicate'; return }
  const fail = props.scenario === 'upload-fail' && !failedAttempt.value
  uploading.value = true
  progress.value = 0
  clearInterval(uploadTimer)
  uploadTimer = setInterval(() => {
    progress.value = Math.min(100, progress.value + 25)
    if (fail && progress.value >= 75) {
      clearInterval(uploadTimer)
      uploading.value = false
      failedAttempt.value = true
      errors.upload = 'uploadFailed'
      return
    }
    if (progress.value !== 100) return
    clearInterval(uploadTimer)
    uploading.value = false
    const document = addLocalDocument(file.value, displayName.value)
    if (!document) { errors.name = 'nameDuplicate'; return }
    ElMessage.success(t('library.localAdded'))
    emit('added', document.id)
    open.value = false
  }, 200)
}

/** 只有重新打开上传入口才清空草稿；同一弹窗内改名重试保留原文件。 */
function resetUpload() {
  clearInterval(uploadTimer)
  uploading.value = false
  progress.value = 0
  failedAttempt.value = false
  file.value = null
  uploadFiles.value = []
  displayName.value = ''
  nameEdited.value = false
  errors.file = ''
  errors.name = ''
  errors.upload = ''
}

// 父级关闭抽屉或退出账号时中止在途模拟，避免迟到结果登记到已经离开的页面。
watch(() => props.modelValue, value => {
  if (value) resetUpload()
  else { clearInterval(uploadTimer); uploading.value = false }
})
onBeforeUnmount(() => clearInterval(uploadTimer))
</script>

<template>
  <el-dialog v-model="open" :title="t('library.uploadDocument')" width="540px" class="library-dialog" append-to-body :close-on-click-modal="false" :close-on-press-escape="!uploading" :show-close="!uploading">
    <el-alert :title="t('library.uploadDemoTitle')" :description="t('library.uploadDemoHint')" type="info" :closable="false" class="upload-notice" />
    <el-form label-position="top" @submit.prevent="submitFile">
      <el-form-item :label="t('library.fileLabel')" required :error="errors.file ? t(`library.${errors.file}`) : ''">
        <el-upload v-model:file-list="uploadFiles" class="document-upload" drag :auto-upload="false" :show-file-list="false" :disabled="uploading" accept=".pdf,.docx,.txt,.md" :on-change="chooseFile">
          <AppIcon name="cloud-upload" /><strong>{{ file?.name || t('library.selectFile') }}</strong><small>{{ t('library.fileHint') }}</small>
        </el-upload>
      </el-form-item>
      <el-form-item :label="t('library.displayName')" :error="errors.name ? t(`library.${errors.name}`) : ''">
        <el-input v-model="displayName" :disabled="uploading" :placeholder="t('library.displayNamePlaceholder')" @input="nameEdited = true" />
      </el-form-item>
      <el-alert v-if="errors.name" :title="t('library.duplicateTitle')" :description="t('library.duplicateHint')" type="error" :closable="false" />
      <div v-if="uploading" class="upload-progress" role="status"><p>{{ t('library.uploadingProgress', { progress }) }}</p><el-progress :percentage="progress" :stroke-width="6" /></div>
      <el-alert v-if="errors.upload" :title="t('library.uploadFailedTitle')" :description="t(`library.${errors.upload}`)" type="error" :closable="false" />
    </el-form>
    <template #footer><el-button :disabled="uploading" @click="open = false">{{ t('common.cancel') }}</el-button><el-button type="primary" :disabled="uploading" @click="submitFile"><AppIcon name="upload" />{{ t(uploading ? 'library.uploading' : failedAttempt ? 'library.retryUpload' : 'library.submitUpload') }}</el-button></template>
  </el-dialog>
</template>

<style scoped>
.upload-notice { margin-bottom: 22px; }
.upload-progress { margin: 18px 0; color: var(--muted); font-size: 12px; }
.document-upload { width: 100%; }
.document-upload :deep(.el-upload) { display: block; }
.document-upload :deep(.el-upload-dragger) { background: var(--surface-raised); border-color: var(--border); padding: 28px 20px; }
.document-upload .app-icon { display: block; width: 27px; height: 27px; margin: 0 auto 14px; color: var(--accent); }
.document-upload strong { display: block; color: var(--text); line-height: 1.7; overflow-wrap: anywhere; }
.document-upload small { display: block; color: var(--muted); margin-top: 8px; line-height: 1.6; }
</style>
