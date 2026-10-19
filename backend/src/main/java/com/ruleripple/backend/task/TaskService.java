package com.ruleripple.backend.task;

import com.ruleripple.backend.auth.AuthUser;

import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

import java.util.List;
import java.util.Map;
import java.util.UUID;

@Slf4j
@Service
public class TaskService {

    private final AnalysisTaskRepository tasks;
    private final TaskEventRepository events;
    private final TaskArtifactRepository artifacts;
    private final ApprovalRepository approvals;
    private final DeliveryRepository deliveries;
    private final AgentClient agent;
    private final SseBroadcaster sse;

    public TaskService(AnalysisTaskRepository tasks, TaskEventRepository events, TaskArtifactRepository artifacts,
                       ApprovalRepository approvals, DeliveryRepository deliveries, AgentClient agent, SseBroadcaster sse) {
        this.tasks = tasks;
        this.events = events;
        this.artifacts = artifacts;
        this.approvals = approvals;
        this.deliveries = deliveries;
        this.agent = agent;
        this.sse = sse;
    }

    // ---------- 접수 (202) ----------

    @Transactional
    public AnalysisTask create(AuthUser me, String regulationId, String oldVersion, String newVersion, String question) {
        AnalysisTask task = tasks.save(AnalysisTask.create(me.id(), regulationId, oldVersion, newVersion, question));
        appendEvent(task.getId(), "STEP", Map.<String, Object>of("step", "queued", "message", "작업이 접수되었습니다"));
        return task;
    }

    /** 트랜잭션 커밋 후 비동기로 Agent 에 실행 요청. 실패하면 FAILED 로 기록. */
    @Async
    public void dispatch(UUID taskId) {
        AnalysisTask task = tasks.findById(taskId).orElseThrow();
        try {
            agent.run(task);
            updateStatus(taskId, AnalysisTask.Status.RUNNING, "requirement_agent", null);
        } catch (Exception e) {
            log.warn("agent dispatch failed task={} : {}", taskId, e.getMessage());
            updateStatus(taskId, AnalysisTask.Status.FAILED, null, "agent unreachable: " + e.getMessage());
            appendEvent(taskId, "FAILED", Map.<String, Object>of("reason", "agent unreachable", "detail", String.valueOf(e.getMessage())));
        }
    }

    // ---------- 조회 ----------

    @Transactional(readOnly = true)
    public AnalysisTask get(UUID taskId, AuthUser me) {
        AnalysisTask task = tasks.findById(taskId)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "task not found"));
        if (!me.isLead() && !task.getRequesterId().equals(me.id())) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "not your task");
        }
        return task;
    }

    @Transactional(readOnly = true)
    public List<AnalysisTask> list(AuthUser me, boolean mine) {
        if (mine || !me.isLead()) return tasks.findByRequesterIdOrderByCreatedAtDesc(me.id());
        return tasks.findAllByOrderByCreatedAtDesc();
    }

    @Transactional(readOnly = true)
    public List<TaskEvent> eventsAfter(UUID taskId, int afterSeq) {
        return events.findByTaskIdAndSeqGreaterThanOrderBySeqAsc(taskId, afterSeq);
    }

    @Transactional(readOnly = true)
    public List<TaskArtifact> artifacts(UUID taskId) {
        return artifacts.findByTaskIdOrderByIdAsc(taskId);
    }

    @Transactional(readOnly = true)
    public List<Approval> approvals(UUID taskId) {
        return approvals.findByTaskIdOrderByIdAsc(taskId);
    }

    @Transactional(readOnly = true)
    public List<Delivery> deliveries(UUID taskId) {
        return deliveries.findByTaskIdOrderByIdAsc(taskId);
    }

    // ---------- 승인 (interrupt ① REVIEW / ② PUBLISH) ----------

    @Transactional
    public Approval approve(UUID taskId, AuthUser me, Approval.Step step, Approval.Decision decision,
                            String comment, Map<String, Object> payload) {
        AnalysisTask task = get(taskId, me);

        AnalysisTask.Status expected = step == Approval.Step.REVIEW
                ? AnalysisTask.Status.WAITING_REVIEW : AnalysisTask.Status.WAITING_PUBLISH;
        if (task.getStatus() != expected) {
            throw new ResponseStatusException(HttpStatus.CONFLICT,
                    "task is " + task.getStatus() + ", expected " + expected);
        }
        // PUBLISH(PR·티켓 생성) 승인은 LEAD 만 가능
        if (step == Approval.Step.PUBLISH && !me.isLead()) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "PUBLISH approval requires LEAD role");
        }

        Approval saved = approvals.save(new Approval(taskId, step, decision, me.id(), comment, payload));

        if (decision == Approval.Decision.REJECT) {
            task.setStatus(AnalysisTask.Status.REJECTED);
            task.setCurrentStep("rejected");
            appendEvent(taskId, "STEP", Map.<String, Object>of("step", "rejected", "by", me.username(), "at", step.name()));
        } else {
            task.setStatus(step == Approval.Step.REVIEW ? AnalysisTask.Status.RUNNING : AnalysisTask.Status.PUBLISHING);
            task.setCurrentStep(step == Approval.Step.REVIEW ? "publish" : "create_draft_pr");
            appendEvent(taskId, "RESUMED", Map.<String, Object>of("step", step.name(), "by", me.username()));
        }
        tasks.save(task);

        try {
            agent.resume(task, step, decision, payload);
        } catch (Exception e) {
            log.warn("agent resume failed task={} : {}", taskId, e.getMessage());
            task.setStatus(AnalysisTask.Status.FAILED);
            task.setErrorMessage("agent unreachable on resume: " + e.getMessage());
            appendEvent(taskId, "FAILED", Map.<String, Object>of("reason", "agent unreachable on resume"));
        }
        return saved;
    }

    // ---------- Agent 콜백 (/internal) ----------

    /** Agent 가 보낸 이벤트를 저장하고 SSE 로 흘려보낸다. 상태 전이가 필요한 이벤트는 여기서 반영. */
    @Transactional
    public TaskEvent appendEvent(UUID taskId, String type, Map<String, Object> payload) {
        int seq = events.maxSeq(taskId) + 1;
        TaskEvent saved = events.save(new TaskEvent(taskId, seq, type, payload));

        tasks.findById(taskId).ifPresent(task -> {
            switch (type) {
                case "STEP" -> {
                    Object step = payload == null ? null : payload.get("step");
                    if (step != null) task.setCurrentStep(step.toString());
                    if (task.getStatus() == AnalysisTask.Status.QUEUED && step != null && !"queued".equals(step)) {
                        task.setStatus(AnalysisTask.Status.RUNNING);
                    }
                }
                case "APPROVAL_REQUIRED" -> {
                    Object step = payload == null ? null : payload.get("step");
                    task.setStatus("PUBLISH".equals(String.valueOf(step))
                            ? AnalysisTask.Status.WAITING_PUBLISH : AnalysisTask.Status.WAITING_REVIEW);
                    task.setCurrentStep("waiting_" + String.valueOf(step).toLowerCase());
                }
                case "DONE" -> {
                    task.setStatus(AnalysisTask.Status.DONE);
                    task.setCurrentStep("done");
                }
                case "FAILED" -> {
                    task.setStatus(AnalysisTask.Status.FAILED);
                    task.setCurrentStep("failed");
                    if (payload != null && payload.get("reason") != null) task.setErrorMessage(payload.get("reason").toString());
                }
                default -> { /* TOKEN, TOOL_START, TOOL_END, RESUMED: 상태 변화 없음 */ }
            }
            tasks.save(task);
        });

        sse.send(taskId, saved);
        return saved;
    }

    @Transactional
    public TaskArtifact saveArtifact(UUID taskId, String kind, int round, Map<String, Object> payload) {
        if (!tasks.existsById(taskId)) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "task not found");
        return artifacts.save(new TaskArtifact(taskId, kind, round, payload));
    }

    @Transactional
    public Delivery saveDelivery(UUID taskId, Delivery.Kind kind, String externalRef, String url) {
        return deliveries.save(new Delivery(taskId, kind, externalRef, url));
    }

    @Transactional
    public void updateStatus(UUID taskId, AnalysisTask.Status status, String step, String error) {
        tasks.findById(taskId).ifPresent(t -> {
            t.setStatus(status);
            if (step != null) t.setCurrentStep(step);
            if (error != null) t.setErrorMessage(error);
            tasks.save(t);
        });
    }
}
