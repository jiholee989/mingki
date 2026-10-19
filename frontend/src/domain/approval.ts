import type { User } from './user'

export type RequirementDecision = 'CONFIRMED' | 'HELD'

/** CHANGES_REQUESTED: 코멘트로 수정 요청 */
export type ReviewDecision = 'APPROVED' | 'REJECTED' | 'CHANGES_REQUESTED'

interface ApprovalBase {
  id: string
  decidedBy: User
  decidedAt: string // ISO 8601
  comment: string | null
}

/** ① 요건 확정은 요건마다(decisions: 요건 id → 결정), ② 검토 · 승인은 작업 전체에 대해 결정한다 */
export type Approval =
  | (ApprovalBase & { stage: 'REQUIREMENTS'; decisions: Record<string, RequirementDecision> })
  | (ApprovalBase & { stage: 'REVIEW'; decision: ReviewDecision })
