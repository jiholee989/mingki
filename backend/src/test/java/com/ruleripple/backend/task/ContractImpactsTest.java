package com.ruleripple.backend.task;

import com.fasterxml.jackson.annotation.JsonAutoDetect;
import com.fasterxml.jackson.annotation.PropertyAccessor;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.ruleripple.backend.internal.LoanContract;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

import static org.assertj.core.api.Assertions.assertThat;

/** 계약 영향 응답에 loan_contracts 정보가 붙는지. 실제 시드(data/business)로 확인한다. */
class ContractImpactsTest {

    private static final ObjectMapper SEED = new ObjectMapper().findAndRegisterModules()
            .setPropertyNamingStrategy(PropertyNamingStrategies.SNAKE_CASE)
            .setVisibility(PropertyAccessor.FIELD, JsonAutoDetect.Visibility.ANY)
            .disable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES);

    private static Map<String, LoanContract> contracts() throws IOException {
        List<LoanContract> all = SEED.readValue(Path.of("../data/business/loan_contracts.json").toFile(), new TypeReference<>() {});
        return all.stream().collect(Collectors.toMap(LoanContract::getContractId, c -> c));
    }

    @Test
    void attachesContractAndProductInfoWithoutTouchingAgentFields() throws IOException {
        List<Map<String, Object>> items = List.of(Map.of(
                "contractId", "C0006", "reqKey", "REQ-8", "reason", "연장 시 종전 한도", "grandfathered", true));
        List<Map<String, Object>> out = ContractImpacts.enrich(items, contracts(), Map.of("P001", "리플 직장인 신용대출"));

        Map<String, Object> row = out.get(0);
        assertThat(row).containsEntry("reason", "연장 시 종전 한도").containsEntry("grandfathered", true);
        assertThat(row).containsEntry("contractFound", true)
                .containsEntry("productId", "P001").containsEntry("productName", "리플 직장인 신용대출")
                .containsEntry("appliedAt", "2024-02-20").containsEntry("maturityDate", "2027-02-22")
                .containsEntry("repaymentType", "BULLET").containsEntry("extensionCount", 2)
                .containsEntry("ageAtApplication", 44);
        assertThat(row.get("dsrAtApproval").toString()).startsWith("0.38");
    }

    @Test
    void agentValuesWinOverContractValues() throws IOException {
        List<Map<String, Object>> items = List.of(Map.of("contractId", "C0004", "productId", "P999", "reason", "r"));
        Map<String, Object> row = ContractImpacts.enrich(items, contracts(), Map.of()).get(0);
        assertThat(row).containsEntry("productId", "P999").containsEntry("contractFound", true);
        assertThat(row.get("productName")).isNull();   // 이름 목록에 없는 상품
    }

    @Test
    void unknownContractKeepsAgentFieldsOnly() throws IOException {
        List<Map<String, Object>> items = List.of(Map.of("contractId", "C9999", "reason", "r"));
        Map<String, Object> row = ContractImpacts.enrich(items, contracts(), Map.of()).get(0);
        assertThat(row).containsEntry("contractFound", false).doesNotContainKeys("appliedAt", "productId");
    }

    @Test
    void proposalViewCarriesProductName() {
        RuleProposal p = new RuleProposal();
        p.setProposalKey("P001:DSR_LIMIT");
        p.setProductId("P001");
        p.setImpact("change_required");
        p.setReason("r");
        TaskDtos.ProposalView v = TaskDtos.ProposalView.of(p, "리플 직장인 신용대출", true, "APPLY", null);
        assertThat(v.productName()).isEqualTo("리플 직장인 신용대출");
        assertThat(TaskDtos.ProposalView.of(p, null, false, null, null).productName()).isNull();
    }
}
