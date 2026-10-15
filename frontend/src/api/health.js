import { request } from './client'

// 本阶段仅连接健康接口，避免把业务演示当成真实服务结果。
export function getHealth() {
  return request('/health')
}
