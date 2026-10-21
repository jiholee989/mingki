import { describe, expect, it } from 'vitest'

import type { Proposal, Requirement, TaskEvent } from '@/api/types'
import {
  appliedCount,
  appliedProposals,
  articleLabel,
  buildAiLog,
  buildBriefing,
  elapsedSeconds,
  formatDate,
  formatValue,
  lookupLines,
  progressSteps,
  withSubject,
} from './briefing'

const requirement = (
  reqKey: string,
  title: string,
  change: 'modified' | 'added' = 'modified',
): Requirement => ({
  reqKey,
  summary: '',
  effectiveDate: '2026-12-01',
  detail: { article: '제8조', title, change, old_value: null, new_value: null },
})

const proposal = (over: Partial<Proposal>): Proposal => ({
  proposalKey: `${over.productId}:${over.reqKey ?? 'REQ-8'}`,
  reqKey: 'REQ-8',
  productId: 'P001',
  productName: '리플 직장인 신용대출',
  ruleId: 'R001',
  impact: 'change_required',
  unit: 'ratio',
  currentValue: '0.40',
  proposedValue: '0.35',
  effectiveDate: '2026-12-01',
  reason: '지금 40%라 낮춰야 함',
  verifyStatus: 'PASSED',
  latest: true,
  decision: null,
  apply: null,
  ...over,
})

const event = (
  seq: number,
  type: string,
  payload: TaskEvent['payload'] = {},
  at = seq,
): TaskEvent => ({
  seq,
  type,
  payload,
  createdAt: new Date(Date.UTC(2026, 9, 21, 0, 0, at)).toISOString(),
})

const REQUIREMENTS = [
  requirement('REQ-8', 'DSR 한도'),
  requirement('REQ-15', '고령자 기준'),
  requirement('REQ-15-2', '고령자 설명 확인', 'added'),
]

const PROPOSALS = [
  proposal({ productId: 'P001', productName: '리플 직장인 신용대출' }),
  proposal({
    productId: 'P005',
    productName: '리플 청년 희망대출',
    unit: 'percent',
    currentValue: '40',
    proposedValue: '35',
  }),
  proposal({
    productId: 'P009',
    productName: '리플 사장님 신용대출',
    impact: 'keep',
    reason: '사업자대출은 DSR 대상 아님',
  }),
  proposal({
    productId: 'P010',
    productName: '리플 중금리 신용대출',
    impact: 'needs_check',
    reason: 'DSR 기준 없음',
  }),
  proposal({
    reqKey: 'REQ-15',
    productId: 'P002',
    productName: '리플 시니어 든든대출',
    unit: 'age',
    currentValue: '65',
    proposedValue: '60',
  }),
  proposal({
    reqKey: 'REQ-15-2',
    productId: 'P002',
    productName: '리플 시니어 든든대출',
    ruleId: null,
    unit: 'bool',
    currentValue: null,
    proposedValue: 'true',
  }),
  proposal({
    reqKey: 'REQ-15-2',
    productId: 'P003',
    productName: '리플 프리미엄 신용대출',
    ruleId: null,
    unit: 'bool',
    currentValue: null,
    proposedValue: 'true',
  }),
  proposal({ productId: 'P001', latest: false, currentValue: '40', proposedValue: '35' }), // 지난 회차는 보지 않는다
]

describe('값 · 이름 표시', () => {
  it('단위에 맞게 보여 준다', () => {
    expect(formatValue('0.40', 'ratio')).toBe('40%')
    expect(formatValue('0.015', 'ratio')).toBe('1.5%')
    expect(formatValue('35', 'percent')).toBe('35%')
    expect(formatValue('60', 'age')).toBe('만 60세')
    expect(formatValue('true', 'bool')).toBe('켜짐')
    expect(formatValue('30000000', 'krw')).toBe('30,000,000원')
    expect(formatValue('36', 'months')).toBe('36개월')
    expect(formatValue(null, 'ratio')).toBe('')
  })

  it('날짜와 조항 번호를 읽기 쉽게', () => {
    expect(formatDate('2026-12-01')).toBe('12월 1일')
    expect(formatDate(null)).toBe('')
    expect(articleLabel('3')).toBe('제3조')
    expect(articleLabel('15-2')).toBe('제15조의2')
    expect(articleLabel('supp-2')).toBe('부칙 제2조')
    expect(withSubject('개인신용대출 운영기준')).toBe('개인신용대출 운영기준이')
    expect(withSubject('운영 기준표')).toBe('운영 기준표가')
  })
})

describe('확인 화면', () => {
  const briefing = buildBriefing(REQUIREMENTS, PROPOSALS)

  it('바뀐 조항마다 카드 하나, 같은 값으로 바뀌면 머리에 그 값', () => {
    expect(
      briefing.groups.map((g) => [g.title, g.before, g.after, g.added, g.rows.length]),
    ).toEqual([
      ['DSR 한도', '40%', '35%', false, 2],
      ['고령자 기준', '만 65세', '만 60세', false, 1],
      ['고령자 설명 확인', null, null, true, 2],
    ])
    expect(briefing.groups[2]!.rows[0]!.change).toBe('새 규칙 추가')
  })

  it('바꿀 상품 수는 상품 기준 (여러 조항으로 바뀌어도 하나)', () => {
    expect(briefing.productCount).toBe(4)
    expect(briefing.changeKeys).toHaveLength(5)
  })

  it('확인 필요 · 그대로 둠은 이유와 함께 따로', () => {
    expect(briefing.needsCheck).toEqual([
      {
        key: 'P010:REQ-8',
        productName: '리플 중금리 신용대출',
        topic: 'DSR 한도',
        reason: 'DSR 기준 없음',
      },
    ])
    expect(briefing.keep.map((n) => n.productName)).toEqual(['리플 사장님 신용대출'])
    expect(briefing.effectiveDate).toBe('2026-12-01')
  })

  it('상품마다 값이 다르면 머리에는 요건의 전후 값', () => {
    const mixed = buildBriefing(
      [
        {
          ...requirement('REQ-8', 'DSR 한도'),
          detail: { ...REQUIREMENTS[0]!.detail, old_value: '40%', new_value: '35%' },
        },
      ],
      [proposal({}), proposal({ productId: 'P004', currentValue: '0.45' })],
    )
    expect([mixed.groups[0]!.before, mixed.groups[0]!.after]).toEqual(['40%', '35%'])
  })

  it('완료 화면은 실제로 반영된 제안만', () => {
    const done = PROPOSALS.map((p, i) =>
      i === 0
        ? {
            ...p,
            decision: 'APPLY' as const,
            apply: { status: 'DONE', closedRuleId: 'R001', newRuleId: 'R083' },
          }
        : p,
    )
    expect(appliedProposals(done).map((p) => p.productId)).toEqual(['P001'])
  })
})

describe('AI 작업 기록', () => {
  const plan = (requirementId: string, articleId: string, articleTitle: string | null = null) =>
    event(10, 'TOOL_PLAN', {
      node: 'product_impact_agent',
      requirementId,
      lookups: [
        {
          tool: 'get_article',
          regulationId: 'dsr-management',
          articleId,
          query: null,
          reason: '적용 대상 확인',
          regulationTitle: '가계대출 DSR 관리기준',
          articleTitle,
        },
      ],
    })

  it('고른 조회는 이름 · 이유로, 같은 조항은 한 번만', () => {
    const lines = lookupLines([
      plan('REQ-8', '3', '적용 대상'),
      plan('REQ-15', '3', '적용 대상'),
      plan('REQ-8', '10'),
    ])
    expect(lines.map((l) => l.label)).toEqual([
      '가계대출 DSR 관리기준 제3조(적용 대상)',
      '가계대출 DSR 관리기준 제10조',
    ])
  })

  it('걸린 시간 · 조항 수 · 상품 수 · 검사 결과', () => {
    const events = [
      event(1, 'STEP', {}, 0),
      plan('REQ-8', '3'),
      event(30, 'APPROVAL_REQUIRED', {}, 86),
    ]
    expect(buildAiLog(events, REQUIREMENTS, PROPOSALS)).toMatchObject({
      seconds: 86,
      requirementCount: 3,
      productCount: 6,
      allPassed: true,
    })
  })
})

describe('작업 중 단계', () => {
  const products = event(5, 'TOOL_END', {
    node: 'product_impact_agent',
    tool: 'get_products',
    ok: true,
    summary: '12건',
  })

  it('상태와 이벤트로 지금 하는 일을 보여 준다', () => {
    expect(progressSteps('EXTRACTING', 1, 0, []).map((s) => s.state)).toEqual([
      'active',
      'todo',
      'todo',
      'todo',
    ])
    expect(progressSteps('LOCATING', 1, 3, []).map((s) => s.state)).toEqual([
      'done',
      'active',
      'todo',
      'todo',
    ])
    const judging = progressSteps('LOCATING', 1, 3, [
      products,
      event(6, 'TOOL_PLAN', { lookups: [] }),
    ])
    expect(judging.map((s) => [s.label, s.state])).toEqual([
      ['바뀐 조항 3곳을 찾았어요', 'done'],
      ['상품 12개를 불러왔어요', 'done'],
      ['상품마다 영향을 판단하고 있어요', 'active'],
      ['수정안 만들고 검사하기', 'todo'],
    ])
    expect(progressSteps('VERIFYING', 2, 3, [products])[3]).toEqual({
      label: '수정안을 다시 만들고 있어요 · 2회차',
      state: 'active',
    })
  })

  it('반영 중에는 큐가 끝낸 제안 수만 센다 (Agent 도구 기록 · 실패한 시도는 빼고)', () => {
    const queue = (ok: boolean) => event(40, 'TOOL_END', { tool: 'APPLY_RULE_VERSION', ok })
    expect(appliedCount([products, queue(true), queue(false), queue(true)])).toBe(2)
  })

  it('걸린 시간은 작업 시작부터, 반영 중에는 확인한 때부터', () => {
    const events = [event(1, 'STEP', {}, 0), event(30, 'RESUMED', {}, 100)]
    const now = Date.parse(event(0, '', {}, 105).createdAt)
    expect(elapsedSeconds(events, now)).toBe(105)
    expect(elapsedSeconds(events, now, 'RESUMED')).toBe(5)
  })
})
