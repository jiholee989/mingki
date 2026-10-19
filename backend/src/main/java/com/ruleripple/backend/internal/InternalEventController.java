package com.ruleripple.backend.internal;

import com.ruleripple.backend.task.Delivery;
import com.ruleripple.backend.task.TaskArtifact;
import com.ruleripple.backend.task.TaskEvent;
import com.ruleripple.backend.task.TaskService;
import jakarta.validation.constraints.NotBlank;
import org.springframework.web.bind.annotation.*;

import java.util.Map;
import java.util.UUID;

/**
 * Agent → Spring 콜백.
 *   POST /internal/tasks/{id}/events      진행 이벤트 (SSE 로 중계)
 *   POST /internal/tasks/{id}/artifacts   산출물 저장 (명세서, 패치, 테스트, 검증 결과, 보고서)
 *   POST /internal/tasks/{id}/deliveries  Draft PR / 티켓 생성 결과 기록
 */
@RestController
@RequestMapping("/internal/tasks/{taskId}")
public class InternalEventController {

    public record EventRequest(@NotBlank String type, Map<String, Object> payload) {}
    public record ArtifactRequest(@NotBlank String kind, Integer round, Map<String, Object> payload) {}
    public record DeliveryRequest(Delivery.Kind kind, String externalRef, String url) {}

    private final TaskService service;

    public InternalEventController(TaskService service) {
        this.service = service;
    }

    @PostMapping("/events")
    public Map<String, Object> event(@PathVariable UUID taskId, @RequestBody EventRequest req) {
        TaskEvent saved = service.appendEvent(taskId, req.type(), req.payload());
        return Map.<String, Object>of("seq", saved.getSeq());
    }

    @PostMapping("/artifacts")
    public Map<String, Object> artifact(@PathVariable UUID taskId, @RequestBody ArtifactRequest req) {
        TaskArtifact saved = service.saveArtifact(taskId, req.kind(), req.round() == null ? 0 : req.round(), req.payload());
        return Map.<String, Object>of("id", saved.getId());
    }

    @PostMapping("/deliveries")
    public Map<String, Object> delivery(@PathVariable UUID taskId, @RequestBody DeliveryRequest req) {
        Delivery saved = service.saveDelivery(taskId, req.kind(), req.externalRef(), req.url());
        return Map.<String, Object>of("id", saved.getId());
    }
}
