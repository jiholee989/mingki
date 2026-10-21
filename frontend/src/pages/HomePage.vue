<script setup lang="ts">
/** 시연 화면 한 페이지: 시작 → AI 작업 중 → 확인 → (반영 중) → 완료. 흐름은 useDemo, 화면 계산은 lib/briefing */
import { computed, onMounted } from 'vue'

import DoneView from '@/components/demo/DoneView.vue'
import ReviewView from '@/components/demo/ReviewView.vue'
import RunningView from '@/components/demo/RunningView.vue'
import StartView from '@/components/demo/StartView.vue'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
import { useDemo } from '@/composables/useDemo'
import {
  appliedCount,
  appliedProposals,
  buildAiLog,
  buildBriefing,
  elapsedSeconds,
  progressSteps,
  type Step,
} from '@/lib/briefing'

const {
  phase,
  task,
  events,
  requirements,
  proposals,
  canApprove,
  error,
  busy,
  now,
  init,
  start,
  approve,
  reset,
  retry,
} = useDemo()

onMounted(init)

const briefing = computed(() => buildBriefing(requirements.value, proposals.value))
const aiLog = computed(() => buildAiLog(events.value, requirements.value, proposals.value))
const applied = computed(() => buildBriefing(requirements.value, appliedProposals(proposals.value)))
// 반영 중에는 확인한 때(RESUMED)부터 센다
const seconds = computed(() =>
  elapsedSeconds(events.value, now.value, phase.value === 'publishing' ? 'RESUMED' : undefined),
)

const running = computed((): { title: string; steps: Step[] } => {
  const detail = task.value
  if (!detail) return { title: 'AI가 확인하고 있어요', steps: [] }
  if (phase.value === 'publishing') {
    const total = proposals.value.filter((p) => p.latest && p.decision === 'APPLY').length
    return {
      title: '상품 규칙에 반영하고 있어요',
      steps: [
        {
          label: `${Math.min(appliedCount(events.value), total)} / ${total}건 반영했어요`,
          state: 'active',
        },
      ],
    }
  }
  return {
    title: 'AI가 확인하고 있어요',
    steps: progressSteps(
      detail.task.status,
      detail.task.verifyRound,
      detail.counts.requirements,
      events.value,
    ),
  }
})
</script>

<template>
  <div class="min-h-svh bg-muted">
    <header class="mx-auto flex h-14 max-w-xl items-center px-5">
      <span class="font-semibold">Rule Ripple</span>
      <Button
        variant="ghost"
        size="sm"
        class="ml-auto text-muted-foreground"
        :disabled="busy"
        @click="reset"
      >
        초기화
      </Button>
    </header>

    <main class="mx-auto max-w-xl px-5 pb-36">
      <Alert
        v-if="error && phase !== 'failed' && phase !== 'review'"
        variant="destructive"
        class="mt-4"
      >
        <AlertDescription>{{ error }}</AlertDescription>
      </Alert>

      <div v-if="phase === 'loading'" class="pt-20"><Spinner class="size-8" /></div>
      <StartView v-else-if="phase === 'start'" :busy="busy" @start="start" />
      <RunningView
        v-else-if="phase === 'running' || phase === 'publishing'"
        :title="running.title"
        :seconds="seconds"
        :steps="running.steps"
      />
      <ReviewView
        v-else-if="phase === 'review'"
        :briefing="briefing"
        :log="aiLog"
        :can-approve="canApprove"
        :busy="busy"
        :error="error"
        @approve="approve"
      />
      <DoneView
        v-else-if="phase === 'done' && task"
        :applied="applied"
        :status="task.task.status"
        :busy="busy"
        @restart="reset"
      />
      <section v-else-if="phase === 'failed'" class="space-y-6 pt-20">
        <Alert variant="destructive">
          <AlertTitle>작업을 이어갈 수 없어요</AlertTitle>
          <AlertDescription>{{ error }}</AlertDescription>
        </Alert>
        <div class="grid grid-cols-2 gap-2">
          <Button variant="outline" size="lg" :disabled="busy" @click="retry">다시 시도</Button>
          <Button size="lg" :disabled="busy" @click="reset">초기화</Button>
        </div>
      </section>
    </main>
  </div>
</template>
