import { fileURLToPath, URL } from 'node:url'

import tailwindcss from '@tailwindcss/vite'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue(), tailwindcss()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
      // 시연에서 올리는 규정 원문. Agent가 등록된 원문과 바이트까지 같은지 확인하므로 저장소 파일을 그대로 쓴다
      '@regulations': fileURLToPath(new URL('../data/regulations', import.meta.url)),
    },
  },
  server: {
    proxy: { '/api': 'http://localhost:8080' },
    fs: { allow: ['.', '../data/regulations'] },
  },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.spec.ts'],
  },
})
