package com.ruleripple.backend.task;

import com.ruleripple.backend.auth.AuthUser;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.io.IOException;
import java.net.URI;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * 레퍼런스 아키텍처의 공개 API 5개.
 *   POST /api/ai/tasks                → 202 + taskId
 *   GET  /api/ai/tasks/{id}           → 상태 + 산출물 + 승인 이력 + 전달 결과
 *   GET  /api/ai/tasks/{id}/stream    → SSE (Last-Event-ID 로 재생)
 *   POST /api/ai/tasks/{id}/approval  → interrupt 승인/반려 후 재개
 *   GET  /api/ai/tasks?mine=true      → 내 작업 목록
 */
@RestController
@RequestMapping("/api/ai/tasks")
public class TaskController {

    public record CreateRequest(@NotBlank String regulationId, @NotBlank String oldVersion,
                                @NotBlank String newVersion, String question) {}
    public record CreateResponse(UUID taskId, String status) {}
    public record ApprovalRequest(Approval.Step step, Approval.Decision decision, String comment, Map<String, Object> payload) {}

    public record TaskSummary(UUID id, String regulationId, String oldVersion, String newVersion, String status,
                              String currentStep, String createdAt) {
        static TaskSummary of(AnalysisTask t) {
            return new TaskSummary(t.getId(), t.getRegulationId(), t.getOldVersion(), t.getNewVersion(),
                    t.getStatus().name(), t.getCurrentStep(), String.valueOf(t.getCreatedAt()));
        }
    }

    public record TaskDetail(TaskSummary task, String question, String errorMessage,
                             List<TaskArtifact> artifacts, List<Approval> approvals, List<Delivery> deliveries) {}

    private final TaskService service;
    private final SseBroadcaster sse;

    public TaskController(TaskService service, SseBroadcaster sse) {
        this.service = service;
        this.sse = sse;
    }

    @PostMapping
    public ResponseEntity<CreateResponse> create(@AuthenticationPrincipal AuthUser me, @Valid @RequestBody CreateRequest req) {
        AnalysisTask task = service.create(me, req.regulationId(), req.oldVersion(), req.newVersion(), req.question());
        service.dispatch(task.getId());
        return ResponseEntity.status(HttpStatus.ACCEPTED)
                .location(URI.create("/api/ai/tasks/" + task.getId()))
                .body(new CreateResponse(task.getId(), task.getStatus().name()));
    }

    @GetMapping
    public List<TaskSummary> list(@AuthenticationPrincipal AuthUser me, @RequestParam(defaultValue = "true") boolean mine) {
        return service.list(me, mine).stream().map(TaskSummary::of).toList();
    }

    @GetMapping("/{id}")
    public TaskDetail get(@AuthenticationPrincipal AuthUser me, @PathVariable UUID id) {
        AnalysisTask t = service.get(id, me);
        return new TaskDetail(TaskSummary.of(t), t.getQuestion(), t.getErrorMessage(),
                service.artifacts(id), service.approvals(id), service.deliveries(id));
    }

    @GetMapping(value = "/{id}/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter stream(@AuthenticationPrincipal AuthUser me, @PathVariable UUID id,
                             @RequestHeader(value = "Last-Event-ID", required = false) Integer lastEventId,
                             @RequestParam(value = "after", required = false) Integer after) throws IOException {
        service.get(id, me); // 권한 확인
        SseEmitter emitter = sse.subscribe(id);
        int from = lastEventId != null ? lastEventId : (after != null ? after : 0);
        // 놓친 이벤트 재생
        for (TaskEvent e : service.eventsAfter(id, from)) {
            sse.sendTo(emitter, e);
            if ("DONE".equals(e.getType()) || "FAILED".equals(e.getType())) {
                emitter.complete();
                break;
            }
        }
        return emitter;
    }

    @PostMapping("/{id}/approval")
    public Approval approve(@AuthenticationPrincipal AuthUser me, @PathVariable UUID id, @RequestBody ApprovalRequest req) {
        return service.approve(id, me, req.step(), req.decision(), req.comment(), req.payload());
    }
}
