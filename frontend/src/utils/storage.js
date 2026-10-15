// 存储受限时保留当前页面可用性，主题和演示会话不依赖浏览器允许持久化。
export function readStorage(key, fallback) {
  try {
    return JSON.parse(localStorage.getItem(key)) ?? fallback
  } catch {
    return fallback
  }
}

// 只保存演示数据与界面偏好，不把演示密码或后续真实认证凭证写入本地存储。
export function writeStorage(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    // 浏览器禁用存储时，调用方的响应式状态仍在当前页面有效。
  }
}
