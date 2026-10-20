package com.ruleripple.backend.queue;

import com.rabbitmq.client.Channel;
import com.ruleripple.backend.config.RuleRippleProperties;
import com.ruleripple.backend.internal.RuleVersionService;
import com.ruleripple.backend.internal.WorkTicketRepository;
import com.ruleripple.backend.task.DeliveryRepository;
import com.ruleripple.backend.task.TaskEventService;
import org.junit.jupiter.api.Test;

import java.util.Map;
import java.util.Optional;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

/** 반영 작업의 실패 처리: 일시 실패는 재시도, 다시 해도 같은 실패는 바로 DEAD. */
class JobWorkerTest {

    private final JobRepository jobs = mock(JobRepository.class);
    private final JobPublisher publisher = mock(JobPublisher.class);
    private final RuleVersionService ruleVersions = mock(RuleVersionService.class);
    private final Channel channel = mock(Channel.class);
    private final JobWorker worker = new JobWorker(jobs, publisher, mock(WorkTicketRepository.class),
            mock(DeliveryRepository.class), mock(TaskEventService.class), ruleVersions, props());

    private static RuleRippleProperties props() {
        var queue = new RuleRippleProperties.Queue("rr.jobs", "rr.jobs.q", "rr.jobs.retry", "rr.jobs.dlq", 3000, 3, 0.0);
        return new RuleRippleProperties(null, null, null, queue, null, null);
    }

    private Job job() {
        Job j = Job.create(UUID.randomUUID(), Job.Type.APPLY_RULE_VERSION, Map.of("proposalId", 1), 7L, "t:apply:P001");
        when(jobs.findById(j.getId())).thenReturn(Optional.of(j));
        return j;
    }

    @Test
    void permanentFailureGoesDeadWithoutRetry() throws Exception {
        Job j = job();
        when(ruleVersions.apply(any())).thenThrow(new PermanentJobFailure("이미 바뀐 규칙: R001 값이 0.40이 아니라 0.38입니다"));

        worker.onMessage(new JobMessage(j.getId(), 1), channel, 1L);

        assertThat(j.getStatus()).isEqualTo(Job.Status.DEAD);
        assertThat(j.getLastError()).contains("이미 바뀐 규칙");
        verify(publisher).dead(any());
        verify(publisher, never()).retry(any());
        verify(channel).basicAck(1L, false);
    }

    @Test
    void transientFailureIsRetried() throws Exception {
        Job j = job();
        when(ruleVersions.apply(any())).thenThrow(new IllegalStateException("DB 연결 끊김"));

        worker.onMessage(new JobMessage(j.getId(), 1), channel, 1L);

        assertThat(j.getStatus()).isEqualTo(Job.Status.RETRYING);
        verify(publisher).retry(any());
        verify(publisher, never()).dead(any());
    }

    @Test
    void successStoresResult() throws Exception {
        Job j = job();
        when(ruleVersions.apply(any())).thenReturn(Map.of("closedRuleId", "R001", "newRuleId", "R083"));

        worker.onMessage(new JobMessage(j.getId(), 1), channel, 1L);

        assertThat(j.getStatus()).isEqualTo(Job.Status.DONE);
        assertThat(j.getResult()).containsEntry("newRuleId", "R083");
    }
}
