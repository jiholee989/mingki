package com.ruleripple.backend.queue;

import com.ruleripple.backend.config.RabbitConfig;
import com.ruleripple.backend.config.RuleRippleProperties;
import lombok.extern.slf4j.Slf4j;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import java.util.Map;
import java.util.UUID;

@Slf4j
@Service
public class JobPublisher {

    private final JobRepository jobs;
    private final RabbitTemplate rabbit;
    private final String exchange;

    public JobPublisher(JobRepository jobs, RabbitTemplate rabbit, RuleRippleProperties props) {
        this.jobs = jobs;
        this.rabbit = rabbit;
        this.exchange = props.queue().exchange();
    }

    /** jobs 행을 먼저 커밋하고, 커밋 이후에 메시지를 발행한다 (워커가 행을 못 찾는 경쟁 방지). */
    @Transactional
    public UUID publish(UUID taskId, String type, Map<String, Object> payload) {
        Job job = jobs.save(Job.create(taskId, type, payload));
        JobMessage msg = new JobMessage(job.getId(), 1);
        TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
            @Override
            public void afterCommit() {
                rabbit.convertAndSend(exchange, RabbitConfig.RK_JOB, msg);
                log.info("job queued id={} type={}", job.getId(), type);
            }
        });
        return job.getId();
    }

    public void retry(JobMessage msg) {
        rabbit.convertAndSend(exchange, RabbitConfig.RK_RETRY, msg.next());
    }

    public void dead(JobMessage msg) {
        rabbit.convertAndSend(exchange, RabbitConfig.RK_DEAD, msg);
    }
}
