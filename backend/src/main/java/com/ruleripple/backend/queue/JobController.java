package com.ruleripple.backend.queue;

import com.ruleripple.backend.internal.ApprovalGuard;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

import java.util.Collection;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * 작업 큐 (code-mcp · business-mcp · Agent 가 호출).
 *   POST /internal/jobs        {taskId, type, payload, approvalId?, idempotencyKey?} → 202
 *        CHECK_PATCH      : 승인 불필요
 *        CREATE_DRAFT_PR  : approvalId + idempotencyKey 필수, ApprovalGuard 검증
 *        CREATE_TICKET    : 〃 (보통은 /internal/work-tickets 를 쓴다)
 *   GET  /internal/jobs/{id}   상태 · 시도 횟수 · 결과 (publish 노드가 완료를 기다릴 때 폴링)
 *   GET  /internal/jobs?taskId= 작업별 큐 이력 (시연: 재시도 · DLQ)
 */
@RestController
@RequestMapping("/internal/jobs")
public class JobController {

    public record EnqueueRequest(UUID taskId, Job.Type type, Map<String, Object> payload, Long approvalId, String idempotencyKey) {}

    private final JobPublisher publisher;
    private final JobRepository jobs;
    private final ApprovalGuard guard;

    public JobController(JobPublisher publisher, JobRepository jobs, ApprovalGuard guard) {
        this.publisher = publisher;
        this.jobs = jobs;
        this.guard = guard;
    }

    @PostMapping
    public ResponseEntity<JobPublisher.Enqueued> enqueue(@RequestBody EnqueueRequest req) {
        if (req.type() == null) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "type is required");
        // 반영은 제안 · 지금 값 검사를 거치는 전용 API 로만 받는다 (임의 proposalId 로 우회 방지)
        if (req.type() == Job.Type.APPLY_RULE_VERSION) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "APPLY_RULE_VERSION 은 POST /internal/product-rules/versions 로 요청하세요");
        }
        Map<String, Object> payload = req.payload() == null ? Map.<String, Object>of() : req.payload();
        if (req.type().isWrite()) guard.check(req.taskId(), req.approvalId(), specKeysOf(payload));
        return ResponseEntity.status(HttpStatus.ACCEPTED)
                .body(publisher.publish(req.taskId(), req.type(), payload, req.approvalId(), req.idempotencyKey()));
    }

    @GetMapping("/{id}")
    public Job get(@PathVariable UUID id) {
        return jobs.findById(id).orElseThrow();
    }

    @GetMapping
    public List<Job> byTask(@RequestParam UUID taskId) {
        return jobs.findByTaskIdOrderByCreatedAtAsc(taskId);
    }

    static Collection<String> specKeysOf(Map<String, Object> payload) {
        Object raw = payload.get("specKeys");
        if (raw instanceof Collection<?> c) return c.stream().map(String::valueOf).toList();
        return List.of();
    }
}
