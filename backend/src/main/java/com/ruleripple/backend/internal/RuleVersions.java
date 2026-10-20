package com.ruleripple.backend.internal;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.Collection;
import java.util.List;

/**
 * 상품 규칙 반영 판단 (docs/BACKEND_API.md 10.4). 접수와 워커가 같은 판단을 쓴다.
 * DB 없이 테스트할 수 있게 행 목록만 받는다.
 */
final class RuleVersions {

    private RuleVersions() {}

    /** 같은 상품 · 규칙 키의 행 하나. */
    record Row(String ruleId, String value, LocalDate effectiveFrom, LocalDate effectiveTo) {
        boolean validOn(LocalDate day) {
            return !effectiveFrom.isAfter(day) && (effectiveTo == null || !effectiveTo.isBefore(day));
        }

        boolean startsOnOrAfter(LocalDate day) {
            return !effectiveFrom.isBefore(day);
        }
    }

    /** 값은 숫자로 비교한다 (0.4 = 0.40). 숫자가 아니면(bool 등) 글자 그대로 비교한다. */
    static boolean sameValue(String a, String b) {
        if (a == null || b == null) return a == null && b == null;
        try {
            return new BigDecimal(a.trim()).compareTo(new BigDecimal(b.trim())) == 0;
        } catch (NumberFormatException e) {
            return a.trim().equals(b.trim());
        }
    }

    /**
     * 반영할 수 없으면 이유, 반영할 수 있으면 null.
     * 기존 규칙(ruleId 있음): 그 행이 오늘 유효하고 값이 제안 당시 값과 같으며, 시행일 이후에 유효하거나 시작하는 다른 행이 없어야 한다.
     * 새 규칙(ruleId 없음): 오늘이나 시행일 이후에 유효하거나 시작하는 같은 키의 행이 없어야 한다.
     */
    static String problem(String ruleId, String currentValue, LocalDate effectiveDate, List<Row> rows, LocalDate today) {
        if (ruleId == null) {
            return rows.stream().filter(r -> r.validOn(today) || r.validOn(effectiveDate) || r.startsOnOrAfter(effectiveDate)).findFirst()
                    .map(r -> "같은 상품 · 규칙 키의 유효한 행이 이미 있습니다 (" + r.ruleId() + ")")
                    .orElse(null);
        }
        Row row = rows.stream().filter(r -> r.ruleId().equals(ruleId)).findFirst().orElse(null);
        if (row == null) return ruleId + " 행이 없습니다";
        if (!row.validOn(today)) return ruleId + " 행이 지금 유효하지 않습니다";
        if (!sameValue(row.value(), currentValue)) {
            return ruleId + " 값이 제안 당시 " + currentValue + "이 아니라 " + row.value() + "입니다";
        }
        if (row.effectiveTo() != null && row.effectiveTo().isBefore(effectiveDate)) {
            return ruleId + " 행이 이미 " + row.effectiveTo() + "에 닫혀 있습니다";
        }
        if (!row.effectiveFrom().isBefore(effectiveDate)) {
            return "시행일 " + effectiveDate + "이 " + ruleId + " 시작일보다 빠르거나 같습니다";
        }
        // 시행일에 유효한 행뿐 아니라 시행일 뒤에 시작하는 행(이미 반영된 미래 버전)도 본다.
        // 새 행은 effective_to 가 null 이라, 미래 행을 두고 넣으면 그 날부터 두 행이 동시에 유효해진다.
        return rows.stream().filter(r -> !r.ruleId().equals(ruleId) && (r.validOn(effectiveDate) || r.startsOnOrAfter(effectiveDate))).findFirst()
                .map(r -> "시행일 기준 새 행이 이미 있습니다 (" + r.ruleId() + ")")
                .orElse(null);
    }

    /** 기존 최대 번호 다음 (R082 → R083). R 숫자 형식이 아닌 ID 는 무시한다. */
    static String nextRuleId(Collection<String> ruleIds) {
        int max = ruleIds.stream()
                .filter(id -> id != null && id.matches("R\\d+"))
                .mapToInt(id -> Integer.parseInt(id.substring(1)))
                .max().orElse(0);
        return String.format("R%03d", max + 1);
    }
}
