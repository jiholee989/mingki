export type DeliveryKind = 'DRAFT_PR' | 'WORK_TICKET'

/** publish가 만든 Draft PR · 작업 티켓 */
export interface Delivery {
  id: string
  kind: DeliveryKind
  title: string
  url: string
  createdAt: string // ISO 8601
}
