<script setup>
import icons from '@/assets/icons.json'

defineProps({ name: { type: String, required: true } })
</script>

<template>
  <!-- 图标只来自原设计稿内提取的固定资源，不接收用户或接口返回的标记。 -->
  <span class="app-icon" aria-hidden="true" v-html="icons[name] || icons['circle-help']" />
</template>
