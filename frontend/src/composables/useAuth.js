import { reactive, readonly } from 'vue'
import { getCurrentUser, signIn, signOut } from '../api/auth.js'
import { ApiError } from '../api/client.js'
import { clearAuthSession, readAuthSession, saveAuthSession } from '../utils/authSession.js'

const state = reactive({ user: null, restoring: false, pending: false, initialized: false, noticeKey: '' })
const auth = readonly(state)
let revision = 0
let verification = null
let expiryTimer

// 接口异常时拒绝恢复身份，防止字段缺失或未知角色进入管理界面。
function validateUser(user) {
  if (typeof user?.id !== 'string' || !user.id || typeof user.account !== 'string'
    || typeof user.display_name !== 'string' || !['user', 'admin'].includes(user.role)) {
    throw new ApiError(200, 'INVALID_RESPONSE')
  }
  return user
}

// 使正在等待的旧请求失去写回资格，并通知工作区清理当前用户界面。
function clearIdentity(noticeKey = '') {
  revision += 1
  verification = null
  clearTimeout(expiryTimer)
  clearAuthSession()
  state.user = null
  state.restoring = false
  state.initialized = true
  state.noticeKey = noticeKey
}

// 本地定时仅用于及时收起界面，凭证是否真正有效仍由后端每次查询判断。
function scheduleExpiry() {
  clearTimeout(expiryTimer)
  const session = readAuthSession()
  if (!session) return
  expiryTimer = setTimeout(() => clearIdentity('account.sessionExpired'), Math.max(0, session.expiresAt - Date.now()))
  expiryTimer.unref?.()
}

// 只接受服务端登录结果；异步操作期间禁止重复登录，并清除旧校验的写回资格。
async function login(account, password) {
  if (state.pending || state.restoring || state.user) return false
  state.pending = true
  const operation = ++revision
  verification = null
  clearTimeout(expiryTimer)
  try {
    const result = await signIn(account, password)
    const user = validateUser(result.user)
    if (result.token_type !== 'bearer' || !/^[A-Za-z0-9_-]{43}$/.test(result.access_token)
      || !Number.isInteger(result.expires_in) || result.expires_in < 1 || result.expires_in > 86400) {
      throw new ApiError(200, 'INVALID_RESPONSE')
    }
    if (operation !== revision) return false
    saveAuthSession(result.access_token, Date.now() + result.expires_in * 1000)
    state.user = user
    state.initialized = true
    state.noticeKey = ''
    scheduleExpiry()
    return true
  } finally {
    state.pending = false
    if (!state.user) scheduleExpiry()
  }
}

// 恢复和重新检查共享一个请求，旧响应必须同时匹配操作代次和凭证才可更新身份。
async function verifySession() {
  if (state.pending) return false
  if (verification) return verification
  const session = readAuthSession()
  if (!session) {
    state.initialized = true
    return false
  }
  if (session.expiresAt <= Date.now()) {
    clearIdentity('account.sessionExpired')
    return false
  }
  state.restoring = true
  const operation = revision
  const task = (async () => {
    try {
      const user = validateUser(await getCurrentUser(session.token))
      if (operation !== revision || readAuthSession()?.token !== session.token) return false
      state.user = user
      state.noticeKey = ''
      scheduleExpiry()
      return true
    } catch (error) {
      if (operation !== revision || readAuthSession()?.token !== session.token) return false
      if (error.status === 401) clearIdentity('account.sessionExpired')
      else {
        // 网络与数据库故障不代表凭证被撤销，保留凭证供重试，暂时收起未核实的身份。
        state.user = null
        state.noticeKey = 'account.sessionCheckFailed'
        scheduleExpiry()
      }
      return false
    } finally {
      if (operation === revision) {
        state.restoring = false
        state.initialized = true
      }
    }
  })()
  verification = task
  try {
    return await task
  } finally {
    if (verification === task) verification = null
  }
}

// 首次挂载恢复一次身份；后续窗口重新获得焦点使用 verifySession 检查最新状态。
function restoreSession() {
  return state.initialized ? Promise.resolve(Boolean(state.user)) : verifySession()
}

// 成功撤销或凭证已经失效才清理身份；网络故障保留状态并允许重试退出。
async function logout() {
  if (state.pending) return false
  const session = readAuthSession()
  if (!session) {
    clearIdentity()
    return true
  }
  state.pending = true
  const operation = ++revision
  verification = null
  state.restoring = false
  clearTimeout(expiryTimer)
  try {
    await signOut(session.token)
    if (operation === revision) clearIdentity()
    return true
  } catch (error) {
    if (operation !== revision) return false
    if (error.status === 401) {
      clearIdentity()
      return true
    }
    state.noticeKey = 'account.logoutFailed'
    scheduleExpiry()
    return false
  } finally {
    state.pending = false
  }
}

// 认证状态集中供工作区和界面复用；只读暴露避免组件误把本地角色当成可编辑配置。
export function useAuth() {
  return { auth, login, logout, restoreSession, verifySession }
}
