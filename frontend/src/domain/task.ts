/** 작업 상태. 서버가 바꾸고 화면은 읽기만 한다 */
export type TaskStatus =
  | 'EXTRACTING' // 요건 추출 중
  | 'WAITING_REQUIREMENT_APPROVAL' // 요건 확정 대기 (interrupt ①)
  | 'LOCATING' // 영향 위치 탐색 · 테스트 생성 중
  | 'DESIGNING' // 수정안 생성 중
  | 'VERIFYING' // 검증 중
  | 'WAITING_REVIEW' // 검토 · 승인 대기 (interrupt ②)
  | 'PUBLISHING' // PR · 티켓 생성 중
  | 'DONE' // 완료
  | 'NO_CHANGE' // 실질 변경 없음
  | 'HELD' // 요건 전부 보류로 종료
  | 'REJECTED' // 검토에서 거절로 종료
  | 'FAILED' // 시스템 오류

/** 규정 v3 → v4 업로드 1건에 대한 분석 작업 */
export interface AnalysisTask {
  id: string
  title: string // 예: 개인신용대출 운영기준 v3 → v4
  status: TaskStatus
  verificationRound: number | null // VERIFYING일 때 현재 회차 (최대 2회)
  errorMessage: string | null // FAILED일 때 오류 내용
  createdAt: string // ISO 8601
  updatedAt: string // ISO 8601
}
