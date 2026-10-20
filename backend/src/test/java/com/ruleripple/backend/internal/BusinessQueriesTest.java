package com.ruleripple.backend.internal;

import com.fasterxml.jackson.annotation.JsonAutoDetect;
import com.fasterxml.jackson.annotation.PropertyAccessor;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.math.BigDecimal;
import java.nio.file.Path;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

import static org.assertj.core.api.Assertions.assertThat;

/** 실제 시드(data/business)로 계산해 계약 예시(docs/contracts)와 같은지 본다. */
class BusinessQueriesTest {

    private static final Path DATA = Path.of("../data/business");
    private static final Path CONTRACTS = Path.of("../docs/contracts");
    private static final LocalDate TODAY = LocalDate.of(2026, 10, 20);
    private static final LocalDate EFFECTIVE = LocalDate.of(2026, 12, 1);

    /** 엔티티에 setter 가 없어서 필드에 바로 넣는다. JSON 키는 snake_case. */
    private static final ObjectMapper SEED = new ObjectMapper().findAndRegisterModules()
            .setPropertyNamingStrategy(PropertyNamingStrategies.SNAKE_CASE)
            .setVisibility(PropertyAccessor.FIELD, JsonAutoDetect.Visibility.ANY)
            .disable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES);
    private static final ObjectMapper JSON = new ObjectMapper().findAndRegisterModules();

    private static List<ProductRule> rules() throws IOException {
        return SEED.readValue(DATA.resolve("product_rules.json").toFile(), new TypeReference<>() {});
    }

    private static List<LoanContract> contracts() throws IOException {
        return SEED.readValue(DATA.resolve("loan_contracts.json").toFile(), new TypeReference<>() {});
    }

    private static JsonNode contract(String file) throws IOException {
        return JSON.readTree(CONTRACTS.resolve(file).toFile());
    }

    /** 숫자 형식(0.35 vs 0.350)과 무관하게 비교하려고 한 번 직렬화했다가 다시 읽는다. */
    private static JsonNode tree(Object value) throws IOException {
        return JSON.readTree(JSON.writeValueAsString(value));
    }

    @Test
    void ruleKeysMatchContractExample() throws IOException {
        JsonNode expected = contract("rule-keys.get.json");
        Set<String> keys = new java.util.HashSet<>();
        expected.forEach(k -> keys.add(k.get("ruleKey").asText()));

        List<BusinessQueries.RuleKey> actual = BusinessQueries.ruleKeys(rules(), TODAY).stream()
                .filter(k -> keys.contains(k.ruleKey())).toList();

        assertThat(tree(actual)).isEqualTo(expected);
    }

    @Test
    void dsrImpactMatchesContractExample() throws IOException {
        var q = new BusinessQueries.ImpactQuery(0, 200, new BigDecimal("0.35"), new BigDecimal("0.40"), EFFECTIVE);
        assertThat(tree(BusinessQueries.contractImpact(contracts(), q, TODAY)))
                .isEqualTo(contract("contract-impact.get.json"));
    }

    @Test
    void ageImpactStillFindsGrandfatheredContracts() throws IOException {
        var q = new BusinessQueries.ImpactQuery(60, 64, null, null, EFFECTIVE);
        Map<String, Object> out = BusinessQueries.contractImpact(contracts(), q, TODAY);
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> items = (List<Map<String, Object>>) out.get("contracts");
        assertThat(items).extracting(i -> i.get("contractId")).contains("C0002", "C0004");
        assertThat(out).doesNotContainKeys("dsrFrom", "dsrTo");
    }

    @Test
    void validityFollowsDatesNotMissingEndDate() throws IOException {
        // 반영 직후: R001 을 11-30 에 닫고 R083 을 12-01 부터 연다
        List<ProductRule> after = new ArrayList<>(rules());
        ProductRule r001 = after.stream().filter(r -> r.getRuleId().equals("R001")).findFirst().orElseThrow();
        after.remove(r001);
        after.add(rule("R001", "P001", "DSR_LIMIT", "0.40", "2024-01-01", "2026-11-30"));
        after.add(rule("R083", "P001", "DSR_LIMIT", "0.35", "2026-12-01", null));

        assertThat(ids(BusinessQueries.rules(after, "DSR_LIMIT", "P001", TODAY))).containsExactly("R001");
        assertThat(ids(BusinessQueries.rules(after, "DSR_LIMIT", "P001", EFFECTIVE))).containsExactly("R083");

        BusinessQueries.RuleKey dsr = BusinessQueries.ruleKeys(after, TODAY).stream()
                .filter(k -> k.ruleKey().equals("DSR_LIMIT")).findFirst().orElseThrow();
        assertThat(dsr.activeRows()).isEqualTo(8);
        assertThat(dsr.upcomingRows()).isEqualTo(1);
        assertThat(dsr.closedRows()).isEqualTo(2);
    }

    @Test
    void endedOldVersionIsNotValid() throws IOException {
        // P011 의 R074(0.50)는 2023-12-31 에 끝났다. 지금 유효한 것은 R075 하나
        assertThat(ids(BusinessQueries.rules(rules(), "DSR_LIMIT", "P011", TODAY))).containsExactly("R075");
        assertThat(ids(BusinessQueries.rules(rules(), "DSR_LIMIT", "P011", null))).containsExactlyInAnyOrder("R074", "R075");
    }

    private static ProductRule rule(String id, String product, String key, String value, String from, String to) throws IOException {
        String json = """
                {"rule_id":"%s","product_id":"%s","rule_key":"%s","value":"%s","unit":"ratio","effective_from":"%s","effective_to":%s}
                """.formatted(id, product, key, value, from, to == null ? "null" : "\"" + to + "\"");
        return SEED.readValue(json, ProductRule.class);
    }

    private static List<String> ids(List<ProductRule> rules) {
        return rules.stream().map(ProductRule::getRuleId).collect(Collectors.toList());
    }
}
