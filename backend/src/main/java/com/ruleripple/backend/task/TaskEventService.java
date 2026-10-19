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
 *   STATUS            {status}                  상태를 직접 지정 (예외 상황용)
 *   APPROVAL_REQUIRED {step: REQUIREMENTS|REVIEW, summary?}
 *   RESUMED           {step, decision, by}
 *   TOKEN             {text}
 *   TOOL_START        {tool, args?}
 *   TOOL_END          {tool, ok, result?|error?}
 *   DONE              {outcome: DONE|NO_CHANGE|HELD|REJECTED}
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

    @Transactional
    public TaskEvent append(UUID taskId, String type, Map<String, Object> payload) {
        AnalysisTask task = tasks.findForUpdate(taskId)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "task not found"));
        Map<String, Object> body = payload == null ? Map.of() : payload;

        int seq = events.maxSeq(taskId) + 1;
        TaskEvent saved = events.save(new TaskEvent(taskId, seq, type, body));
        applyTransition(task, type, body);
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
                if (s != null) task.setStatus(TaskStatus.valueOf(s));
            }
            case "APPROVAL_REQUIRED" -> {
                if (task.getStatus().isTerminal()) return;
                boolean review = "REVIEW".equals(str(p.get("step")));
                task.setStatus(review ? TaskStatus.WAITING_REVIEW : TaskStatus.WAITING_REQUIREMENT_APPROVAL);
                task.setCurrentNode(review ? "interrupt_review" : "interrupt_requirements");
            }
            case "DONE" -> {
                String outcome = str(p.get("outcome"));
                TaskStatus s = outcome == null ? TaskStatus.DONE : TaskStatus.valueOf(outcome);
                if (!s.isTerminal() || s == TaskStatus.FAILED) {
                    throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "DONE.outcome must be DONE|NO_CHANGE|HELD|REJECTED");
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

    private static String str(Object o) {
        return o == null ? null : o.toString();
    }
}
