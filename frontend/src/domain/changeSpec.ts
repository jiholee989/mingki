/** ① 값 ② 로직 ③ DB ④ 신규 */
export type ChangeType = 'VALUE' | 'LOGIC' | 'DB' | 'NEW'

export type LocationKind = 'CODE' | 'CONFIG' | 'DB_SCHEMA' | 'PRODUCT_RULE'

export interface ChangeLocation {
  kind: LocationKind
  path: string // 파일 경로 또는 상품 규칙 키
  symbol: string | null // 함수 · 상수 이름
  line: number | null // 경과조치 분기처럼 아직 없는 로직이면 null
  snippet: string | null // 현재 코드, 아직 없는 로직이면 null
}

interface ChangeSpecBase {
  id: string
  requirementId: string
  location: ChangeLocation
  reason: string // 판단 이유
}

/** locate_agent가 찾은 위치. 대상이 아닌 곳도 이유와 함께 남긴다 */
export type ChangeSpec =
  | (ChangeSpecBase & { isTarget: true; changeType: ChangeType })
  | (ChangeSpecBase & { isTarget: false })
