<script setup lang="ts">
/** 바꾸지 않는 상품 (확인 필요 · 그대로 둠): 한 줄로 접어 두고, 펼치면 상품과 이유 */
import { ChevronRightIcon } from '@lucide/vue'

import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import type { Note } from '@/lib/briefing'
import ExpandableList from './ExpandableList.vue'

defineProps<{ title: string; items: Note[]; warn?: boolean }>()
</script>

<template>
  <Collapsible>
    <CollapsibleTrigger
      class="group flex items-center gap-1 py-2"
      :class="warn ? 'text-amber-700' : 'text-muted-foreground hover:text-foreground'"
    >
      {{ title }}
      <ChevronRightIcon class="size-4 transition-transform group-data-[state=open]:rotate-90" />
    </CollapsibleTrigger>
    <CollapsibleContent class="mb-3">
      <ExpandableList :items="items">
        <template #default="{ item }">
          <p class="line-clamp-2">
            {{ item.productName }}
            <span class="text-muted-foreground">· {{ item.topic }} · {{ item.reason }}</span>
          </p>
        </template>
      </ExpandableList>
    </CollapsibleContent>
  </Collapsible>
</template>
