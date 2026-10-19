import skipFormatting from '@vue/eslint-config-prettier/skip-formatting'
import { defineConfigWithVueTs, vueTsConfigs } from '@vue/eslint-config-typescript'
import pluginVue from 'eslint-plugin-vue'

export default defineConfigWithVueTs(
  {
    name: 'app/files-to-lint',
    files: ['**/*.{ts,mts,tsx,vue}'],
  },
  {
    name: 'app/files-to-ignore',
    ignores: ['**/dist/**', '**/coverage/**', 'public/mockServiceWorker.js'],
  },
  pluginVue.configs['flat/essential'],
  vueTsConfigs.recommended,
  {
    name: 'app/ui-components',
    files: ['src/components/ui/**'],
    rules: {
      // shadcn-vue가 생성한 컴포넌트는 Button.vue처럼 한 단어 이름을 쓴다
      'vue/multi-word-component-names': 'off',
    },
  },
  skipFormatting,
)
