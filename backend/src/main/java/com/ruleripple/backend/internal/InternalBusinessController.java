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

import java.time.LocalDate;
import java.util.*;

/**
 * business-mcp → Spring. 업무 규칙은 여기 한 곳에만 둔다 (MCP 는 복제하지 않음).
 *
 * 읽기 (get_product_rules, get_db_schema)
 *   GET  /internal/products
 *   GET  /internal/product-rules?key=ELIGIBLE_MIN_AGE  key 없으면 전체
 *   GET  /internal/products/{id}/rules
 *   GET  /internal/contracts/impact?ageFrom=60&ageTo=64&appliedBefore=2026-12-01   신청일 기준 만 나이 · 경과조치 판단
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
    public List<Product> products() {
        return products.findAll();
    }

    @GetMapping("/product-rules")
    public List<ProductRule> productRules(@RequestParam(required = false) String key) {
        return key == null || key.isBlank()
                ? rules.findAllByOrderByRuleKeyAscProductIdAscEffectiveFromDesc()
                : rules.findByRuleKeyOrderByProductIdAscEffectiveFromDesc(key);
    }

    @GetMapping("/products/{id}/rules")
    public List<ProductRule> rulesOfProduct(@PathVariable String id) {
        if (!products.existsById(id)) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "product not found");
        return rules.findByProductIdOrderByRuleKeyAscEffectiveFromDesc(id);
    }

    /**
     * 신청일 기준 만 나이가 [ageFrom, ageTo] 인 유효 계약 · 신청. 거절 건과 만기 지난 계약은 뺀다.
     * appliedBefore(시행일)를 주면 그 전에 신청한 건을 경과조치 대상(종전 기준 유지)으로 센다.
     */
    @GetMapping("/contracts/impact")
    public Map<String, Object> contractImpact(@RequestParam(defaultValue = "0") int ageFrom,
                                              @RequestParam(defaultValue = "200") int ageTo,
                                              @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate appliedBefore) {
        LocalDate today = LocalDate.now();
        Map<String, Long> byProduct = new TreeMap<>();
        List<Map<String, Object>> items = new ArrayList<>();
        long grandfathered = 0;
        for (LoanContract c : contracts.findAll(Sort.by("contractId"))) {
            if ("REJECTED".equals(c.getStatus())) continue;
            if (c.getMaturityDate() != null && !c.getMaturityDate().isAfter(today)) continue;
            int age = c.ageAtApplication();
            if (age < ageFrom || age > ageTo) continue;

            boolean beforeEffective = appliedBefore != null && c.getAppliedAt().isBefore(appliedBefore);
            if (beforeEffective) grandfathered++;
            byProduct.merge(c.getProductId(), 1L, Long::sum);

            Map<String, Object> item = new LinkedHashMap<>();
            item.put("contractId", c.getContractId());
            item.put("productId", c.getProductId());
            item.put("status", c.getStatus());
            item.put("appliedAt", c.getAppliedAt().toString());
            item.put("ageAtApplication", age);
            if (appliedBefore != null) item.put("grandfathered", beforeEffective);
            items.add(item);
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("ageFrom", ageFrom);
        out.put("ageTo", ageTo);
        out.put("total", items.size());
        out.put("byProduct", byProduct);
        if (appliedBefore != null) {
            out.put("appliedBefore", appliedBefore.toString());
            out.put("grandfathered", grandfathered);   // 경과조치로 종전 기준 유지
        }
        out.put("contracts", items);
        return out;
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
}
