<script setup lang="ts">
/** AI 작업 중 · 반영 중: 큰 제목 하나와 지금 하는 일 목록 */
import { CheckIcon, CircleIcon } from '@lucide/vue'

import { Spinner } from '@/components/ui/spinner'
import type { Step } from '@/lib/briefing'

defineProps<{ title: string; seconds: number; steps: Step[] }>()
</script>

<template>
  <section class="pt-20">
    <Spinner class="size-8" />
    <h1 class="mt-6 text-3xl font-bold">{{ title }}</h1>
    <p class="mt-2 text-muted-foreground">{{ seconds }}초</p>
    <ul class="mt-10 space-y-4">
      <li
        v-for="step in steps"
        :key="step.label"
        class="flex gap-3"
        :class="{
          'font-medium': step.state === 'active',
          'text-muted-foreground/50': step.state === 'todo',
        }"
      >
        <CheckIcon v-if="step.state === 'done'" class="mt-0.5 size-5 shrink-0" />
        <span
          v-else-if="step.state === 'active'"
          class="mt-0.5 grid size-5 shrink-0 place-items-center"
        >
          <span class="size-2.5 animate-pulse rounded-full bg-foreground" />
        </span>
        <CircleIcon v-else class="mt-0.5 size-5 shrink-0" />
        <div>
          {{ step.label }}
          <p v-if="step.detail" class="mt-1 text-sm font-normal text-muted-foreground">
            {{ step.detail }}
          </p>
        </div>
      </li>
    </ul>
  </section>
</template>
