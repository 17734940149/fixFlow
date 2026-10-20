<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'
import { useWorkspace } from '@/composables/useWorkspace'
import { themes, usePreferences } from '@/composables/usePreferences'
import AppIcon from '@/components/common/AppIcon.vue'

const props = defineProps({ modelValue: Boolean })
const emit = defineEmits(['update:modelValue'])
const { t } = useI18n()
const { state, saveProfile } = useWorkspace()
const { theme, language, setTheme, setLanguage } = usePreferences()
const name = ref('')
const avatar = ref('')
const errorKey = ref('')
const fileInput = ref()
const open = computed({ get: () => props.modelValue, set: (value) => emit('update:modelValue', value) })
let avatarRequest = 0

watch(() => props.modelValue, (value) => {
  if (value) { name.value = state.user?.name || ''; avatar.value = state.user?.avatar || ''; errorKey.value = '' }
  else releaseDraftAvatar()
})

// 未保存的临时图片及时释放，关闭设置不会替换当前账号的头像。
function releaseDraftAvatar() {
  avatarRequest += 1
  if (avatar.value && avatar.value !== state.user?.avatar) URL.revokeObjectURL(avatar.value)
}
onBeforeUnmount(releaseDraftAvatar)

// 同时校验文件声明和实际可读性，避免扩展名正确但内容损坏的图片进入界面。
async function chooseAvatar(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  errorKey.value = ''
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) { errorKey.value = 'account.invalidAvatar'; return }
  if (file.size > 20 * 1024 * 1024) { errorKey.value = 'account.avatarTooLarge'; return }
  const requestId = ++avatarRequest
  const url = URL.createObjectURL(file)
  const image = new Image()
  image.src = url
  try {
    await image.decode()
    if (requestId !== avatarRequest) { URL.revokeObjectURL(url); return }
    if (avatar.value && avatar.value !== state.user?.avatar) URL.revokeObjectURL(avatar.value)
    avatar.value = url
  } catch {
    URL.revokeObjectURL(url)
    if (requestId === avatarRequest) errorKey.value = 'account.invalidImage'
  }
}

// 主题即时生效；资料字段只有保存后才写入当前账号，二者遵循不同的更新时机。
function save() {
  if (!name.value.trim()) { errorKey.value = 'account.requiredName'; return }
  saveProfile(name.value, avatar.value)
  open.value = false
  ElMessage.success(t('account.profileSaved'))
}

// 提供方向键循环选择，确保主题预览也能只用键盘操作。
function moveTheme(event, index) {
  if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return
  event.preventDefault()
  const direction = ['ArrowLeft', 'ArrowUp'].includes(event.key) ? -1 : 1
  const next = (index + direction + themes.length) % themes.length
  setTheme(themes[next])
  event.currentTarget.parentElement.children[next].focus()
}
</script>

<template>
  <el-dialog v-model="open" :title="t('account.profile')" width="580px" class="settings-dialog" :close-on-click-modal="false">
    <div class="profile-avatar-row">
      <img v-if="avatar" class="profile-avatar" :src="avatar" :alt="t('account.avatar')" />
      <div v-else class="profile-avatar profile-initial">{{ state.user?.name.slice(0, 1) }}</div>
      <div><label class="field-label">{{ t('account.avatar') }}</label><el-button @click="fileInput.click()"><AppIcon name="image" />{{ t('account.chooseAvatar') }}</el-button><p class="muted avatar-hint">{{ t('account.avatarHint') }}</p></div>
      <input ref="fileInput" type="file" accept="image/png,image/jpeg,image/webp" hidden :aria-label="t('account.chooseAvatar')" @change="chooseAvatar" />
    </div>
    <el-form label-position="top" @submit.prevent="save">
      <p class="muted">{{ t('account.localProfileHint') }}</p>
      <el-form-item :label="t('account.displayName')"><el-input v-model="name" :placeholder="t('account.namePlaceholder')" maxlength="50" /></el-form-item>
      <el-form-item :label="t('account.identity')"><div class="identity-field">{{ state.user?.account }} / {{ t(state.user?.role === 'admin' ? 'account.admin' : 'account.user') }}</div></el-form-item>
      <el-form-item :label="t('account.theme')">
        <div class="theme-grid" role="radiogroup" :aria-label="t('account.theme')">
          <button v-for="(key, index) in themes" :key="key" type="button" class="theme-choice" :data-preview="key" role="radio" :aria-checked="theme === key" @click="setTheme(key)" @keydown="moveTheme($event, index)">
            <span class="theme-preview"><span class="preview-sidebar" /><span class="preview-main"><i /><i /><i /></span></span><span class="theme-choice-label">{{ t(`account.${key}`) }}<AppIcon v-if="theme === key" name="check" /></span>
          </button>
        </div>
      </el-form-item>
      <el-form-item :label="t('account.language')">
        <el-radio-group :model-value="language" @update:model-value="setLanguage"><el-radio-button value="zh">{{ t('account.chinese') }}</el-radio-button><el-radio-button value="en">{{ t('account.english') }}</el-radio-button></el-radio-group>
      </el-form-item>
      <p v-if="errorKey" class="form-error" role="alert">{{ t(errorKey) }}</p>
      <div class="dialog-actions"><el-button @click="open = false">{{ t('common.close') }}</el-button><el-button type="primary" native-type="submit">{{ t('common.save') }}</el-button></div>
    </el-form>
  </el-dialog>
</template>
