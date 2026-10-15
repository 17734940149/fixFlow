<script setup>
import { computed, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useWorkspace } from '@/composables/useWorkspace'

const { t } = useI18n()
const { state, login } = useWorkspace()
const formRef = ref()
const form = reactive({ account: '', password: '' })
const error = ref(false)
const rules = computed(() => ({
  account: [{ required: true, message: t('account.requiredAccount'), trigger: 'blur' }],
  password: [{ required: true, message: t('account.requiredPassword'), trigger: 'blur' }],
}))
const open = computed({
  get: () => state.loginOpen,
  set: (value) => { state.loginOpen = value; if (!value) state.submitAfterLogin = false },
})

// 先执行输入校验，再校验本地演示账号，失败时保留账号和问题草稿。
async function submit() {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  error.value = !login(form.account.trim(), form.password)
  form.password = ''
}

// 关闭时移除密码和错误提示，避免再次打开时残留敏感输入。
function clearPassword() {
  form.password = ''
  error.value = false
  formRef.value?.clearValidate()
}
</script>

<template>
  <el-dialog v-model="open" :title="t('account.loginTitle')" width="440px" class="account-dialog" :close-on-click-modal="false" @closed="clearPassword">
    <p class="dialog-intro">{{ t('account.loginHint') }}</p>
    <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent="submit">
      <el-form-item :label="t('account.account')" prop="account">
        <el-input v-model="form.account" :placeholder="t('account.accountPlaceholder')" autocomplete="username" />
      </el-form-item>
      <el-form-item :label="t('account.password')" prop="password">
        <el-input v-model="form.password" type="password" show-password :placeholder="t('account.passwordPlaceholder')" autocomplete="current-password" />
      </el-form-item>
      <p v-if="error" class="form-error" role="alert">{{ t('account.invalidCredentials') }}</p>
      <p class="demo-account-hint">{{ t('account.demoAccounts') }}</p>
      <div class="dialog-actions"><el-button @click="open = false">{{ t('common.cancel') }}</el-button><el-button type="primary" native-type="submit">{{ t('account.login') }}</el-button></div>
    </el-form>
  </el-dialog>
</template>
