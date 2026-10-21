package com.ruleripple.backend.queue;

import com.rabbitmq.client.Channel;
import com.ruleripple.backend.config.RuleRippleProperties;
import com.ruleripple.backend.internal.RuleVersionService;
import com.ruleripple.backend.task.TaskEventService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.amqp.support.AmqpHeaders;
import org.springframework.messaging.handler.annotation.Header;
import org.springframework.stereotype.Component;

import java.io.IOException;
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
    private final TaskEventService events;
    private final RuleVersionService ruleVersions;
    private final int maxAttempts;
    private final double failureRate;

    public JobWorker(JobRepository jobs, JobPublisher publisher, TaskEventService events,
                     RuleVersionService ruleVersions, RuleRippleProperties props) {
        this.jobs = jobs;
        this.publisher = publisher;
        this.events = events;
        this.ruleVersions = ruleVersions;
        this.maxAttempts = props.queue().maxAttempts();
        this.failureRate = props.queue().failureRate();
    }

    @RabbitListener(queues = "${ruleripple.queue.main-queue}")
    public void onMessage(JobMessage msg, Channel channel, @Header(AmqpHeaders.DELIVERY_TAG) long tag) throws IOException {
        try {
            handle(msg);
        } catch (Exception e) {
            // 재발행·DB 오류 등 예상 밖 실패. 수동 ack 모드라 ack 를 빠뜨리면 prefetch=1 소비자가 멈춘다.
            log.error("job handling crashed id={} : {}", msg.jobId(), e.getMessage(), e);
        } finally {
            channel.basicAck(tag, false);
        }
    }

    private void handle(JobMessage msg) {
        Job job = jobs.findById(msg.jobId()).orElse(null);
        if (job == null || job.getStatus() == Job.Status.DONE) return;  // 없거나 이미 끝난 작업은 버린다 (중복 전달 대비)
        job.setStatus(Job.Status.RUNNING);
        job.setAttempts(msg.attempt());
        jobs.save(job);
        emit(job, "TOOL_START", Map.<String, Object>of("tool", job.getType().name(), "jobId", job.getId().toString(),
                "attempt", msg.attempt(), "maxAttempts", maxAttempts));

        try {
            Map<String, Object> result = process(job, msg.attempt());
            job.setStatus(Job.Status.DONE);
            job.setResult(result);
            job.setLastError(null);
            jobs.save(job);
            emit(job, "TOOL_END", Map.<String, Object>of("tool", job.getType().name(), "jobId", job.getId().toString(),
                    "ok", true, "attempt", msg.attempt(), "result", result));
        } catch (Exception e) {
            String error = String.valueOf(e.getMessage());
            job.setLastError(error);
            // 다시 해도 같은 실패(이미 바뀐 규칙 등)는 재시도하지 않는다
            boolean retry = !(e instanceof PermanentJobFailure) && msg.attempt() < maxAttempts;
            job.setStatus(retry ? Job.Status.RETRYING : Job.Status.DEAD);
            jobs.save(job);
            if (retry) publisher.retry(msg); else publisher.dead(msg);
            emit(job, "TOOL_END", Map.<String, Object>of("tool", job.getType().name(), "jobId", job.getId().toString(),
                    "ok", false, "attempt", msg.attempt(), "retrying", retry, "dead", !retry, "error", error));
            if (retry) log.warn("job failed id={} attempt={} → retry: {}", job.getId(), msg.attempt(), error);
            else log.error("job dead id={} after {} attempts: {}", job.getId(), msg.attempt(), error);
        }
    }

    private Map<String, Object> process(Job job, int attempt) {
        maybeFail(job, attempt);
        return switch (job.getType()) {
            case APPLY_RULE_VERSION -> ruleVersions.apply(job);
        };
    }

    /**
     * 시연용 실패 주입. 마지막 시도에서는 하지 않는다. 재시도는 보이되, 주입한 실패만으로 반영이 DEAD 가 되지 않게.
     * DEAD 는 진짜 오류와 다시 해도 같은 실패(PermanentJobFailure)에서만 나온다.
     */
    private void maybeFail(Job job, int attempt) {
        if (failureRate > 0 && attempt < maxAttempts && ThreadLocalRandom.current().nextDouble() < failureRate) {
            throw new IllegalStateException("일시적 오류 (시연용 실패 주입: " + job.getType() + ")");
        }
    }

    private void emit(Job job, String type, Map<String, Object> payload) {
        if (job.getTaskId() == null) return;
        try {
            events.append(job.getTaskId(), type, payload);
        } catch (Exception e) {
            log.debug("event emit skipped: {}", e.getMessage());
        }
    }
}
