package com.ruleripple.backend.task;

import com.ruleripple.backend.internal.LoanContract;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** 계약 영향 화면 응답 (v2 10.6). Agent 가 보낸 판단에 계약 정보를 붙인다. DB 없이 테스트할 수 있게 분리. */
final class ContractImpacts {

    private ContractImpacts() {}

    /**
     * Agent 필드(contractId · reqKey · reason · grandfathered …)는 그대로 두고, 계약 정보는 없는 키만 채운다.
     * 계약을 못 찾으면 contractFound=false 로 표시하고 Agent 필드만 남긴다.
     */
    static List<Map<String, Object>> enrich(List<Map<String, Object>> items, Map<String, LoanContract> contracts,
                                            Map<String, String> productNames) {
        List<Map<String, Object>> out = new ArrayList<>();
        for (Map<String, Object> item : items) {
            Map<String, Object> row = new LinkedHashMap<>(item);
            LoanContract c = item.get("contractId") == null ? null : contracts.get(item.get("contractId").toString());
            row.put("contractFound", c != null);
            if (c != null) {
                row.putIfAbsent("productId", c.getProductId());
                row.putIfAbsent("productName", productNames.get(c.getProductId()));
                row.putIfAbsent("customerId", c.getCustomerId());
                row.putIfAbsent("status", c.getStatus());
                row.putIfAbsent("appliedAt", c.getAppliedAt().toString());
                row.putIfAbsent("contractedAt", c.getContractedAt() == null ? null : c.getContractedAt().toString());
                row.putIfAbsent("ageAtApplication", c.ageAtApplication());
                row.putIfAbsent("amount", c.getAmount());
                row.putIfAbsent("termMonths", c.getTermMonths());
                row.putIfAbsent("repaymentType", c.getRepaymentType());
                row.putIfAbsent("maturityDate", c.getMaturityDate() == null ? null : c.getMaturityDate().toString());
                row.putIfAbsent("extensionCount", c.getExtensionCount());
                row.putIfAbsent("dsrAtApproval", c.getDsrAtApproval());
                row.putIfAbsent("seniorApplied", c.getSeniorApplied());
            }
            out.add(row);
        }
        return out;
    }
}
