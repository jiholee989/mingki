export interface RegulationClause {
  version: string // 예: v4
  article: string // 예: 제15조
  text: string // 원문
}

/** requirement_agent가 신 · 구 조항을 비교해 뽑은 요건 */
export interface Requirement {
  id: string
  summary: string // 변경 내용, 예: 고령자 기준 만 65세 → 만 60세
  target: string // 적용 대상
  effectiveDate: string // 시행일, YYYY-MM-DD
  transitionalMeasure: string | null // 경과조치, 없으면 null
  previousClause: RegulationClause | null // 구 조항, 신설이면 null
  currentClause: RegulationClause | null // 신 조항, 삭제면 null
}
