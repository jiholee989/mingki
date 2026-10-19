/** UNIT: 경계값 · 시행일 전후, SYSTEM: 신청 API 전체 흐름 */
export type TestKind = 'UNIT' | 'SYSTEM'

/** test_agent가 요건에서 만든 테스트. 고정되어 design_agent가 고칠 수 없다 */
export interface TestCase {
  id: string
  requirementId: string
  kind: TestKind
  name: string
  description: string
  code: string
}
