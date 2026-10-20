import { request } from './client'

// 健康检查只判断服务存活，不把登录和数据库就绪混为同一个状态。
export function getHealth() {
  return request('/health')
}
