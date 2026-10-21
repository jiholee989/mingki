package com.ruleripple.backend.task;

import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.web.server.ResponseStatusException;

import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * 진행 이벤트 저장 + 작업 상태 전이를 한곳에서 처리한다.
 * Agent 콜백, 큐 워커, 승인 API 가 동시에 이벤트를 쓰므로 작업 행을 잠그고 seq 를 채번한다.
 * SSE 전송은 커밋 이후에 한다 (클라이언트가 받은 이벤트는 항상 DB 에도 있다).
 *
 * 이벤트 type
 *   STEP              {node, round?, message?}  노드 진입. node → 상태 (TaskStatus.fromNode)
 *   STATUS            {status, reason?}         상태를 직접 지정 (예외 상황용). reason 은 errorMessage 로 남는다
 *   APPROVAL_REQUIRED {step: REVIEW, summary?}
 *   RESUMED           {step, decision, by}
 *   TOKEN             {text}
 *   TOOL_START        {tool, args?}
 *   TOOL_END          {tool, ok, result?|error?}
 *   DONE              {outcome: DONE|NO_CHANGE|REJECTED}
 *   FAILED            {reason}
 */
@Service
public class TaskEventService {

    private final AnalysisTaskRepository tasks;
    private final TaskEventRepository events;
    private final SseBroadcaster sse;

    public TaskEventService(AnalysisTaskRepository tasks, TaskEventRepository events, SseBroadcaster sse) {
        this.tasks = tasks;
        this.events = events;
        this.sse = sse;
    }

    /** 서버 내부(승인 API · 큐 워커 · 디스패처)용. 전이를 검사하지 않는다. */
    @Transactional
    public TaskEvent append(UUID taskId, String type, Map<String, Object> payload) {
        return append(taskId, type, payload, false);
    }

    /** Agent 콜백용. TaskStatus.agentCanMoveTo 에 없는 전이는 409. */
    @Transactional
    public TaskEvent appendFromAgent(UUID taskId, String type, Map<String, Object> payload) {
        return append(taskId, type, payload, true);
    }

    private TaskEvent append(UUID taskId, String type, Map<String, Object> payload, boolean fromAgent) {
        AnalysisTask task = tasks.findForUpdate(taskId)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "task not found"));
        Map<String, Object> body = payload == null ? Map.of() : payload;

        int seq = events.maxSeq(taskId) + 1;
        TaskEvent saved = events.save(new TaskEvent(taskId, seq, type, body));
        TaskStatus before = task.getStatus();
        applyTransition(task, type, body);
        if (fromAgent && !before.agentCanMoveTo(task.getStatus())) {
            throw new ResponseStatusException(HttpStatus.CONFLICT,
                    type + " 이벤트로 " + before + " → " + task.getStatus() + " 전이는 할 수 없습니다");
        }
        tasks.save(task);
        boolean terminal = task.getStatus().isTerminal();

        if (TransactionSynchronizationManager.isSynchronizationActive()) {
            TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
                @Override
                public void afterCommit() {
                    sse.send(taskId, saved, terminal);
                }
            });
        } else {
            sse.send(taskId, saved, terminal);
        }
        return saved;
    }

    @Transactional(readOnly = true)
    public List<TaskEvent> after(UUID taskId, int afterSeq) {
        return events.findByTaskIdAndSeqGreaterThanOrderBySeqAsc(taskId, afterSeq);
    }

    private void applyTransition(AnalysisTask task, String type, Map<String, Object> p) {
        switch (type) {
            case "STEP" -> {
                if (task.getStatus().isTerminal()) return;
                String node = str(p.get("node"));
                if (node != null) task.setCurrentNode(node);
                TaskStatus next = TaskStatus.fromNode(node);
                if (next != null) task.setStatus(next);
                if ("verify".equals(node) && p.get("round") instanceof Number n) task.setVerifyRound(n.intValue());
            }
            case "STATUS" -> {
                String s = str(p.get("status"));
                if (s != null) task.setStatus(parseStatus(s));
                if (task.getStatus() == TaskStatus.WAITING_REVIEW) task.setCurrentNode("interrupt_review");
                String reason = str(p.get("reason"));
                if (reason != null) task.setErrorMessage(reason);
            }
            case "APPROVAL_REQUIRED" -> {
                if (!"REVIEW".equals(str(p.get("step")))) {
                    throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "APPROVAL_REQUIRED.step must be REVIEW");
                }
                if (task.getStatus().isTerminal()) return;
                task.setStatus(TaskStatus.WAITING_REVIEW);
                task.setCurrentNode("interrupt_review");
            }
            case "DONE" -> {
                String outcome = str(p.get("outcome"));
                TaskStatus s = outcome == null ? TaskStatus.DONE : parseStatus(outcome);
                if (!s.isTerminal() || s == TaskStatus.FAILED) {
                    throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "DONE.outcome must be DONE|NO_CHANGE|REJECTED");
                }
                task.setStatus(s);
                task.setCurrentNode("report");
            }
            case "FAILED" -> {
                task.setStatus(TaskStatus.FAILED);
                task.setErrorMessage(str(p.get("reason")));
            }
            default -> { /* TOKEN, TOOL_START, TOOL_END, RESUMED: 상태 변화 없음 */ }
        }
    }

    private static TaskStatus parseStatus(String s) {
        try {
            return TaskStatus.valueOf(s);
        } catch (IllegalArgumentException e) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "알 수 없는 상태: " + s);
        }
    }

    private static String str(Object o) {
        return o == null ? null : o.toString();
    }
}
