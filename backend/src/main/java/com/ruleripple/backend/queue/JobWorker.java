package com.ruleripple.backend.queue;

import com.rabbitmq.client.Channel;
import com.ruleripple.backend.config.RuleRippleProperties;
import com.ruleripple.backend.internal.WorkTicketRepository;
import com.ruleripple.backend.internal.WorkTicket;
import com.ruleripple.backend.task.Delivery;
import com.ruleripple.backend.task.TaskService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.amqp.support.AmqpHeaders;
import org.springframework.messaging.handler.annotation.Header;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.ThreadLocalRandom;

/**
 * 큐 워커. 처리 실패 시 retry 큐로 재발행(지연 후 재시도), maxAttempts 초과 시 DLQ.
 * 시연용으로 failureRate 확률로 일부러 실패시킨다 (JOB_FAILURE_RATE=0 이면 항상 성공).
 */
@Slf4j
@Component
public class JobWorker {

    private final JobRepository jobs;
    private final JobPublisher publisher;
    private final WorkTicketRepository tickets;
    private final TaskService taskService;
    private final int maxAttempts;
    private final double failureRate;

    public JobWorker(JobRepository jobs, JobPublisher publisher, WorkTicketRepository tickets,
                     TaskService taskService, RuleRippleProperties props) {
        this.jobs = jobs;
        this.publisher = publisher;
        this.tickets = tickets;
        this.taskService = taskService;
        this.maxAttempts = props.queue().maxAttempts();
        this.failureRate = props.queue().failureRate();
    }

    @RabbitListener(queues = "${ruleripple.queue.main-queue}")
    public void onMessage(JobMessage msg, Channel channel, @Header(AmqpHeaders.DELIVERY_TAG) long tag) throws IOException {
        Job job = jobs.findById(msg.jobId()).orElse(null);
        if (job == null) {
            log.warn("job not found id={} — ack and drop", msg.jobId());
            channel.basicAck(tag, false);
            return;
        }
        job.setStatus(Job.Status.RUNNING);
        job.setAttempts(msg.attempt());
        jobs.save(job);
        emit(job, "TOOL_START", Map.<String, Object>of("tool", job.getType(), "jobId", job.getId().toString(), "attempt", msg.attempt()));

        try {
            Map<String, Object> result = process(job);
            job.setStatus(Job.Status.DONE);
            job.setResult(result);
            job.setLastError(null);
            jobs.save(job);
            emit(job, "TOOL_END", Map.<String, Object>of("tool", job.getType(), "jobId", job.getId().toString(), "ok", true, "result", result));
            channel.basicAck(tag, false);
        } catch (Exception e) {
            job.setLastError(e.getMessage());
            if (msg.attempt() < maxAttempts) {
                job.setStatus(Job.Status.RETRYING);
                jobs.save(job);
                publisher.retry(msg);
                emit(job, "TOOL_END", Map.<String, Object>of("tool", job.getType(), "jobId", job.getId().toString(), "ok", false,
                        "retrying", true, "attempt", msg.attempt(), "error", String.valueOf(e.getMessage())));
                log.warn("job failed id={} attempt={} → retry: {}", job.getId(), msg.attempt(), e.getMessage());
            } else {
                job.setStatus(Job.Status.DEAD);
                jobs.save(job);
                publisher.dead(msg);
                emit(job, "TOOL_END", Map.<String, Object>of("tool", job.getType(), "jobId", job.getId().toString(), "ok", false,
                        "dead", true, "attempt", msg.attempt(), "error", String.valueOf(e.getMessage())));
                log.error("job dead id={} after {} attempts: {}", job.getId(), msg.attempt(), e.getMessage());
            }
            channel.basicAck(tag, false); // 재발행했으므로 원 메시지는 ack
        }
    }

    private Map<String, Object> process(Job job) {
        maybeFail(job);
        return switch (job.getType()) {
            case "CREATE_TICKET" -> createTicket(job);
            case "CREATE_DRAFT_PR" -> createDraftPr(job);
            case "CHECK_PATCH" -> checkPatch(job);
            default -> throw new IllegalArgumentException("unknown job type: " + job.getType());
        };
    }

    private void maybeFail(Job job) {
        if (failureRate > 0 && ThreadLocalRandom.current().nextDouble() < failureRate) {
            throw new IllegalStateException("simulated transient failure (" + job.getType() + ")");
        }
    }

    private Map<String, Object> createTicket(Job job) {
        Map<String, Object> p = job.getPayload();
        WorkTicket t = new WorkTicket();
        t.setTaskId(job.getTaskId());
        t.setTitle(str(p, "title", "untitled"));
        t.setDescription(str(p, "description", null));
        t.setType(WorkTicket.Type.valueOf(str(p, "type", "CODE")));
        t.setTargetRef(str(p, "targetRef", null));
        t.setAssignee(str(p, "assignee", null));
        t.setCreatedBy(str(p, "createdBy", "agent"));
        WorkTicket saved = tickets.save(t);
        String ref = "RR-" + saved.getId();
        if (job.getTaskId() != null) {
            taskService.saveDelivery(job.getTaskId(), Delivery.Kind.TICKET, ref, "http://localhost/tickets/" + saved.getId());
        }
        Map<String, Object> r = new LinkedHashMap<>();
        r.put("ticketId", saved.getId());
        r.put("ref", ref);
        return r;
    }

    /** 시연용 목: 실제 GitHub 대신 브랜치명·PR 번호를 만들어 돌려준다. code-mcp 가 로컬 git 커밋까지 담당. */
    private Map<String, Object> createDraftPr(Job job) {
        Map<String, Object> p = job.getPayload();
        String branch = str(p, "branch", "rule-ripple/" + job.getId().toString().substring(0, 8));
        int prNumber = 100 + ThreadLocalRandom.current().nextInt(900);
        String url = "https://github.com/example/loan-core/pull/" + prNumber;
        if (job.getTaskId() != null) {
            taskService.saveDelivery(job.getTaskId(), Delivery.Kind.PR, "#" + prNumber, url);
        }
        Map<String, Object> r = new LinkedHashMap<>();
        r.put("branch", branch);
        r.put("prNumber", prNumber);
        r.put("url", url);
        r.put("draft", true);
        return r;
    }

    /** 패치 검증 결과 기록. 실제 샌드박스 실행은 code-mcp 가 하고, 여기서는 결과를 받아 기록만 한다. */
    private Map<String, Object> checkPatch(Job job) {
        Map<String, Object> p = job.getPayload();
        Map<String, Object> r = new LinkedHashMap<>();
        r.put("applied", Boolean.TRUE.equals(p.get("applied")));
        r.put("testsPassed", p.getOrDefault("testsPassed", 0));
        r.put("testsFailed", p.getOrDefault("testsFailed", 0));
        return r;
    }

    private void emit(Job job, String type, Map<String, Object> payload) {
        if (job.getTaskId() == null) return;
        try {
            taskService.appendEvent(job.getTaskId(), type, payload);
        } catch (Exception e) {
            log.debug("event emit skipped: {}", e.getMessage());
        }
    }

    private static String str(Map<String, Object> m, String k, String def) {
        Object v = m.get(k);
        return v == null ? def : v.toString();
    }
}
