package com.ruleripple.backend.internal;

import com.ruleripple.backend.task.*;
import com.ruleripple.backend.task.TaskDtos.ApprovalView;
import jakarta.validation.constraints.NotBlank;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * Agent · regulation-mcp → Spring. AgentClient 가 넘긴 callbackBaseUrl = /internal/tasks/{taskId}.
 *
 *   GET  /internal/tasks/{id}              작업 정보 (status, threadId, verifyRound)
 *   GET  /internal/tasks/{id}/documents    규정 v3 · v4 원문
 *   GET  /internal/tasks/{id}/approvals          확인 기록 (반영 · 제외한 제안 키)
 *   POST /internal/tasks/{id}/events             진행 이벤트 → SSE
 *   PUT  /internal/tasks/{id}/requirements       requirement_agent 결과 (전체 교체, EXTRACTING 에서만)
 *   PUT  /internal/tasks/{id}/proposals          제안 · 근거 검사 결과 ((proposalKey, round) upsert)
 *   PUT  /internal/tasks/{id}/contract-impacts   경과조치 계약 영향 (전체 교체)
 *   PUT  /internal/tasks/{id}/report             report 노드 결과
 *   PUT  /internal/tasks/{id}/evaluation   정답지 점수 · 키워드 검색 비교
 */
@RestController
@RequestMapping("/internal/tasks/{taskId}")
public class InternalTaskController {

    public record EventRequest(@NotBlank String type, Map<String, Object> payload) {}
    public record Items<T>(List<T> items) {}
    public record TaskInfo(UUID id, String title, String status, String currentNode, int verifyRound, String threadId) {}
    public record DocumentView(String side, String versionLabel, String filename, String sha256, String content) {}

    private final TaskService tasks;
    private final TaskEventService events;
    private final AgentResultService results;

    public InternalTaskController(TaskService tasks, TaskEventService events, AgentResultService results) {
        this.tasks = tasks;
        this.events = events;
        this.results = results;
    }

    @GetMapping
    public TaskInfo task(@PathVariable UUID taskId) {
        AnalysisTask t = tasks.get(taskId);
        return new TaskInfo(t.getId(), t.getTitle(), t.getStatus().name(), t.getCurrentNode(), t.getVerifyRound(), t.getThreadId());
    }

    @GetMapping("/documents")
    public List<DocumentView> documents(@PathVariable UUID taskId) {
        return tasks.documents(taskId).stream()
                .map(d -> new DocumentView(d.getSide().name(), d.getVersionLabel(), d.getFilename(), d.getSha256(), d.getContent()))
                .toList();
    }

    @GetMapping("/approvals")
    public List<ApprovalView> approvals(@PathVariable UUID taskId) {
        return tasks.approvals(taskId);
    }

    @PostMapping("/events")
    public Map<String, Object> event(@PathVariable UUID taskId, @RequestBody EventRequest req) {
        if (req.type() == null || req.type().isBlank()) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "type is required");
        TaskEvent saved = events.appendFromAgent(taskId, req.type(), req.payload());
        return Map.<String, Object>of("seq", saved.getSeq());
    }

    @PutMapping("/requirements")
    public Map<String, Object> requirements(@PathVariable UUID taskId, @RequestBody Items<AgentResultService.RequirementItem> body) {
        return Map.<String, Object>of("saved", results.replaceRequirements(taskId, body.items()));
    }

    @PutMapping("/proposals")
    public Map<String, Object> proposals(@PathVariable UUID taskId, @RequestBody Items<Proposals.Item> body) {
        return Map.<String, Object>of("saved", results.upsertProposals(taskId, body.items()));
    }

    @PutMapping("/contract-impacts")
    public Map<String, Object> contractImpacts(@PathVariable UUID taskId, @RequestBody Items<Map<String, Object>> body) {
        return Map.<String, Object>of("saved", results.replaceContractImpacts(taskId, body.items()));
    }

    @PutMapping("/report")
    public Map<String, Object> report(@PathVariable UUID taskId, @RequestBody Map<String, Object> report) {
        results.saveReport(taskId, report);
        return Map.<String, Object>of("ok", true);
    }

    @PutMapping("/evaluation")
    public Map<String, Object> evaluation(@PathVariable UUID taskId, @RequestBody Map<String, Object> evaluation) {
        results.saveEvaluation(taskId, evaluation);
        return Map.<String, Object>of("ok", true);
    }
}
