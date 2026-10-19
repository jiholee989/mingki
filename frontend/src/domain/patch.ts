/** 패치 적용 · 문법 · 테스트 · 시스템 테스트 */
export type VerificationStep = 'APPLY' | 'SYNTAX' | 'TEST' | 'SYSTEM_TEST'

/** verify 1회 결과. 시스템 테스트 실패는 locate로, 나머지 실패는 design으로 돌아간다 */
export type VerificationRound =
  | { round: number; passed: true }
  | { round: number; passed: false; failedStep: VerificationStep; message: string }

/** FAILED: 재시도를 다 쓰고도 실패. publish가 막힌다 */
export type PatchStatus = 'VERIFYING' | 'PASSED' | 'FAILED'

/** design_agent가 파일 묶음 하나에 만든 패치 */
export interface CodePatch {
  id: string
  changeSpecIds: string[]
  diff: string // unified diff
  status: PatchStatus
  rounds: VerificationRound[]
}
