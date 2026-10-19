/** OFFICER: 준법감시 · 상품기획 담당자, DEVELOPER: 개발자 */
export type Role = 'OFFICER' | 'DEVELOPER'

export interface User {
  id: string
  name: string
  role: Role
}
