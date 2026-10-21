package com.ruleripple.backend.task;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.EnumSource;

import static com.ruleripple.backend.task.TaskStatus.*;
import static org.assertj.core.api.Assertions.assertThat;

class TaskStatusTest {

    @Test
    void agentFollowsHappyPath() {
        assertThat(EXTRACTING.agentCanMoveTo(LOCATING)).isTrue();
        assertThat(LOCATING.agentCanMoveTo(DESIGNING)).isTrue();
        assertThat(DESIGNING.agentCanMoveTo(VERIFYING)).isTrue();
        assertThat(VERIFYING.agentCanMoveTo(DESIGNING)).isTrue();   // 근거 검사 실패 → 다시 작성
        assertThat(VERIFYING.agentCanMoveTo(WAITING_REVIEW)).isTrue();
        assertThat(PUBLISHING.agentCanMoveTo(DONE)).isTrue();
    }

    @Test
    void noChangeEndsEarly() {
        assertThat(EXTRACTING.agentCanMoveTo(NO_CHANGE)).isTrue();   // 요건 0건
        assertThat(LOCATING.agentCanMoveTo(NO_CHANGE)).isTrue();     // 요건은 있는데 전 상품 유지
        assertThat(EXTRACTING.agentCanMoveTo(DESIGNING)).isFalse();
        assertThat(VERIFYING.agentCanMoveTo(LOCATING)).isFalse();
    }

    @Test
    void nodesMapToStatuses() {
        assertThat(TaskStatus.fromNode("requirement_agent")).isEqualTo(EXTRACTING);
        assertThat(TaskStatus.fromNode("impact_agent")).isEqualTo(LOCATING);
        assertThat(TaskStatus.fromNode("product_impact_agent")).isEqualTo(LOCATING);   // #27 노드 이름
        assertThat(TaskStatus.fromNode("proposal_agent")).isEqualTo(DESIGNING);
        assertThat(TaskStatus.fromNode("verify")).isEqualTo(VERIFYING);
        assertThat(TaskStatus.fromNode("apply")).isEqualTo(PUBLISHING);
        assertThat(TaskStatus.fromNode("report")).isNull();
    }

    @Test
    void agentCannotSkipReview() {
        assertThat(VERIFYING.agentCanMoveTo(PUBLISHING)).isFalse();
    }

    @Test
    void onlyHumansLeaveReview() {
        // FAILED 도 안 된다. 기다리는 Agent 는 실행하지 않으므로, 그때 온 FAILED 는 겹친 요청의 뒷처리다
        for (TaskStatus next : TaskStatus.values()) {
            assertThat(WAITING_REVIEW.agentCanMoveTo(next)).as("WAITING_REVIEW → " + next).isEqualTo(next == WAITING_REVIEW);
        }
    }

    @Test
    void failedTaskRestoresToWhereItStopped() {
        assertThat(TaskStatus.restoredAfterFailure("apply", true)).isEqualTo(PUBLISHING);
        assertThat(TaskStatus.restoredAfterFailure("interrupt_review", true)).isEqualTo(PUBLISHING);   // 승인 직후 죽음
        assertThat(TaskStatus.restoredAfterFailure("interrupt_review", false)).isEqualTo(WAITING_REVIEW);
        assertThat(TaskStatus.restoredAfterFailure("proposal_agent", false)).isEqualTo(DESIGNING);
        assertThat(TaskStatus.restoredAfterFailure(null, false)).isEqualTo(EXTRACTING);
        assertThat(TaskStatus.restoredAfterFailure("report", false)).isEqualTo(EXTRACTING);
    }

    @ParameterizedTest
    @EnumSource(TaskStatus.class)
    void inProgressAndFailedTasksCanRetry(TaskStatus s) {
        boolean expected = s == FAILED || (!s.isTerminal() && s != WAITING_REVIEW);
        assertThat(s.canRetry()).as(s.name()).isEqualTo(expected);
    }

    @ParameterizedTest
    @EnumSource(value = TaskStatus.class, names = {"DONE", "NO_CHANGE", "REJECTED", "FAILED"})
    void terminalStatesStayPut(TaskStatus terminal) {
        for (TaskStatus next : TaskStatus.values()) {
            assertThat(terminal.agentCanMoveTo(next)).as(terminal + " → " + next).isEqualTo(next == terminal);
        }
    }
}
