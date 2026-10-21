package com.ruleripple.backend.queue;

import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.UUID;

/**
 * 작업 큐 조회 (Agent · business-mcp 가 호출). 반영 작업은 POST /internal/product-rules/versions 로만 넣는다.
 *   GET  /internal/jobs/{id}     상태 · 시도 횟수 · 결과 (apply 노드가 완료를 기다릴 때 폴링)
 *   GET  /internal/jobs?taskId=  작업별 큐 이력 (재시도 · DLQ 확인)
 */
@RestController
@RequestMapping("/internal/jobs")
public class JobController {

    private final JobRepository jobs;

    public JobController(JobRepository jobs) {
        this.jobs = jobs;
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
