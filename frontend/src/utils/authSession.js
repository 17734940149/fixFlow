const storageKey = 'fixflow:auth-session:v1'
let memorySession = null

// 仅识别当前后端的随机凭证格式和有限到期时间，损坏缓存不参与身份恢复。
function validSession(value) {
  return typeof value?.token === 'string' && /^[A-Za-z0-9_-]{43}$/.test(value.token)
    && Number.isSafeInteger(value.expiresAt) && value.expiresAt > 0
}

// 标签页存储受限时仍允许本页面登录；刷新恢复能力依赖浏览器允许临时存储。
export function readAuthSession() {
  if (memorySession) return memorySession
  try {
    const value = JSON.parse(sessionStorage.getItem(storageKey))
    if (validSession(value)) memorySession = { token: value.token, expiresAt: value.expiresAt }
    else sessionStorage.removeItem(storageKey)
  } catch {
    // 缺少存储权限或缓存无法解析时按未登录处理，不读取长期演示身份。
  }
  return memorySession
}

// 凭证与到期时间独立存储，不保存密码、用户对象或角色，也不复用演示数据的长期存储。
export function saveAuthSession(token, expiresAt) {
  memorySession = { token, expiresAt }
  try {
    sessionStorage.setItem(storageKey, JSON.stringify(memorySession))
  } catch {
    // 当前页面保留内存凭证，避免存储禁用被误当成账号密码错误。
  }
}

// 清除本标签页凭证；服务端撤销仍必须调用退出接口，不能用此函数代替。
export function clearAuthSession() {
  memorySession = null
  try {
    sessionStorage.removeItem(storageKey)
  } catch {
    // 即使清理存储失败，当前页面也不再使用内存身份；刷新时仍须重新核验。
  }
}
