package com.ruleripple.backend.task;

import org.junit.jupiter.api.Test;

import java.time.OffsetDateTime;

import static org.assertj.core.api.Assertions.assertThat;

class RetryGuardTest {

    private static final OffsetDateTime NOW = OffsetDateTime.parse("2026-10-21T10:00:00+09:00");

    @Test
    void failedTaskRetriesImmediately() {
        assertThat(RetryGuard.problem(TaskStatus.FAILED, NOW, 300, NOW)).isEmpty();
    }

    @Test
    void runningTaskWaitsForQuietTime() {
        assertThat(RetryGuard.problem(TaskStatus.DESIGNING, NOW.minusSeconds(60), 300, NOW))
                .hasValueSatisfying(reason -> assertThat(reason).contains("240초 남음"));
        assertThat(RetryGuard.problem(TaskStatus.DESIGNING, NOW.minusSeconds(300), 300, NOW)).isEmpty();
    }

    @Test
    void quietTimeCanBeTurnedOff() {
        assertThat(RetryGuard.problem(TaskStatus.DESIGNING, NOW, 0, NOW)).isEmpty();
    }

    @Test
    void waitingAndFinishedTasksAreRefusedRegardlessOfTime() {
        assertThat(RetryGuard.problem(TaskStatus.WAITING_REVIEW, NOW.minusDays(1), 300, NOW))
                .hasValueSatisfying(reason -> assertThat(reason).contains("승인을 기다리는"));
        assertThat(RetryGuard.problem(TaskStatus.DONE, NOW.minusDays(1), 300, NOW))
                .hasValueSatisfying(reason -> assertThat(reason).contains("끝난 작업"));
    }
}
