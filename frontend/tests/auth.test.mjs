import assert from 'node:assert/strict'
import { test } from 'node:test'
import { ApiError, request } from '../src/api/client.js'
import { authErrorKey, getCurrentUser, signIn, signOut } from '../src/api/auth.js'
import { clearAuthSession, readAuthSession } from '../src/utils/authSession.js'

const storageKey = 'fixflow:auth-session:v1'
const firstToken = 'a'.repeat(43)
const secondToken = 'b'.repeat(43)
const user = { id: 'user-1', account: 'interview.user', display_name: '面试用户', role: 'user' }
let moduleSequence = 0

// 顶层测试沿用 node:test 默认串行执行，避免各用例临时替换的浏览器全局对象互相覆盖。

// 构造服务端公开数据，测试只使用虚构凭证与用户，不触碰真实账号或数据库。
function loginResult(overrides = {}) {
  return { access_token: firstToken, token_type: 'bearer', expires_in: 3600, user, ...overrides }
}

// 使用真实 Response 检查正文解析，防止用过度简化的模拟对象掩盖 204 等协议边界。
function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

// 统一构造后端 detail 错误协议，确保断言覆盖请求封装与状态机之间的实际衔接。
function errorResponse(status, code) {
  return jsonResponse({ detail: { code, message: '测试错误，不向界面直接输出' } }, status)
}

// 暂缓网络结果，复现恢复、退出及重新登录交错，避免靠等待时间制造不稳定竞态。
function deferred() {
  let resolve
  let reject
  const promise = new Promise((complete, fail) => { resolve = complete; reject = fail })
  return { promise, resolve, reject }
}

// 每个用例使用独立状态机和浏览器环境，清理凭证、定时器及全局模拟，防止测试相互污染。
async function environment(context, { cached = null, storageDisabled = false } = {}) {
  const originals = new Map(['fetch', 'sessionStorage', 'localStorage'].map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]))
  const values = new Map(cached === null ? [] : [[storageKey, cached]])
  const calls = []
  let responder = () => { throw new Error('测试没有安排此请求') }
  const storage = {
    // 显式模拟权限异常，验证浏览器禁用存储时仍有可控的内存会话降级。
    getItem(key) {
      if (storageDisabled) throw new DOMException('禁止存储', 'SecurityError')
      return values.get(key) ?? null
    },
    // 记录最终持久化内容，从实际缓存检查密码、角色和用户资料是否泄漏。
    setItem(key, value) {
      if (storageDisabled) throw new DOMException('禁止存储', 'SecurityError')
      values.set(key, value)
    },
    // 模拟移除操作，使退出和过期的断言同时观察内存与标签页缓存。
    removeItem(key) {
      if (storageDisabled) throw new DOMException('禁止存储', 'SecurityError')
      values.delete(key)
    },
  }
  Object.defineProperty(globalThis, 'sessionStorage', { configurable: true, value: storage })
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    // 任何长期存储访问都立即失败，避免测试悄悄容忍沿用旧演示登录缓存。
    get() { throw new Error('认证不得访问 localStorage') },
  })
  globalThis.fetch = async (url, options) => {
    calls.push({ url, ...options })
    return responder(url, options)
  }
  clearAuthSession()
  if (cached !== null) values.set(storageKey, cached)
  const { useAuth } = await import(`../src/composables/useAuth.js?test=${++moduleSequence}`)
  const authentication = useAuth()
  context.after(async () => {
    responder = () => new Response(null, { status: 204 })
    await authentication.logout()
    clearAuthSession()
    for (const [key, descriptor] of originals) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor)
      else delete globalThis[key]
    }
  })
  return {
    ...authentication, values, calls,
    // 切换下一阶段网络响应，保留同一个真实请求封装供完整流程调用。
    respond(handler) { responder = handler },
  }
}

// 退出成功必须跳过正文读取，否则正常的空响应会被错误转成失败提示。
test('请求封装接受 204 无正文退出', async (context) => {
  const env = await environment(context)
  let reads = 0
  env.respond(() => ({ status: 204, ok: true, json() { reads += 1; throw new Error('204 没有正文') } }))
  assert.equal(await signOut(firstToken), null)
  assert.equal(reads, 0)
  assert.equal(env.calls[0].method, 'POST')
  assert.equal(env.calls[0].headers.get('Authorization'), `Bearer ${firstToken}`)
})

// 精确限制登录请求字段和凭证传播，防止界面角色或密码被误加到其他请求中。
test('接口请求仅发送约定字段并显式携带凭证', async (context) => {
  const env = await environment(context)
  const password = '  Keep-PASSWORD-Exactly  '
  env.respond(() => jsonResponse(loginResult()))
  await signIn('interview.user', password)
  const login = env.calls[0]
  assert.equal(login.url, '/api/v1/auth/login')
  assert.deepEqual(JSON.parse(login.body), { account: 'interview.user', password })
  assert.equal(login.headers.has('Authorization'), false)
  assert.equal(login.credentials, 'omit')
  assert.equal(login.cache, 'no-store')
  assert.equal(login.headers.get('Content-Type'), 'application/json')
  env.respond(() => jsonResponse(user))
  assert.deepEqual(await getCurrentUser(firstToken), user)
  assert.equal(env.calls[1].url, '/api/v1/auth/me')
  assert.equal(env.calls[1].body, undefined)
  assert.equal(env.calls[1].headers.get('Authorization'), `Bearer ${firstToken}`)
})

// 区分认证失败、数据库故障、输入错误和网络断开，避免把所有失败都误判为密码错误。
test('请求错误保留状态与稳定代码，界面使用对应语言包键', async (context) => {
  const env = await environment(context)
  for (const [status, code, key] of [
    [401, 'INVALID_CREDENTIALS', 'account.invalidCredentials'],
    [503, 'DATABASE_UNAVAILABLE', 'account.serverUnavailable'],
    [422, 'REQUEST_FAILED', 'account.invalidInput'],
  ]) {
    env.respond(() => errorResponse(status, code))
    await assert.rejects(request('/auth/login'), (error) => {
      assert.ok(error instanceof ApiError)
      assert.equal(error.status, status)
      assert.equal(error.code, code)
      assert.equal(authErrorKey(error), key)
      assert.equal(error.message.includes('测试错误'), false)
      return true
    })
  }
  env.respond(() => { throw new TypeError('Failed to fetch') })
  await assert.rejects(request('/auth/me'), (error) => error.status === 0 && error.code === 'NETWORK_ERROR' && authErrorKey(error) === 'account.networkError')
  env.respond(() => { throw new DOMException('取消请求', 'AbortError') })
  await assert.rejects(request('/auth/me'), (error) => error.status === 0 && error.code === 'REQUEST_ABORTED')
})

// 服务成功却返回非数据正文也不能建立身份；网关错误页则保留原服务错误状态供界面分类。
test('非数据响应不会伪装成认证成功', async (context) => {
  const env = await environment(context)
  env.respond(() => new Response('<html>unexpected</html>', { status: 200 }))
  await assert.rejects(request('/auth/me'), (error) => error.status === 200 && error.code === 'INVALID_RESPONSE')
  env.respond(() => new Response('<html>unavailable</html>', { status: 503 }))
  await assert.rejects(request('/auth/me'), (error) => error.status === 503 && error.code === 'REQUEST_FAILED')
})

// 只允许最少会话信息进入本标签页缓存，避免密码与客户端角色变成持久化身份依据。
test('登录只在 sessionStorage 保存凭证与到期时间', async (context) => {
  const env = await environment(context)
  const password = 'Never-store-this-password'
  env.respond(() => jsonResponse(loginResult()))
  assert.equal(await env.login(user.account, password), true)
  const cached = JSON.parse(env.values.get(storageKey))
  assert.deepEqual(Object.keys(cached).sort(), ['expiresAt', 'token'])
  assert.equal(cached.token, firstToken)
  assert.ok(cached.expiresAt > Date.now())
  assert.equal(env.values.get(storageKey).includes(password), false)
  assert.equal(env.values.get(storageKey).includes('role'), false)
  assert.equal(env.auth.user.display_name, user.display_name)
})

// 缓存只能提供待核实凭证，必须等服务端 me 返回才能显示当前用户和角色。
test('初始化先查询 me，缓存伪造角色不能恢复管理员身份', async (context) => {
  const pending = deferred()
  const env = await environment(context, { cached: JSON.stringify({ token: firstToken, expiresAt: Date.now() + 60000, role: 'admin', user: { role: 'admin' } }) })
  env.respond(() => pending.promise)
  const restoration = env.restoreSession()
  assert.equal(env.auth.user, null)
  assert.equal(env.auth.restoring, true)
  assert.equal(env.calls.length, 1)
  assert.equal(env.calls[0].url, '/api/v1/auth/me')
  pending.resolve(jsonResponse(user))
  assert.equal(await restoration, true)
  assert.equal(env.auth.user.role, 'user')
  assert.equal(env.auth.initialized, true)
  assert.equal(await env.restoreSession(), true)
  assert.equal(env.calls.length, 1)
})

// 损坏及缺字段缓存必须被忽略，不能因此发出伪凭证请求或让页面启动失败。
test('损坏缓存和非法凭证按未登录处理', async (context) => {
  const env = await environment(context)
  for (const cached of ['{broken', 'null', '{}', JSON.stringify({ token: 'invalid', expiresAt: Date.now() + 60000 }), JSON.stringify({ token: firstToken, expiresAt: 'later' })]) {
    clearAuthSession()
    env.values.set(storageKey, cached)
    assert.equal(readAuthSession(), null)
  }
  assert.equal(await env.restoreSession(), false)
  assert.equal(env.calls.length, 0)
})

// 浏览器禁用临时存储时保留当前页面的内存登录能力，避免误报账号密码无效。
test('存储禁用时可以内存登录并正常退出', async (context) => {
  const env = await environment(context, { storageDisabled: true })
  assert.equal(readAuthSession(), null)
  env.respond(() => jsonResponse(loginResult()))
  assert.equal(await env.login(user.account, 'Test-password'), true)
  assert.equal(readAuthSession().token, firstToken)
  assert.equal(env.values.size, 0)
  env.respond(() => new Response(null, { status: 204 }))
  assert.equal(await env.logout(), true)
  assert.equal(readAuthSession(), null)
  assert.equal(env.auth.user, null)
})

// 数据库不可用和断网都不证明凭证无效；保留凭证并在重试成功后重新建立真实身份。
for (const failure of ['network', 'database']) {
  test(`恢复时 ${failure} 故障保留凭证，重试查询成功恢复身份`, async (context) => {
    const env = await environment(context, { cached: JSON.stringify({ token: firstToken, expiresAt: Date.now() + 60000 }) })
    env.respond(() => {
      if (failure === 'network') throw new TypeError('Failed to fetch')
      return errorResponse(503, 'DATABASE_UNAVAILABLE')
    })
    assert.equal(await env.restoreSession(), false)
    assert.equal(env.auth.user, null)
    assert.equal(env.auth.restoring, false)
    assert.equal(env.auth.noticeKey, 'account.sessionCheckFailed')
    assert.equal(readAuthSession().token, firstToken)
    assert.ok(env.values.has(storageKey))
    env.respond(() => jsonResponse(user))
    assert.equal(await env.verifySession(), true)
    assert.equal(env.auth.user.id, user.id)
    assert.equal(env.auth.noticeKey, '')
  })
}

// 服务端明确拒绝凭证时必须清除本地缓存，防止刷新反复恢复已撤销或已禁用的身份。
test('恢复时 401 清除身份和凭证', async (context) => {
  const env = await environment(context, { cached: JSON.stringify({ token: firstToken, expiresAt: Date.now() + 60000 }) })
  env.respond(() => errorResponse(401, 'UNAUTHENTICATED'))
  assert.equal(await env.restoreSession(), false)
  assert.equal(env.auth.noticeKey, 'account.sessionExpired')
  assert.equal(env.auth.user, null)
  assert.equal(readAuthSession(), null)
  assert.equal(env.values.has(storageKey), false)
})

// 本地已知到期时立即收起身份，不把过期凭证继续发送到后端造成无效请求。
test('已到期缓存直接清理且不请求 me', async (context) => {
  const env = await environment(context, { cached: JSON.stringify({ token: firstToken, expiresAt: Date.now() - 1 }) })
  assert.equal(await env.restoreSession(), false)
  assert.equal(env.calls.length, 0)
  assert.equal(env.auth.noticeKey, 'account.sessionExpired')
  assert.equal(readAuthSession(), null)
})

// 同时触发挂载恢复和窗口焦点检查时复用查询，避免重复请求和身份显示来回跳动。
test('并发恢复共享一次 me 请求', async (context) => {
  const env = await environment(context, { cached: JSON.stringify({ token: firstToken, expiresAt: Date.now() + 60000 }) })
  const pending = deferred()
  env.respond(() => pending.promise)
  const first = env.restoreSession()
  const second = env.verifySession()
  assert.equal(env.calls.length, 1)
  pending.resolve(jsonResponse(user))
  assert.deepEqual(await Promise.all([first, second]), [true, true])
  assert.equal(env.auth.restoring, false)
})

// 防止连续点击登录或退出产生多次签发、重复撤销，以及响应覆盖彼此的界面状态。
test('并发登录及退出各只发送一次请求', async (context) => {
  const env = await environment(context)
  const pendingLogin = deferred()
  env.respond(() => pendingLogin.promise)
  const login = env.login(user.account, 'Test-password')
  assert.equal(await env.login(user.account, 'Test-password'), false)
  assert.equal(env.calls.length, 1)
  pendingLogin.resolve(jsonResponse(loginResult()))
  assert.equal(await login, true)
  const pendingLogout = deferred()
  env.respond(() => pendingLogout.promise)
  const logout = env.logout()
  assert.equal(await env.logout(), false)
  assert.equal(env.calls.length, 2)
  pendingLogout.resolve(new Response(null, { status: 204 }))
  assert.equal(await logout, true)
})

// 错误密码不允许创建会话，且必须解除按钮等待状态，让用户能修改后再次提交。
test('登录失败不保存凭证并解除等待状态', async (context) => {
  const env = await environment(context)
  env.respond(() => errorResponse(401, 'INVALID_CREDENTIALS'))
  await assert.rejects(env.login(user.account, 'Wrong-password'), (error) => error.status === 401)
  assert.equal(env.auth.pending, false)
  assert.equal(env.auth.user, null)
  assert.equal(readAuthSession(), null)
})

// 错误响应字段不能被接受为可用身份，防止后端协议变化时缓存未知权限或伪凭证。
test('非法登录响应不写入会话', async (context) => {
  const env = await environment(context)
  for (const result of [loginResult({ token_type: 'other' }), loginResult({ access_token: 'bad-token' }), loginResult({ expires_in: 0 }), loginResult({ user: { ...user, role: 'owner' } })]) {
    env.respond(() => jsonResponse(result))
    await assert.rejects(env.login(user.account, 'Test-password'), (error) => error.code === 'INVALID_RESPONSE')
    assert.equal(readAuthSession(), null)
    assert.equal(env.auth.pending, false)
  }
})

// 退出故障不能谎报服务端撤销成功，必须保留原身份并允许用户再次尝试撤销。
for (const failure of ['network', 'database']) {
  test(`退出时 ${failure} 故障保留会话，重试成功才清理`, async (context) => {
    const env = await environment(context)
    env.respond(() => jsonResponse(loginResult()))
    await env.login(user.account, 'Test-password')
    env.respond(() => {
      if (failure === 'network') throw new TypeError('Failed to fetch')
      return errorResponse(503, 'DATABASE_UNAVAILABLE')
    })
    assert.equal(await env.logout(), false)
    assert.equal(env.auth.user.id, user.id)
    assert.equal(readAuthSession().token, firstToken)
    assert.equal(env.auth.noticeKey, 'account.logoutFailed')
    assert.equal(env.auth.pending, false)
    env.respond(() => new Response(null, { status: 204 }))
    assert.equal(await env.logout(), true)
    assert.equal(env.auth.user, null)
    assert.equal(readAuthSession(), null)
    assert.equal(env.values.has(storageKey), false)
  })
}

// 凭证已经失效时无需继续撤销，客户端可以完成退出，避免用户被困在无效登录状态。
test('退出返回 401 也清理本地身份', async (context) => {
  const env = await environment(context)
  env.respond(() => jsonResponse(loginResult()))
  await env.login(user.account, 'Test-password')
  env.respond(() => errorResponse(401, 'UNAUTHENTICATED'))
  assert.equal(await env.logout(), true)
  assert.equal(env.auth.user, null)
  assert.equal(readAuthSession(), null)
  assert.equal(env.auth.noticeKey, '')
})

// 旧身份查询即使在退出并重新登录后才返回，也不能恢复旧用户或清除新凭证。
for (const oldResult of ['success', 'unauthenticated']) {
  test(`退出后新登录不受旧 me ${oldResult} 响应覆盖`, async (context) => {
    const env = await environment(context, { cached: JSON.stringify({ token: firstToken, expiresAt: Date.now() + 60000 }) })
    const stale = deferred()
    env.respond(() => stale.promise)
    const oldVerification = env.restoreSession()
    env.respond(() => new Response(null, { status: 204 }))
    assert.equal(await env.logout(), true)
    const newUser = { ...user, id: 'user-2', account: 'second.user', display_name: '第二位用户' }
    env.respond(() => jsonResponse(loginResult({ access_token: secondToken, user: newUser })))
    assert.equal(await env.login(newUser.account, 'Another-password'), true)
    stale.resolve(oldResult === 'success' ? jsonResponse(user) : errorResponse(401, 'UNAUTHENTICATED'))
    assert.equal(await oldVerification, false)
    assert.equal(env.auth.user.id, newUser.id)
    assert.equal(readAuthSession().token, secondToken)
    assert.equal(env.auth.noticeKey, '')
    assert.equal(env.auth.restoring, false)
  })
}

// 到期会让旧查询失去资格，新账号必须能立即发起自己的检查，不能被旧 Promise 长期阻塞。
test('到期后新登录的 me 检查不会复用尚未结束的旧查询', async (context) => {
  const env = await environment(context)
  context.mock.timers.enable({ apis: ['Date', 'setTimeout'], now: 2000000000000 })
  env.respond(() => jsonResponse(loginResult({ expires_in: 1 })))
  assert.equal(await env.login(user.account, 'Test-password'), true)
  const stale = deferred()
  env.respond(() => stale.promise)
  const oldVerification = env.verifySession()
  context.mock.timers.tick(1000)
  assert.equal(env.auth.user, null)
  assert.equal(env.auth.restoring, false)
  const newUser = { ...user, id: 'user-2', account: 'second.user' }
  env.respond(() => jsonResponse(loginResult({ access_token: secondToken, user: newUser })))
  assert.equal(await env.login(newUser.account, 'Another-password'), true)
  const fresh = deferred()
  env.respond(() => fresh.promise)
  const newVerification = env.verifySession()
  assert.equal(env.calls.length, 4)
  assert.equal(env.calls.at(-1).headers.get('Authorization'), `Bearer ${secondToken}`)
  fresh.resolve(jsonResponse(newUser))
  assert.equal(await newVerification, true)
  stale.resolve(errorResponse(401, 'UNAUTHENTICATED'))
  assert.equal(await oldVerification, false)
  assert.equal(env.auth.user.id, newUser.id)
  assert.equal(readAuthSession().token, secondToken)
})

// 登录有效期到达时主动清理当前页面，使用虚拟时钟避免依赖真实等待或留下定时器。
test('登录到期定时器清理身份和标签页缓存', async (context) => {
  const env = await environment(context)
  context.mock.timers.enable({ apis: ['Date', 'setTimeout'], now: 2000000000000 })
  env.respond(() => jsonResponse(loginResult({ expires_in: 1 })))
  assert.equal(await env.login(user.account, 'Test-password'), true)
  context.mock.timers.tick(999)
  assert.equal(env.auth.user.id, user.id)
  context.mock.timers.tick(1)
  assert.equal(env.auth.user, null)
  assert.equal(readAuthSession(), null)
  assert.equal(env.values.has(storageKey), false)
  assert.equal(env.auth.noticeKey, 'account.sessionExpired')
})
