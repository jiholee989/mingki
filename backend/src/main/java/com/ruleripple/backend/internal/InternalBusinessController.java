package com.ruleripple.backend.internal;


import com.ruleripple.backend.queue.JobPublisher;
import jakarta.validation.constraints.NotBlank;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

import java.time.LocalDate;
import java.util.*;

/**
 * business-mcp 가 호출하는 업무 API. 업무 규칙은 여기 한 곳에만 둔다 (MCP 는 복제하지 않음).
 *
 * 조회 도구 (get_*)
 *   GET  /internal/products
 *   GET  /internal/products/{id}/rules
 *   GET  /internal/rules?key=SENIOR_AGE
 *   GET  /internal/contracts/impact?ruleKey=SENIOR_AGE&from=60&to=64   (경과조치 대상 계약 수)
 *   GET  /internal/db/schema
 * 변경 도구 (승인 후에만 호출됨, destructiveHint)
 *   POST /internal/work-tickets          → 큐에 넣고 202 (워커가 처리, 실패 시 재시도)
 *   POST /internal/products/{id}/rules   → 경과조치 포함 규칙값 변경 (현재 행 종료 + 새 행)
 */
@RestController
@RequestMapping("/internal")
public class InternalBusinessController {

    public record TicketRequest(UUID taskId, @NotBlank String title, String description,
                                WorkTicket.Type type, String targetRef, String assignee, String createdBy) {}
    public record RuleChangeRequest(@NotBlank String ruleKey, @NotBlank String value,
                                    String regulationId, String regulationArticle, LocalDate effectiveFrom) {}

    private final ProductRepository products;
    private final ProductRuleRepository rules;
    private final LoanContractRepository contracts;
    private final JdbcTemplate jdbc;
    private final JobPublisher jobs;

    public InternalBusinessController(ProductRepository products, ProductRuleRepository rules,
                                      LoanContractRepository contracts, JdbcTemplate jdbc, JobPublisher jobs) {
        this.products = products;
        this.rules = rules;
        this.contracts = contracts;
        this.jdbc = jdbc;
        this.jobs = jobs;
    }

    // ---------- 조회 ----------

    @GetMapping("/products")
    public List<Product> products() {
        return products.findAll();
    }

    @GetMapping("/products/{id}/rules")
    public List<ProductRule> productRules(@PathVariable String id) {
        if (!products.existsById(id)) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "product not found");
        return rules.findByProductIdOrderByRuleKeyAscEffectiveFromDesc(id);
    }

    @GetMapping("/rules")
    public List<ProductRule> rulesByKey(@RequestParam String key) {
        return rules.findByRuleKeyOrderByProductIdAscEffectiveFromDesc(key);
    }

    /** 규정 변경 시 경과조치 판단용: 특정 나이 구간에 걸리는 유효 계약 수. */
    @GetMapping("/contracts/impact")
    public Map<String, Object> contractImpact(@RequestParam(defaultValue = "0") int from,
                                              @RequestParam(defaultValue = "200") int to) {
        List<LoanContract> hits = contracts.findByCustomerAgeBetweenAndMaturityAtAfter(from, to, LocalDate.now());
        Map<String, Long> byProduct = new TreeMap<>();
        for (LoanContract c : hits) byProduct.merge(c.getProductId(), 1L, Long::sum);
        return Map.<String, Object>of("ageFrom", from, "ageTo", to, "total", hits.size(), "byProduct", byProduct);
    }

    /** Agent 가 DB 변경 유형(③)을 설계할 때 참조하는 스키마 요약. */
    @GetMapping("/db/schema")
    public List<Map<String, Object>> schema() {
        List<Map<String, Object>> cols = jdbc.queryForList("""
                select table_name, column_name, data_type, is_nullable
                from information_schema.columns
                where table_schema = 'public'
                  and table_name in ('products','product_rules','loan_contracts','work_tickets')
                order by table_name, ordinal_position
                """);
        Map<String, List<Map<String, Object>>> grouped = new LinkedHashMap<>();
        for (Map<String, Object> c : cols) {
            grouped.computeIfAbsent(String.valueOf(c.get("table_name")), k -> new ArrayList<>())
                    .add(Map.<String, Object>of("name", c.get("column_name"), "type", c.get("data_type"), "nullable", "YES".equals(c.get("is_nullable"))));
        }
        List<Map<String, Object>> out = new ArrayList<>();
        grouped.forEach((t, cs) -> out.add(Map.<String, Object>of("table", t, "columns", cs)));
        return out;
    }

    // ---------- 변경 (승인 후) ----------

    @PostMapping("/work-tickets")
    public ResponseEntity<Map<String, Object>> createTicket(@RequestBody TicketRequest req) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("title", req.title());
        payload.put("description", req.description());
        payload.put("type", req.type() == null ? WorkTicket.Type.CODE.name() : req.type().name());
        payload.put("targetRef", req.targetRef());
        payload.put("assignee", req.assignee());
        payload.put("createdBy", req.createdBy() == null ? "agent" : req.createdBy());
        UUID jobId = jobs.publish(req.taskId(), "CREATE_TICKET", payload);
        return ResponseEntity.status(HttpStatus.ACCEPTED).body(Map.<String, Object>of("jobId", jobId, "status", "QUEUED"));
    }

    @PostMapping("/products/{id}/rules")
    public ProductRule changeRule(@PathVariable String id, @RequestBody RuleChangeRequest req) {
        if (!products.existsById(id)) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "product not found");
        LocalDate from = req.effectiveFrom() == null ? LocalDate.now() : req.effectiveFrom();

        // 현재 유효 행 종료 (경과조치: 종전 값은 effective_to 까지 유지)
        for (ProductRule current : rules.findByProductIdAndRuleKeyAndEffectiveToIsNull(id, req.ruleKey())) {
            current.setEffectiveTo(from.minusDays(1));
            rules.save(current);
        }
        ProductRule next = new ProductRule();
        next.setProductId(id);
        next.setRuleKey(req.ruleKey());
        next.setValue(req.value());
        next.setValueType("number");
        next.setRegulationId(req.regulationId());
        next.setRegulationArticle(req.regulationArticle());
        next.setEffectiveFrom(from);
        return rules.save(next);
    }
}
