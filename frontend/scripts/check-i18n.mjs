import assert from 'node:assert/strict'
import { readdir } from 'node:fs/promises'

// 展开嵌套路径检查两个语言环境，确保界面不会因缺失键回退成代码路径。
function flatten(value, prefix = '') {
  return Object.fromEntries(Object.entries(value).flatMap(([key, item]) => {
    const fullKey = prefix ? `${prefix}.${key}` : key
    return typeof item === 'object' ? Object.entries(flatten(item, fullKey)) : [[fullKey, item]]
  }))
}

for (const file of (await readdir(new URL('../src/lang/zh/', import.meta.url))).filter((file) => file !== 'index.js')) {
  const zh = flatten((await import(new URL(`../src/lang/zh/${file}`, import.meta.url))).default)
  const en = flatten((await import(new URL(`../src/lang/en/${file}`, import.meta.url))).default)
  assert.deepEqual(Object.keys(en).sort(), Object.keys(zh).sort(), `${file} 中英文键不一致`)
  for (const key of Object.keys(zh)) assert.equal(en[key], `EN${zh[key]}`, `${key} 英文未按 EN 前缀维护`)
}
console.log('中英文语言包键路径与 EN 前缀检查通过。')
