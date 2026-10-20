import { computed, reactive, watch } from 'vue'
import { readStorage, writeStorage } from '@/utils/storage'
import { useLibrary } from './useLibrary'
import { useAuth } from './useAuth'

const state = reactive({
  user: null, draft: '', messages: [], sessions: [], activeSession: '',
  scenario: 'normal', loginOpen: false, submitAfterLogin: false, errorKey: '', sending: false,
})
let answerTimer
let workspaceRevision = 0
const library = useLibrary()
const identity = useAuth()
const { auth } = identity
const running = computed(() => state.messages.some((message) => message.status === 'thinking'))
const submitting = computed(() => state.sending)

// 真实身份变化时隔离演示工作区，角色刷新不清空同一用户正在编辑的内容。
watch(() => auth.user, (user) => {
  if (user && state.user?.id === user.id) {
    state.user.role = user.role
    state.user.account = user.account
    state.user.display_name = user.display_name
    return
  }
  resetIdentityWorkspace(true)
  if (!user) return
  const profile = readStorage(`fixflow:demo:profile:${user.id}`, {})
  state.user = { ...user, name: typeof profile?.name === 'string' ? profile.name : user.display_name, avatar: '' }
  const stored = readStorage(`fixflow:demo:sessions:${user.id}`, [])
  state.sessions = Array.isArray(stored) ? stored.filter((item) => item && typeof item.id === 'string' && Array.isArray(item.messages)) : []
}, { flush: 'sync' })

// 集中管理同屏问答状态，使主题、语言和抽屉切换不会销毁正在输入的内容。
export function useWorkspace() {
  return { state, auth, running, submitting, login, logout, sendQuestion, stopAnswer, newChat, selectSession, saveProfile, retryAnswer }
}

// 认证通过后再关闭弹窗，游客有效草稿只消费一次；失败由弹窗显示对应错误。
async function login(account, password) {
  if (!await identity.login(account, password)) return false
  state.loginOpen = false
  if (state.submitAfterLogin) {
    state.submitAfterLogin = false
    await sendQuestion()
  }
  return true
}

// 身份变化先保存旧用户的演示内容，再移除旧头像和消息，恢复失败时保留输入草稿。
function resetIdentityWorkspace(keepDraft = false) {
  const draft = state.draft
  stopAnswer()
  if (state.user?.avatar) URL.revokeObjectURL(state.user.avatar)
  state.user = null
  state.sessions = []
  newChat()
  if (keepDraft) state.draft = draft
}

// 只有后端退出完成才清空草稿；失败保留身份供重试，避免误报已经撤销凭证。
async function logout() {
  if (!await identity.logout()) return false
  resetIdentityWorkspace()
  state.submitAfterLogin = false
  state.loginOpen = false
  return true
}

// 在提交时按可见字符校验，支持中文和表情，同时保留超限原文以便直接修改。
async function sendQuestion() {
  if (running.value || state.sending || auth.restoring || auth.pending) return
  state.errorKey = ''
  if (!state.draft.trim()) { state.errorKey = 'chat.emptyQuestion'; return }
  if ([...state.draft].length > 1000) { state.errorKey = 'chat.overLimit'; return }
  if (!state.user) {
    if (auth.noticeKey === 'account.sessionCheckFailed') { state.errorKey = auth.noticeKey; return }
    state.submitAfterLogin = true
    state.loginOpen = true
    return
  }
  const question = state.draft.trim()
  const userId = state.user.id
  const operation = workspaceRevision
  state.sending = true
  try {
    // 即使当前回答仍为演示，也先校验登录，确保禁用和过期身份不能继续操作。
    const verified = await identity.verifySession()
    if (operation !== workspaceRevision) {
      if (!state.user && auth.noticeKey === 'account.sessionExpired' && state.draft.trim() === question) {
        state.submitAfterLogin = true
        state.loginOpen = true
      }
      return
    }
    if (!verified) {
      if (auth.noticeKey === 'account.sessionExpired') {
        state.submitAfterLogin = true
        state.loginOpen = true
      } else state.errorKey = 'account.sessionCheckFailed'
      return
    }
    if (state.user?.id !== userId || state.draft.trim() !== question) return
    state.messages.push({ id: crypto.randomUUID(), role: 'user', text: question })
    state.draft = ''
    beginAnswer(question)
  } finally {
    if (operation === workspaceRevision) state.sending = false
  }
}

// 在生成时保存来源快照，后续下架或删除原文块不会篡改历史演示引用。
function beginAnswer(question, replaceIndex = -1) {
  const candidates = ['no-result', 'search-fail'].includes(state.scenario) ? [] : library.publishedChunks.value.slice(0, 2)
  const sources = candidates.map((chunk) => ({
    ...chunk,
    documentName: library.documentOf(chunk)?.name,
    documentText: library.documentChunks(chunk.doc).map((item) => item.answer).join('\n\n'),
  }))
  const message = {
    id: crypto.randomUUID(), role: 'assistant', question, status: 'thinking',
    scenario: state.scenario, sources, text: '',
    network: !['no-result', 'search-fail'].includes(state.scenario) && (state.scenario !== 'library-only' || sources.length === 0),
  }
  if (replaceIndex < 0) state.messages.push(message)
  else state.messages.splice(replaceIndex, 1, message)
  persistSession()
  answerTimer = setTimeout(() => {
    const current = state.messages.find((item) => item.id === message.id)
    if (!current || current.status !== 'thinking') return
    current.status = message.scenario === 'answer-fail' ? 'failed' : 'complete'
    current.noResult = current.status === 'complete' && (['no-result', 'search-fail'].includes(message.scenario) || (!sources.length && !message.network))
    current.text = sources.map((source) => source.answer).join('\n\n')
    persistSession()
  }, 1400)
}

// 演示历史按服务端稳定用户编号隔离，不继承以前同名演示账号的本地数据。
function persistSession() {
  if (!state.user || !state.messages.length) return
  if (!state.activeSession) state.activeSession = crypto.randomUUID()
  const session = {
    id: state.activeSession,
    title: state.messages.find((message) => message.role === 'user')?.text.slice(0, 30),
    messages: JSON.parse(JSON.stringify(state.messages)),
  }
  const index = state.sessions.findIndex((item) => item.id === session.id)
  if (index === -1) state.sessions.unshift(session)
  else state.sessions[index] = session
  writeStorage(`fixflow:demo:sessions:${state.user.id}`, state.sessions)
}

// 取消计时器并保存停止状态，防止离开会话后迟到的模拟结果写入新会话。
function stopAnswer() {
  clearTimeout(answerTimer)
  const message = state.messages.find((item) => item.status === 'thinking')
  if (message) { message.status = 'stopped'; persistSession() }
}

// 清空当前对话而保留账号会话列表，符合单工作区的新对话入口。
function newChat() {
  workspaceRevision += 1
  state.sending = false
  stopAnswer()
  state.messages = []
  state.activeSession = ''
  state.draft = ''
  state.errorKey = ''
}

// 复制历史快照避免浏览历史时误改列表数据，刷新中断的生成转成可重试状态。
function selectSession(session) {
  if (running.value || state.sending) return
  state.activeSession = session.id
  state.messages = JSON.parse(JSON.stringify(session.messages)).map((message) => ({
    ...message, status: message.status === 'thinking' ? 'stopped' : message.status,
  }))
  state.errorKey = ''
}

// 重试替换失败回答，保留原问题且不重复添加用户消息。
async function retryAnswer(message) {
  if (running.value || state.sending || auth.restoring || auth.pending || !state.user) return
  const index = state.messages.findIndex((item) => item.id === message.id)
  if (index === -1) return
  const operation = workspaceRevision
  state.sending = true
  try {
    if (!await identity.verifySession() || operation !== workspaceRevision) return
    const currentIndex = state.messages.findIndex((item) => item.id === message.id)
    if (currentIndex !== -1) beginAnswer(message.question, currentIndex)
  } finally {
    if (operation === workspaceRevision) state.sending = false
  }
}

// 头像只在当前会话使用，避免大图占满浏览器存储；显示名称可在本机保留。
function saveProfile(name, avatar) {
  if (!state.user) return
  if (state.user.avatar && state.user.avatar !== avatar) URL.revokeObjectURL(state.user.avatar)
  state.user.name = name.trim()
  state.user.avatar = avatar
  writeStorage(`fixflow:demo:profile:${state.user.id}`, { name: state.user.name })
}
