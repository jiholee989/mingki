/** 백엔드 응답 모양 (docs/BACKEND_API.md). 필드 이름은 백엔드 그대로, 화면에서 쓰는 것만 적는다. */

export type TaskStatus =
  | 'EXTRACTING'
  | 'LOCATING'
  | 'DESIGNING'
  | 'VERIFYING'
  | 'WAITING_REVIEW'
  | 'PUBLISHING'
  | 'DONE'
  | 'NO_CHANGE'
  | 'REJECTED'
  | 'FAILED'

export interface TaskSummary {
  id: string
  title: string
  status: TaskStatus
  currentNode: string | null
  verifyRound: number
  createdAt: string
  updatedAt: string
}

export interface TaskDetail {
  task: TaskSummary
  errorMessage: string | null
  counts: { requirements: number; proposals: number }
}

/** AI가 고른 조회 (TOOL_PLAN). 이름은 화면 표시용, 모르면 null */
export interface Lookup {
  tool: 'get_article' | 'search_regulation'
  regulationId: string | null
  articleId: string | null
  query: string | null
  reason: string
  regulationTitle?: string | null
  articleTitle?: string | null
}

/** 진행 이벤트. type마다 payload가 다르다 (docs/BACKEND_API.md 5절) — 화면에서 쓰는 필드만 */
export interface TaskEvent {
  seq: number
  type: string
  createdAt: string
  payload: {
    node?: string
    tool?: string
    ok?: boolean
    summary?: string
    requirementId?: string
    lookups?: Lookup[]
  }
}

export interface Requirement {
  reqKey: string
  summary: string
  effectiveDate: string | null
  detail: {
    article: string
    title?: string | null
    change: 'modified' | 'added' | 'removed'
    old_value: string | null
    new_value: string | null
  }
}

export type Impact = 'change_required' | 'keep' | 'needs_check'

export interface Proposal {
  proposalKey: string
  reqKey: string
  productId: string
  productName: string
  ruleId: string | null
  impact: Impact
  unit: string | null
  currentValue: string | null
  proposedValue: string | null
  effectiveDate: string | null
  reason: string
  verifyStatus: 'PENDING' | 'PASSED' | 'FAILED'
  latest: boolean
  decision: 'APPLY' | 'EXCLUDE' | null
  apply: { status: string; closedRuleId: string | null; newRuleId: string | null } | null
}

export interface ProposalsResponse {
  canApprove: boolean
  proposals: Proposal[]
}
