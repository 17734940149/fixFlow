import { fileURLToPath, URL } from 'node:url'
import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发时把接口请求转发给 Python 服务，让页面使用同一个请求地址完成本地联调。
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  return {
    plugins: [vue()],
    resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
    server: {
      port: 9096,
      strictPort: true,
      proxy: { '/api': { target: env.VITE_BACKEND_TARGET || 'http://127.0.0.1:8100', changeOrigin: true } },
    },
  }
})
