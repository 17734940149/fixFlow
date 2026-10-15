const baseUrl = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '')

// 限制等待时间，使后端未启动时能显示可恢复状态。
export async function request(path) {
  const response = await fetch(`${baseUrl}${path}`, { signal: AbortSignal.timeout(5000) })
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  return response.json()
}
