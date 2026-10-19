package com.ruleripple.backend.queue;

import com.rabbitmq.client.Channel;
import com.ruleripple.backend.config.RuleRippleProperties;
import com.ruleripple.backend.internal.WorkTicket;
import com.ruleripple.backend.internal.WorkTicketRepository;
import com.ruleripple.backend.task.Delivery;
import com.ruleripple.backend.task.DeliveryRepository;
import com.ruleripple.backend.task.TaskEventService;
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
 * 큐 워커. 실패하면 retry 큐로 재발행(지연 후 재시도), maxAttempts 를 넘으면 DLQ.
 * 시연용으로 failureRate 확률로 일부러 실패시킨다 (JOB_FAILURE_RATE=0 이면 항상 성공).
 * 진행 상황은 TOOL_START / TOOL_END 이벤트로 화면에 흘려보낸다.
 */
@Slf4j
@Component
public class JobWorker {

    private final JobRepository jobs;
    private final JobPublisher publisher;
    private final WorkTicketRepository tickets;
    private final DeliveryRepository deliveries;
    private final TaskEventService events;
    private final int maxAttempts;
    private final double failureRate;

    public JobWorker(JobRepository jobs, JobPublisher publisher, WorkTicketRepository tickets,
                     DeliveryRepository deliveries, TaskEventService events, RuleRippleProperties props) {
        this.jobs = jobs;
        this.publisher = publisher;
        this.tickets = tickets;
        this.deliveries = deliveries;
        this.events = events;
        this.maxAttempts = props.queue().maxAttempts();
        this.failureRate = props.queue().failureRate();
    }

    @RabbitListener(queues = "${ruleripple.queue.main-queue}")
    public void onMessage(JobMessage msg, Channel channel, @Header(AmqpHeaders.DELIVERY_TAG) long tag) throws IOException {
        Job job = jobs.findById(msg.jobId()).orElse(null);
        if (job == null || job.getStatus() == Job.Status.DONE) {
            channel.basicAck(tag, false);   // 없거나 이미 끝난 작업은 버린다 (중복 전달 대비)
            return;
        }
        job.setStatus(Job.Status.RUNNING);
        job.setAttempts(msg.attempt());
        jobs.save(job);
        emit(job, "TOOL_START", Map.<String, Object>of("tool", job.getType().name(), "jobId", job.getId().toString(),
                "attempt", msg.attempt(), "maxAttempts", maxAttempts));

        try {
            Map<String, Object> result = process(job);
            job.setStatus(Job.Status.DONE);
            job.setResult(result);
            job.setLastError(null);
            jobs.save(job);
            emit(job, "TOOL_END", Map.<String, Object>of("tool", job.getType().name(), "jobId", job.getId().toString(),
                    "ok", true, "attempt", msg.attempt(), "result", result));
        } catch (Exception e) {
            String error = String.valueOf(e.getMessage());
            job.setLastError(error);
            boolean retry = msg.attempt() < maxAttempts;
            job.setStatus(retry ? Job.Status.RETRYING : Job.Status.DEAD);
            jobs.save(job);
            if (retry) publisher.retry(msg); else publisher.dead(msg);
            emit(job, "TOOL_END", Map.<String, Object>of("tool", job.getType().name(), "jobId", job.getId().toString(),
                    "ok", false, "attempt", msg.attempt(), "retrying", retry, "dead", !retry, "error", error));
            if (retry) log.warn("job failed id={} attempt={} → retry: {}", job.getId(), msg.attempt(), error);
            else log.error("job dead id={} after {} attempts: {}", job.getId(), msg.attempt(), error);
        }
        channel.basicAck(tag, false); // 실패 시에도 재발행했으므로 원 메시지는 ack
    }

    private Map<String, Object> process(Job job) {
        maybeFail(job);
        return switch (job.getType()) {
            case CREATE_TICKET -> createTicket(job);
            case CREATE_DRAFT_PR -> createDraftPr(job);
            case CHECK_PATCH -> checkPatch(job);
        };
    }

    private void maybeFail(Job job) {
        if (failureRate > 0 && ThreadLocalRandom.current().nextDouble() < failureRate) {
            throw new IllegalStateException("일시적 오류 (시연용 실패 주입: " + job.getType() + ")");
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
        t.setApprovalId(job.getApprovalId());
        t.setCreatedBy("agent");
        WorkTicket saved = tickets.save(t);
        String ref = "RR-" + saved.getId();
        String url = "/tickets/" + saved.getId();
        if (job.getTaskId() != null) {
            deliveries.save(new Delivery(job.getTaskId(), Delivery.Kind.TICKET, ref, url, job.getApprovalId()));
        }
        Map<String, Object> r = new LinkedHashMap<>();
        r.put("ticketId", saved.getId());
        r.put("ref", ref);
        r.put("url", url);
        return r;
    }

    /** 시연용 목: 실제 GitHub 대신 PR 번호와 링크를 만든다. 브랜치·커밋은 code-mcp 가 로컬 샘플 레포에 만든다. */
    private Map<String, Object> createDraftPr(Job job) {
        Map<String, Object> p = job.getPayload();
        String branch = str(p, "branch", "rule-ripple/" + job.getId().toString().substring(0, 8));
        int prNumber = 100 + Math.floorMod(job.getId().hashCode(), 900);   // 같은 작업은 같은 번호
        String url = "https://github.com/example/loan-core/pull/" + prNumber;
        if (job.getTaskId() != null) {
            deliveries.save(new Delivery(job.getTaskId(), Delivery.Kind.PR, "#" + prNumber, url, job.getApprovalId()));
        }
        Map<String, Object> r = new LinkedHashMap<>();
        r.put("branch", branch);
        r.put("prNumber", prNumber);
        r.put("url", url);
        r.put("draft", true);
        return r;
    }

    /** 샌드박스 실행 자체는 code-mcp 가 한다. 큐로 들어온 경우 결과만 기록한다. */
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
            events.append(job.getTaskId(), type, payload);
        } catch (Exception e) {
            log.debug("event emit skipped: {}", e.getMessage());
        }
    }

    private static String str(Map<String, Object> m, String k, String def) {
        Object v = m.get(k);
        return v == null ? def : v.toString();
    }
}
