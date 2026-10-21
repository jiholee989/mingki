<script setup lang="ts" generic="T extends { key: string }">
/** 불렛 목록. 처음에는 몇 개만 보이고 "외 n개 보기"를 누르면 전부 */
import { computed, ref } from 'vue'

import { Button } from '@/components/ui/button'

const props = withDefaults(defineProps<{ items: T[]; limit?: number; unit?: string }>(), {
  limit: 3,
  unit: '개',
})

const expanded = ref(false)
const shown = computed(() => (expanded.value ? props.items : props.items.slice(0, props.limit)))
const hidden = computed(() => props.items.length - shown.value.length)
</script>

<template>
  <ul class="list-disc space-y-1.5 pl-5">
    <li v-for="item in shown" :key="item.key">
      <slot :item="item" />
    </li>
  </ul>
  <Button
    v-if="hidden > 0"
    variant="link"
    class="h-auto p-0 text-muted-foreground hover:text-foreground"
    @click="expanded = true"
  >
    외 {{ hidden }}{{ unit }} 보기
  </Button>
</template>
