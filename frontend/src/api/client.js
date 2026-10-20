const baseUrl = (import.meta.env?.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '')

/** 保存请求状态和稳定错误标识，界面无需匹配服务端中文提示，也不携带密码等原始输入。 */
export class ApiError extends Error {
  // 只记录可分流的状态和标识，避免异常对象意外保存请求中的密码或凭证。
  constructor(status, code = 'REQUEST_FAILED') {
    super(code)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

// 统一处理请求正文、凭证和超时；调用方显式传凭证，避免健康检查误带认证信息。
export async function request(path, { method = 'GET', body, token, signal } = {}) {
  const headers = new Headers({ Accept: 'application/json' })
  if (body !== undefined) headers.set('Content-Type', 'application/json')
  if (token) headers.set('Authorization', `Bearer ${token}`)
  let response
  try {
    const timeout = AbortSignal.timeout(10000)
    response = await fetch(`${baseUrl}${path}`, {
      method, headers, cache: 'no-store', credentials: 'omit',
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
    })
  } catch (error) {
    throw new ApiError(0, error.name === 'AbortError' ? 'REQUEST_ABORTED' : 'NETWORK_ERROR')
  }
  // 退出成功没有正文，直接返回，不能把正常退出误判为解析错误。
  if (response.status === 204) return null
  let data
  try {
    data = await response.json()
  } catch {
    throw new ApiError(response.status, response.ok ? 'INVALID_RESPONSE' : 'REQUEST_FAILED')
  }
  if (!response.ok) {
    const code = typeof data?.detail?.code === 'string' ? data.detail.code : 'REQUEST_FAILED'
    throw new ApiError(response.status, code)
  }
  return data
}
