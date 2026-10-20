package com.ruleripple.backend.internal;

import com.ruleripple.backend.queue.Job;
import com.ruleripple.backend.queue.JobPublisher;
import org.springframework.data.domain.Sort;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.*;

/**
 * business-mcp → Spring. 업무 규칙은 여기 한 곳에만 둔다 (MCP 는 복제하지 않음).
 *
 * 읽기 (get_product_rules, get_db_schema)
 *   GET  /internal/products?status=ON_SALE
 *   GET  /internal/product-rules?key=DSR_LIMIT&productId=P001&asOf=2026-10-20   조건 없으면 전체
 *   GET  /internal/product-rules/keys?asOf=2026-10-20                          규칙 키 목록 (기본 오늘)
 *   GET  /internal/products/{id}/rules
 *   GET  /internal/contracts/impact?dsrFrom=0.35&dsrTo=0.40&appliedBefore=2026-12-01   나이 · DSR 구간, 경과조치 판단
 *   GET  /internal/db/schema
 * 쓰기 · 승인 필요 (create_work_ticket)
 *   POST /internal/work-tickets   {taskId, approvalId, idempotencyKey, title, description?, type, targetRef?, specKeys?, assignee?}
 *                                 → ApprovalGuard 검증 → 큐 → 202 {jobId, status, duplicate}
 */
@RestController
@RequestMapping("/internal")
public class InternalBusinessController {

    public record TicketRequest(UUID taskId, Long approvalId, String idempotencyKey, String title, String description,
                                WorkTicket.Type type, String targetRef, List<String> specKeys, String assignee) {}

    private static final List<String> SCHEMA_TABLES = List.of("products", "product_rules", "loan_contracts");

    private final ProductRepository products;
    private final ProductRuleRepository rules;
    private final LoanContractRepository contracts;
    private final JdbcTemplate jdbc;
    private final JobPublisher jobs;
    private final ApprovalGuard guard;

    public InternalBusinessController(ProductRepository products, ProductRuleRepository rules,
                                      LoanContractRepository contracts, JdbcTemplate jdbc,
                                      JobPublisher jobs, ApprovalGuard guard) {
        this.products = products;
        this.rules = rules;
        this.contracts = contracts;
        this.jdbc = jdbc;
        this.jobs = jobs;
        this.guard = guard;
    }

    // ---------- 읽기 ----------

    @GetMapping("/products")
    public List<Product> products(@RequestParam(required = false) String status) {
        List<Product> all = products.findAll(Sort.by("productId"));
        return blank(status) ? all : all.stream().filter(p -> p.getStatus().equals(status)).toList();
    }

    /** asOf 를 주면 그날 유효한 행만. effectiveTo 가 null 이어도 시작 전인 행은 유효하지 않다. */
    @GetMapping("/product-rules")
    public List<ProductRule> productRules(@RequestParam(required = false) String key,
                                          @RequestParam(required = false) String productId,
                                          @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate asOf) {
        return BusinessQueries.rules(rules.findAllByOrderByRuleKeyAscProductIdAscEffectiveFromDesc(),
                blank(key) ? null : key, blank(productId) ? null : productId, asOf);
    }

    @GetMapping("/product-rules/keys")
    public List<BusinessQueries.RuleKey> ruleKeys(@RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate asOf) {
        return BusinessQueries.ruleKeys(rules.findAll(), asOf == null ? LocalDate.now() : asOf);
    }

    @GetMapping("/products/{id}/rules")
    public List<ProductRule> rulesOfProduct(@PathVariable String id) {
        if (!products.existsById(id)) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "product not found");
        return rules.findByProductIdOrderByRuleKeyAscEffectiveFromDesc(id);
    }

    @GetMapping("/contracts/impact")
    public Map<String, Object> contractImpact(@RequestParam(defaultValue = "0") int ageFrom,
                                              @RequestParam(defaultValue = "200") int ageTo,
                                              @RequestParam(required = false) BigDecimal dsrFrom,
                                              @RequestParam(required = false) BigDecimal dsrTo,
                                              @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate appliedBefore) {
        return BusinessQueries.contractImpact(contracts.findAll(),
                new BusinessQueries.ImpactQuery(ageFrom, ageTo, dsrFrom, dsrTo, appliedBefore), LocalDate.now());
    }

    @GetMapping("/db/schema")
    public List<Map<String, Object>> schema() {
        List<Map<String, Object>> cols = jdbc.queryForList("""
                select table_name, column_name, data_type, is_nullable
                from information_schema.columns
                where table_schema = 'public' and table_name in ('products', 'product_rules', 'loan_contracts')
                order by table_name, ordinal_position
                """);
        Map<String, List<Map<String, Object>>> grouped = new LinkedHashMap<>();
        for (String t : SCHEMA_TABLES) grouped.put(t, new ArrayList<>());
        for (Map<String, Object> c : cols) {
            grouped.get(String.valueOf(c.get("table_name"))).add(Map.<String, Object>of(
                    "name", String.valueOf(c.get("column_name")),
                    "type", String.valueOf(c.get("data_type")),
                    "nullable", "YES".equals(c.get("is_nullable"))));
        }
        List<Map<String, Object>> out = new ArrayList<>();
        grouped.forEach((t, cs) -> out.add(Map.<String, Object>of("table", t, "columns", cs)));
        return out;
    }

    // ---------- 쓰기 (승인 필요) ----------

    @PostMapping("/work-tickets")
    public ResponseEntity<JobPublisher.Enqueued> createTicket(@RequestBody TicketRequest req) {
        if (req.title() == null || req.title().isBlank()) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "title is required");
        List<String> specKeys = req.specKeys() == null ? List.of() : req.specKeys();
        guard.check(req.taskId(), req.approvalId(), specKeys);

        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("title", req.title());
        payload.put("description", req.description());
        payload.put("type", req.type() == null ? WorkTicket.Type.CODE.name() : req.type().name());
        payload.put("targetRef", req.targetRef());
        payload.put("specKeys", specKeys);
        payload.put("assignee", req.assignee());
        return ResponseEntity.status(HttpStatus.ACCEPTED)
                .body(jobs.publish(req.taskId(), Job.Type.CREATE_TICKET, payload, req.approvalId(), req.idempotencyKey()));
    }

    private static boolean blank(String s) {
        return s == null || s.isBlank();
    }
}
