package com.ruleripple.backend.internal;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.*;

/**
 * business-mcp 읽기 API 의 계산 (docs/BACKEND_API.md 10.5).
 * DB 없이 테스트할 수 있게 행 목록을 받아 계산만 한다.
 */
final class BusinessQueries {

    private BusinessQueries() {}

    record RuleKey(String ruleKey, List<String> units, List<String> productIds,
                   int activeRows, int closedRows, int upcomingRows) {}

    record ImpactQuery(int ageFrom, int ageTo, BigDecimal dsrFrom, BigDecimal dsrTo, LocalDate appliedBefore) {}

    /** ruleKey · productId 가 null 이면 거르지 않는다. asOf 를 주면 그날 유효한 행만 남긴다. */
    static List<ProductRule> rules(List<ProductRule> all, String ruleKey, String productId, LocalDate asOf) {
        return all.stream()
                .filter(r -> ruleKey == null || r.getRuleKey().equals(ruleKey))
                .filter(r -> productId == null || r.getProductId().equals(productId))
                .filter(r -> asOf == null || r.isValidOn(asOf))
                .toList();
    }

    /** 규칙 키별 단위 · 유효한 상품 · 행 수. asOf 기준으로 유효 · 종료 · 시작 전을 나눈다. */
    static List<RuleKey> ruleKeys(List<ProductRule> all, LocalDate asOf) {
        Map<String, List<ProductRule>> byKey = new TreeMap<>();
        for (ProductRule r : all) byKey.computeIfAbsent(r.getRuleKey(), k -> new ArrayList<>()).add(r);

        List<RuleKey> out = new ArrayList<>();
        byKey.forEach((key, rows) -> {
            SortedSet<String> units = new TreeSet<>();
            SortedSet<String> productIds = new TreeSet<>();
            int active = 0, closed = 0, upcoming = 0;
            for (ProductRule r : rows) {
                units.add(r.getUnit());
                if (r.isValidOn(asOf)) {
                    productIds.add(r.getProductId());
                    active++;
                } else if (r.getEffectiveFrom().isAfter(asOf)) {
                    upcoming++;
                } else {
                    closed++;
                }
            }
            out.add(new RuleKey(key, List.copyOf(units), List.copyOf(productIds), active, closed, upcoming));
        });
        return out;
    }

    /**
     * 유효 계약 · 신청 중 조건에 맞는 것. 거절 건과 today 기준 만기 지난 계약은 뺀다.
     * 나이는 신청일 기준 만 나이로 [ageFrom, ageTo], DSR 은 (dsrFrom, dsrTo]. 둘 다 주면 둘 다 만족해야 한다.
     * appliedBefore(시행일)를 주면 그 전 신청분을 경과조치 대상으로 세고, 만기가 시행일 이후인지 표시한다.
     */
    static Map<String, Object> contractImpact(List<LoanContract> all, ImpactQuery q, LocalDate today) {
        boolean byDsr = q.dsrFrom() != null || q.dsrTo() != null;
        Map<String, Long> byProduct = new TreeMap<>();
        List<Map<String, Object>> items = new ArrayList<>();
        long grandfathered = 0;
        List<LoanContract> sorted = all.stream().sorted(Comparator.comparing(LoanContract::getContractId)).toList();
        for (LoanContract c : sorted) {
            if ("REJECTED".equals(c.getStatus())) continue;
            if (c.getMaturityDate() != null && !c.getMaturityDate().isAfter(today)) continue;
            int age = c.ageAtApplication();
            if (age < q.ageFrom() || age > q.ageTo()) continue;
            BigDecimal dsr = c.getDsrAtApproval();
            if (byDsr && (dsr == null
                    || (q.dsrFrom() != null && dsr.compareTo(q.dsrFrom()) <= 0)
                    || (q.dsrTo() != null && dsr.compareTo(q.dsrTo()) > 0))) continue;

            Map<String, Object> item = new LinkedHashMap<>();
            item.put("contractId", c.getContractId());
            item.put("productId", c.getProductId());
            item.put("status", c.getStatus());
            item.put("appliedAt", c.getAppliedAt().toString());
            item.put("ageAtApplication", age);
            item.put("dsrAtApproval", dsr);
            item.put("repaymentType", c.getRepaymentType());
            item.put("maturityDate", c.getMaturityDate() == null ? null : c.getMaturityDate().toString());
            item.put("extensionCount", c.getExtensionCount());
            if (q.appliedBefore() != null) {
                boolean before = c.getAppliedAt().isBefore(q.appliedBefore());
                if (before) grandfathered++;
                item.put("grandfathered", before);
                item.put("maturesAfterEffective",
                        c.getMaturityDate() != null && !c.getMaturityDate().isBefore(q.appliedBefore()));
            }
            byProduct.merge(c.getProductId(), 1L, Long::sum);
            items.add(item);
        }

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("ageFrom", q.ageFrom());
        out.put("ageTo", q.ageTo());
        if (q.dsrFrom() != null) out.put("dsrFrom", q.dsrFrom());
        if (q.dsrTo() != null) out.put("dsrTo", q.dsrTo());
        if (q.appliedBefore() != null) {
            out.put("appliedBefore", q.appliedBefore().toString());
            out.put("grandfathered", grandfathered);
        }
        out.put("total", items.size());
        out.put("byProduct", byProduct);
        out.put("contracts", items);
        return out;
    }
}
