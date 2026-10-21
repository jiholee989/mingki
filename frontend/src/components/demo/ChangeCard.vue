<script setup lang="ts">
/** 바뀐 조항 하나: 머리(무엇이 어떻게) + 바꿀 상품마다 체크. 상품을 누르면 바뀌는 값과 AI 이유 */
import { ChevronRightIcon } from '@lucide/vue'
import { computed } from 'vue'

import { Card, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import type { ChangeGroup } from '@/lib/briefing'

const props = defineProps<{ group: ChangeGroup; selected: Set<string> }>()
const emit = defineEmits<{ toggle: [keys: string[], on: boolean] }>()

const keys = computed(() => props.group.rows.map((r) => r.key))
const allOn = computed(() => keys.value.every((k) => props.selected.has(k)))
</script>

<template>
  <Card class="gap-0 py-0">
    <CardHeader class="border-b py-5">
      <CardTitle>{{ group.title }}</CardTitle>
      <p class="text-lg">
        <span v-if="group.added" class="font-semibold">새로 생겼어요</span>
        <template v-else-if="group.before && group.after">
          <span class="text-muted-foreground line-through">{{ group.before }}</span>
          →
          <span class="font-semibold">{{ group.after }}</span>
        </template>
      </p>
    </CardHeader>

    <!-- 새로 생긴 의무: 상품마다 같은 새 규칙이라 한 줄로 묶는다 -->
    <Collapsible v-if="group.added">
      <div class="flex items-center gap-3 px-6 py-3.5">
        <Checkbox
          :model-value="allOn"
          :aria-label="`${group.title} 새 규칙 추가`"
          @update:model-value="(on) => emit('toggle', keys, on === true)"
        />
        <CollapsibleTrigger class="group flex flex-1 items-center text-left">
          상품 {{ group.rows.length }}개에 규칙 추가
          <ChevronRightIcon
            class="ml-auto size-4 text-muted-foreground transition-transform group-data-[state=open]:rotate-90"
          />
        </CollapsibleTrigger>
      </div>
      <CollapsibleContent class="px-6 pb-4 pl-13 text-sm leading-relaxed text-muted-foreground">
        {{ group.rows.map((r) => r.productName).join(' · ') }}
      </CollapsibleContent>
    </Collapsible>

    <div v-else class="divide-y">
      <Collapsible v-for="row in group.rows" :key="row.key">
        <div class="flex items-center gap-3 px-6 py-3.5">
          <Checkbox
            :model-value="selected.has(row.key)"
            :aria-label="`${row.productName} 바꾸기`"
            @update:model-value="(on) => emit('toggle', [row.key], on === true)"
          />
          <CollapsibleTrigger class="group flex flex-1 items-center text-left">
            {{ row.productName }}
            <ChevronRightIcon
              class="ml-auto size-4 text-muted-foreground transition-transform group-data-[state=open]:rotate-90"
            />
          </CollapsibleTrigger>
        </div>
        <CollapsibleContent class="px-6 pb-4 pl-13 text-sm">
          <p>{{ row.change }}</p>
          <p class="mt-1 text-muted-foreground">{{ row.reason }}</p>
        </CollapsibleContent>
      </Collapsible>
    </div>
  </Card>
</template>
