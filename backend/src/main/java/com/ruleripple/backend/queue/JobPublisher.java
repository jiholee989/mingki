package com.ruleripple.backend.queue;

import com.ruleripple.backend.config.RabbitConfig;
import com.ruleripple.backend.config.RuleRippleProperties;
import lombok.extern.slf4j.Slf4j;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.web.server.ResponseStatusException;

import java.util.Map;
import java.util.Optional;
import java.util.UUID;

@Slf4j
@Service
public class JobPublisher {

    /** duplicate=true 면 같은 멱등키로 이미 접수된 작업을 그대로 돌려준 것 (새로 만들지 않음). */
    public record Enqueued(UUID jobId, Job.Status status, boolean duplicate) {}

    private final JobRepository jobs;
    private final RabbitTemplate rabbit;
    private final String exchange;

    public JobPublisher(JobRepository jobs, RabbitTemplate rabbit, RuleRippleProperties props) {
        this.jobs = jobs;
        this.rabbit = rabbit;
        this.exchange = props.queue().exchange();
    }

    /**
     * jobs 행을 먼저 커밋하고, 커밋 이후에 메시지를 발행한다 (워커가 행을 못 찾는 경쟁 방지).
     * 멱등키가 필수다. 같은 키로 다시 오면 기존 작업을 돌려준다 (같은 규칙을 두 번 반영하지 않게).
     */
    @Transactional
    public Enqueued publish(UUID taskId, Job.Type type, Map<String, Object> payload, Long approvalId, String idempotencyKey) {
        if (idempotencyKey == null || idempotencyKey.isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, type + " 는 idempotencyKey 가 필요합니다");
        }
        Optional<Job> existing = jobs.findByIdempotencyKey(idempotencyKey);
        if (existing.isPresent()) {
            Job j = existing.get();
            if (!j.getType().equals(type) || (taskId != null && !taskId.equals(j.getTaskId()))) {
                throw new ResponseStatusException(HttpStatus.CONFLICT, "같은 idempotencyKey 가 다른 작업에 쓰였습니다");
            }
            log.info("duplicate job ignored key={} job={}", idempotencyKey, j.getId());
            return new Enqueued(j.getId(), j.getStatus(), true);
        }
        Job job = jobs.saveAndFlush(Job.create(taskId, type, payload, approvalId, idempotencyKey));
        JobMessage msg = new JobMessage(job.getId(), 1);
        TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
            @Override
            public void afterCommit() {
                rabbit.convertAndSend(exchange, RabbitConfig.RK_JOB, msg);
                log.info("job queued id={} type={}", msg.jobId(), type);
            }
        });
        return new Enqueued(job.getId(), job.getStatus(), false);
    }

    public void retry(JobMessage msg) {
        rabbit.convertAndSend(exchange, RabbitConfig.RK_RETRY, msg.next());
    }

    public void dead(JobMessage msg) {
        rabbit.convertAndSend(exchange, RabbitConfig.RK_DEAD, msg);
    }
}
