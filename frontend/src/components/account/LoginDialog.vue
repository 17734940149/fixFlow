<script setup>
import { computed, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useWorkspace } from '@/composables/useWorkspace'
import { authErrorKey } from '@/api/auth'

const { t } = useI18n()
const { state, auth, login } = useWorkspace()
const formRef = ref()
const form = reactive({ account: '', password: '' })
const errorKey = ref('')
const submitting = ref(false)
const rules = computed(() => ({
  account: [{ required: true, message: t('account.requiredAccount'), trigger: 'blur' }],
  password: [{ required: true, message: t('account.requiredPassword'), trigger: 'blur' }],
}))
const open = computed({
  get: () => state.loginOpen,
  set: (value) => {
    if (submitting.value) return
    state.loginOpen = value
    if (!value) state.submitAfterLogin = false
  },
})

// 先锁住重复提交再请求真实认证；失败保留账号和问题，密码在本次尝试结束后立即清除。
async function submit() {
  if (submitting.value || auth.pending || auth.restoring) return
  submitting.value = true
  errorKey.value = ''
  try {
    const valid = await formRef.value.validate().catch(() => false)
    if (!valid) return
    await login(form.account.trim(), form.password)
  } catch (error) {
    errorKey.value = authErrorKey(error)
  } finally {
    form.password = ''
    submitting.value = false
  }
}

// 关闭时移除密码和错误提示，避免再次打开时残留敏感输入。
function clearPassword() {
  form.password = ''
  errorKey.value = ''
  formRef.value?.clearValidate()
}
</script>

<template>
  <el-dialog v-model="open" :title="t('account.loginTitle')" width="440px" class="account-dialog" :close-on-click-modal="false" :close-on-press-escape="!submitting" :show-close="!submitting" @closed="clearPassword">
    <p class="dialog-intro">{{ t('account.loginHint') }}</p>
    <el-form ref="formRef" :model="form" :rules="rules" :disabled="submitting" label-position="top" @submit.prevent="submit">
      <el-form-item :label="t('account.account')" prop="account">
        <el-input v-model="form.account" :placeholder="t('account.accountPlaceholder')" autocomplete="username" />
      </el-form-item>
      <el-form-item :label="t('account.password')" prop="password">
        <el-input v-model="form.password" type="password" show-password :placeholder="t('account.passwordPlaceholder')" autocomplete="current-password" />
      </el-form-item>
      <p v-if="errorKey" class="form-error" role="alert">{{ t(errorKey) }}</p>
      <p class="demo-account-hint">{{ t('account.realLoginHint') }}</p>
      <div class="dialog-actions"><el-button :disabled="submitting" @click="open = false">{{ t('common.cancel') }}</el-button><el-button type="primary" native-type="submit" :loading="submitting" :disabled="auth.restoring || auth.pending">{{ t('account.login') }}</el-button></div>
    </el-form>
  </el-dialog>
</template>
