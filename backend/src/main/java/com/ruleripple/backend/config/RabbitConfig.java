package com.ruleripple.backend.config;

import org.springframework.amqp.core.*;
import org.springframework.amqp.rabbit.connection.ConnectionFactory;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.amqp.support.converter.Jackson2JsonMessageConverter;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.util.Map;

/**
 * 토폴로지
 *   rr.jobs (direct)
 *     ├─ rr.jobs.q      routing "job"    ← 워커가 소비. 실패 시 retry 큐로 재발행
 *     ├─ rr.jobs.retry  routing "retry"  TTL 후 dead-letter 로 rr.jobs.q 에 되돌아감
 *     └─ rr.jobs.dlq    routing "dead"   max attempts 초과 시 최종 보관
 */
@Configuration
public class RabbitConfig {

    public static final String RK_JOB = "job";
    public static final String RK_RETRY = "retry";
    public static final String RK_DEAD = "dead";

    @Bean
    DirectExchange jobsExchange(RuleRippleProperties p) {
        return new DirectExchange(p.queue().exchange(), true, false);
    }

    @Bean
    Queue mainQueue(RuleRippleProperties p) {
        return QueueBuilder.durable(p.queue().mainQueue()).build();
    }

    @Bean
    Queue retryQueue(RuleRippleProperties p) {
        return QueueBuilder.durable(p.queue().retryQueue())
                .withArguments(Map.<String, Object>of(
                        "x-message-ttl", p.queue().retryDelayMs(),
                        "x-dead-letter-exchange", p.queue().exchange(),
                        "x-dead-letter-routing-key", RK_JOB))
                .build();
    }

    @Bean
    Queue deadLetterQueue(RuleRippleProperties p) {
        return QueueBuilder.durable(p.queue().deadLetterQueue()).build();
    }

    @Bean Binding bindMain(Queue mainQueue, DirectExchange jobsExchange) { return BindingBuilder.bind(mainQueue).to(jobsExchange).with(RK_JOB); }
    @Bean Binding bindRetry(Queue retryQueue, DirectExchange jobsExchange) { return BindingBuilder.bind(retryQueue).to(jobsExchange).with(RK_RETRY); }
    @Bean Binding bindDead(Queue deadLetterQueue, DirectExchange jobsExchange) { return BindingBuilder.bind(deadLetterQueue).to(jobsExchange).with(RK_DEAD); }

    @Bean
    Jackson2JsonMessageConverter jsonMessageConverter() {
        Jackson2JsonMessageConverter c = new Jackson2JsonMessageConverter();
        c.getJavaTypeMapper().addTrustedPackages("com.ruleripple.backend");
        return c;
    }

    @Bean
    RabbitTemplate rabbitTemplate(ConnectionFactory cf, Jackson2JsonMessageConverter converter) {
        RabbitTemplate t = new RabbitTemplate(cf);
        t.setMessageConverter(converter);
        return t;
    }
}
