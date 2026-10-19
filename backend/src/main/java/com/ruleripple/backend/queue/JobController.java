package com.ruleripple.backend.queue;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * 범용 작업 큐 API (Agent / code-mcp 가 호출).
 *   POST /internal/jobs            {taskId, type, payload} → 202 jobId
 *   GET  /internal/jobs/{id}       상태·시도 횟수·결과
 *   GET  /internal/jobs?taskId=    작업별 큐 이력 (시연에서 재시도·DLQ 보여줄 때 사용)
 */
@RestController
@RequestMapping("/internal/jobs")
public class JobController {

    public record EnqueueRequest(UUID taskId, String type, Map<String, Object> payload) {}

    private final JobPublisher publisher;
    private final JobRepository jobs;

    public JobController(JobPublisher publisher, JobRepository jobs) {
        this.publisher = publisher;
        this.jobs = jobs;
    }

    @PostMapping
    public ResponseEntity<Map<String, Object>> enqueue(@RequestBody EnqueueRequest req) {
        UUID id = publisher.publish(req.taskId(), req.type(), req.payload());
        return ResponseEntity.status(HttpStatus.ACCEPTED).body(Map.<String, Object>of("jobId", id, "status", "QUEUED"));
    }

    @GetMapping("/{id}")
    public Job get(@PathVariable UUID id) {
        return jobs.findById(id).orElseThrow();
    }

    @GetMapping
    public List<Job> byTask(@RequestParam UUID taskId) {
        return jobs.findByTaskIdOrderByCreatedAtAsc(taskId);
    }
}
