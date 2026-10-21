/**
 * 시연 흐름 하나: 자동 로그인 → (최근 작업 이어보기) → 시작 → 1초마다 진행 확인 → 확인 → 반영 → 완료. 초기화.
 * 서버 호출은 api/tasks.ts, 화면 계산은 lib/briefing.ts. 여기서는 단계와 폴링만 다룬다.
 */

import { onScopeDispose, ref, shallowRef } from 'vue'

import { ApiError } from '@/api/client'
import * as api from '@/api/tasks'
import type { Proposal, Requirement, TaskDetail, TaskEvent, TaskStatus } from '@/api/types'

export type Phase = 'loading' | 'start' | 'running' | 'review' | 'publishing' | 'done' | 'failed'

const POLL_MS = 1000

const PHASE: Record<TaskStatus, Phase> = {
  EXTRACTING: 'running',
  LOCATING: 'running',
  DESIGNING: 'running',
  VERIFYING: 'running',
  WAITING_REVIEW: 'review',
  PUBLISHING: 'publishing',
  DONE: 'done',
  NO_CHANGE: 'done',
  REJECTED: 'done',
  FAILED: 'failed',
}

export function useDemo() {
  const phase = ref<Phase>('loading')
  const task = shallowRef<TaskDetail | null>(null)
  const events = shallowRef<TaskEvent[]>([])
  const requirements = shallowRef<Requirement[]>([])
  const proposals = shallowRef<Proposal[]>([])
  const canApprove = ref(false)
  const error = ref<string | null>(null)
  const busy = ref(false)
  const now = ref(Date.now())

  // 시작 · 초기화마다 늘린다. 이전 작업을 보던 폴링의 늦은 응답은 버린다
  let run = 0
  let timer: ReturnType<typeof setTimeout> | undefined

  function stop() {
    run++
    clearTimeout(timer)
  }

  function clear() {
    task.value = null
    events.value = []
    requirements.value = []
    proposals.value = []
    canApprove.value = false
  }

  function message(e: unknown) {
    return e instanceof Error ? e.message : String(e)
  }

  /** 토큰이 만료되면(8시간) 한 번 다시 로그인한다 */
  async function call<T>(fn: () => Promise<T>): Promise<T> {
    try {
      return await fn()
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 401)) throw e
      await api.login()
      return fn()
    }
  }

  async function follow(id: string) {
    stop()
    if (task.value?.task.id !== id) clear() // 같은 작업을 이어 보면 받은 이벤트 다음부터
    const current = run
    let loadedFor: TaskStatus | null = null
    const tick = async () => {
      try {
        const after = events.value.at(-1)?.seq ?? 0
        const [detail, fresh] = await Promise.all([
          call(() => api.getTask(id)),
          call(() => api.getEvents(id, after)),
        ])
        if (current !== run) return
        const status = detail.task.status
        // 확인 · 반영 · 완료 화면은 요건과 제안이 필요하다. 상태가 바뀔 때 한 번 불러온다
        if (PHASE[status] !== 'running' && PHASE[status] !== 'failed' && loadedFor !== status) {
          const [reqs, res] = await Promise.all([
            call(() => api.getRequirements(id)),
            call(() => api.getProposals(id)),
          ])
          if (current !== run) return
          requirements.value = reqs
          proposals.value = res.proposals
          canApprove.value = res.canApprove
          loadedFor = status
        }
        task.value = detail
        if (fresh.length) events.value = [...events.value, ...fresh]
        now.value = Date.now()
        phase.value = PHASE[status]
        if (status === 'FAILED') error.value = detail.errorMessage ?? '작업이 실패했어요'
        if (phase.value === 'running' || phase.value === 'publishing')
          timer = setTimeout(tick, POLL_MS)
      } catch (e) {
        if (current !== run) return
        error.value = message(e)
        phase.value = 'failed'
      }
    }
    await tick()
  }

  async function init() {
    stop()
    phase.value = 'loading'
    error.value = null
    try {
      await api.login()
      const latest = await api.latestTask()
      if (latest) await follow(latest.id)
      else phase.value = 'start'
    } catch (e) {
      error.value = message(e)
      phase.value = 'failed'
    }
  }

  /** 화면 동작(시작 · 바꾸기 · 초기화) 실패는 지금 화면을 두고 오류만 보여 준다 */
  async function act(fn: () => Promise<void>) {
    busy.value = true
    error.value = null
    try {
      await fn()
    } catch (e) {
      error.value = message(e)
    } finally {
      busy.value = false
    }
  }

  const start = () =>
    act(async () => {
      const { taskId } = await call(() => api.startTask())
      await follow(taskId)
    })

  /** 체크를 푼 제안만 빼고 반영한다 */
  const approve = (excludedKeys: string[]) =>
    act(async () => {
      const id = task.value?.task.id
      if (!id) return
      await call(() => api.approve(id, excludedKeys))
      await follow(id)
    })

  const reset = () =>
    act(async () => {
      stop()
      await call(() => api.resetDemo())
      clear()
      phase.value = 'start'
    })

  /** 실패 화면의 다시 시도: 보던 작업이 있으면 이어서, 없으면 처음부터 */
  function retry() {
    error.value = null
    const id = task.value?.task.id
    return id ? follow(id) : init()
  }

  onScopeDispose(stop)

  return {
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
  }
}
