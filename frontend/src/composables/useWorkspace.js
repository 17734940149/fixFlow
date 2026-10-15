import { computed, reactive } from 'vue'
import { readStorage, writeStorage } from '@/utils/storage'
import { useLibrary } from './useLibrary'

const state = reactive({
  user: null, draft: '', messages: [], sessions: [], activeSession: '',
  scenario: 'normal', loginOpen: false, submitAfterLogin: false, errorKey: '',
})
let answerTimer
const library = useLibrary()
const running = computed(() => state.messages.some((message) => message.status === 'thinking'))

// 集中管理同屏问答状态，使主题、语言和抽屉切换不会销毁正在输入的内容。
export function useWorkspace() {
  return { state, running, login, logout, sendQuestion, stopAnswer, newChat, selectSession, saveProfile, retryAnswer }
}

// 演示账号只用于检查角色界面，真实身份校验必须在后续由服务端完成。
function login(account, password) {
  if (!['user', 'admin'].includes(account) || password !== 'demo123') return false
  const profile = readStorage(`fixflow:profile:${account}`, {})
  state.user = { account, role: account === 'admin' ? 'admin' : 'user', name: profile?.name || account, avatar: '' }
  const stored = readStorage(`fixflow:sessions:${account}`, [])
  state.sessions = Array.isArray(stored) ? stored : []
  state.loginOpen = false
  if (state.submitAfterLogin) {
    state.submitAfterLogin = false
    sendQuestion()
  }
  return true
}

// 切换账号前清空当前工作区，避免把上一个演示账号的消息展示给另一个账号。
function logout() {
  stopAnswer()
  if (state.user?.avatar) URL.revokeObjectURL(state.user.avatar)
  state.user = null
  state.sessions = []
  newChat()
}

// 在提交时按可见字符校验，支持中文和表情，同时保留超限原文以便直接修改。
function sendQuestion() {
  if (running.value) return
  state.errorKey = ''
  if (!state.draft.trim()) { state.errorKey = 'chat.emptyQuestion'; return }
  if ([...state.draft].length > 1000) { state.errorKey = 'chat.overLimit'; return }
  if (!state.user) {
    state.submitAfterLogin = true
    state.loginOpen = true
    return
  }
  const question = state.draft.trim()
  state.messages.push({ id: crypto.randomUUID(), role: 'user', text: question })
  state.draft = ''
  beginAnswer(question)
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

// 每次只更新当前会话，并按账号存储；示例消息可以刷新后重新选择查看。
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
  writeStorage(`fixflow:sessions:${state.user.account}`, state.sessions)
}

// 取消计时器并保存停止状态，防止离开会话后迟到的模拟结果写入新会话。
function stopAnswer() {
  clearTimeout(answerTimer)
  const message = state.messages.find((item) => item.status === 'thinking')
  if (message) { message.status = 'stopped'; persistSession() }
}

// 清空当前对话而保留账号会话列表，符合单工作区的新对话入口。
function newChat() {
  stopAnswer()
  state.messages = []
  state.activeSession = ''
  state.draft = ''
  state.errorKey = ''
}

// 复制历史快照避免浏览历史时误改列表数据，刷新中断的生成转成可重试状态。
function selectSession(session) {
  if (running.value) return
  state.activeSession = session.id
  state.messages = JSON.parse(JSON.stringify(session.messages)).map((message) => ({
    ...message, status: message.status === 'thinking' ? 'stopped' : message.status,
  }))
  state.errorKey = ''
}

// 重试替换失败回答，保留原问题且不重复添加用户消息。
function retryAnswer(message) {
  if (running.value) return
  const index = state.messages.findIndex((item) => item.id === message.id)
  if (index === -1) return
  beginAnswer(message.question, index)
}

// 头像只在当前会话使用，避免大图占满浏览器存储；显示名称可在本机保留。
function saveProfile(name, avatar) {
  if (!state.user) return
  if (state.user.avatar && state.user.avatar !== avatar) URL.revokeObjectURL(state.user.avatar)
  state.user.name = name.trim()
  state.user.avatar = avatar
  writeStorage(`fixflow:profile:${state.user.account}`, { name: state.user.name })
}
