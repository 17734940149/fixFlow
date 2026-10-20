import { request } from './client.js'

// 登录只发送服务端允许的字段，不让页面选择或提交自己的角色。
export function signIn(account, password) {
  return request('/auth/login', { method: 'POST', body: { account, password } })
}

// 每次恢复身份都向服务端核实，避免把本地保存的用户资料当成认证依据。
export function getCurrentUser(token) {
  return request('/auth/me', { token })
}

// 撤销当前凭证，由服务端删除会话后再清理页面的登录状态。
export function signOut(token) {
  return request('/auth/logout', { method: 'POST', token })
}

// 请求错误映射为语言包键，服务端返回的用户资料本身不做翻译。
export function authErrorKey(error) {
  if (error.status === 401) return 'account.invalidCredentials'
  if (error.status === 422) return 'account.invalidInput'
  if (error.status >= 500) return 'account.serverUnavailable'
  if (error.code === 'NETWORK_ERROR') return 'account.networkError'
  return 'account.requestFailed'
}
