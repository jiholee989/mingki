package com.ruleripple.backend.internal;

import org.junit.jupiter.api.Test;

import java.time.LocalDate;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/** 상품 규칙 반영 판단 (docs/BACKEND_API.md 10.4). 값은 #19 데이터 기준. */
class RuleVersionsTest {

    private static final LocalDate TODAY = LocalDate.of(2026, 10, 20);
    private static final LocalDate EFFECTIVE = LocalDate.of(2026, 12, 1);

    private static RuleVersions.Row row(String id, String value, String from, String to) {
        return new RuleVersions.Row(id, value, LocalDate.parse(from), to == null ? null : LocalDate.parse(to));
    }

    @Test
    void valuesCompareAsNumbers() {
        assertThat(RuleVersions.sameValue("0.4", "0.40")).isTrue();      // R056
        assertThat(RuleVersions.sameValue("40", "40")).isTrue();         // R044 percent
        assertThat(RuleVersions.sameValue("0.38", "0.40")).isFalse();
        assertThat(RuleVersions.sameValue("true", "true")).isTrue();     // bool 은 글자 그대로
    }

    @Test
    void nextRuleIdFollowsMax() {
        assertThat(RuleVersions.nextRuleId(List.of("R001", "R082", "R010"))).isEqualTo("R083");
        assertThat(RuleVersions.nextRuleId(List.of("R099", "custom"))).isEqualTo("R100");
        assertThat(RuleVersions.nextRuleId(List.of())).isEqualTo("R001");
    }

    @Test
    void existingRuleCanBeApplied() {
        var rows = List.of(row("R001", "0.40", "2024-01-01", null));
        assertThat(RuleVersions.problem("R001", "0.40", EFFECTIVE, rows, TODAY)).isNull();
        assertThat(RuleVersions.problem("R056", "0.40", EFFECTIVE, List.of(row("R056", "0.4", "2024-01-01", null)), TODAY)).isNull();
    }

    @Test
    void changedValueIsRejected() {
        var rows = List.of(row("R001", "0.38", "2024-01-01", null));
        assertThat(RuleVersions.problem("R001", "0.40", EFFECTIVE, rows, TODAY)).contains("0.38");
    }

    @Test
    void alreadyAppliedIsRejected() {
        // 한 번 반영한 뒤: R001 은 11-30 에 닫히고 R083 이 12-01 부터
        var after = List.of(row("R001", "0.40", "2024-01-01", "2026-11-30"), row("R083", "0.35", "2026-12-01", null));
        assertThat(RuleVersions.problem("R001", "0.40", EFFECTIVE, after, TODAY)).contains("닫혀");

        // 기존 행은 열려 있는데 시행일 기준 새 행이 따로 들어온 경우
        var other = List.of(row("R001", "0.40", "2024-01-01", null), row("R090", "0.35", "2026-12-01", null));
        assertThat(RuleVersions.problem("R001", "0.40", EFFECTIVE, other, TODAY)).contains("R090");
    }

    @Test
    void futureVersionBlocksAnEarlierEffectiveDate() {
        // 2027-01-01 시행으로 한 번 반영된 뒤(R001 은 12-31 까지, R083 은 1-1 부터), 같은 R001 을 12-01 시행으로 또 반영하려는 경우.
        // 시행일(12-01)에 유효한 다른 행은 없지만, 끝이 없는 새 행을 넣으면 1-1 부터 R083 과 함께 유효해진다.
        var rows = List.of(row("R001", "0.40", "2024-01-01", "2026-12-31"), row("R083", "0.35", "2027-01-01", null));
        assertThat(RuleVersions.problem("R001", "0.40", EFFECTIVE, rows, TODAY)).contains("R083");
        // 새 규칙도 같다
        assertThat(RuleVersions.problem(null, null, EFFECTIVE, List.of(row("R090", "true", "2027-01-01", null)), TODAY)).contains("R090");
    }

    @Test
    void endedOldVersionIsNotTheCurrentRule() {
        // P011: R074 는 2023 년에 끝났다. R074 를 고치려는 제안은 받지 않는다
        var rows = List.of(row("R074", "0.50", "2023-01-01", "2023-12-31"), row("R075", "0.40", "2024-01-01", null));
        assertThat(RuleVersions.problem("R074", "0.50", EFFECTIVE, rows, TODAY)).contains("유효하지 않습니다");
        assertThat(RuleVersions.problem("R075", "0.40", EFFECTIVE, rows, TODAY)).isNull();
    }

    @Test
    void newRuleNeedsNoValidRow() {
        assertThat(RuleVersions.problem(null, null, EFFECTIVE, List.of(), TODAY)).isNull();
        var exists = List.of(row("R083", "true", "2026-12-01", null));
        assertThat(RuleVersions.problem(null, null, EFFECTIVE, exists, TODAY)).contains("R083");
        // 끝난 옛 행만 있으면 새 규칙을 넣을 수 있다 (P010 R070)
        assertThat(RuleVersions.problem(null, null, EFFECTIVE, List.of(row("R070", "0.45", "2022-01-01", "2023-12-31")), TODAY)).isNull();
    }

    @Test
    void newRuleTakesTheFirstArticleOfTheProposalBasis() {
        assertThat(RuleVersions.basisArticlesJson("reg://credit-loan-ops/v4/15-2")).isEqualTo("[\"credit-loan-ops/15-2\"]");
        assertThat(RuleVersions.basisArticlesJson("reg://credit-loan-ops/v4/8, reg://dsr-management/v2/8"))
                .isEqualTo("[\"credit-loan-ops/8\"]");
        assertThat(RuleVersions.basisArticlesJson(null)).isEqualTo("[]");
        assertThat(RuleVersions.basisArticlesJson("근거 없음")).isEqualTo("[]");
    }
}
