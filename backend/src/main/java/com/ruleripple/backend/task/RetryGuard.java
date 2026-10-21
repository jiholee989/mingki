package com.ruleripple.backend.task;

import java.time.Duration;
import java.time.OffsetDateTime;
import java.util.Optional;

/**
 * "다시 시도"를 받아도 되는지 판단한다 (DB 없이 테스트할 수 있는 순수 함수).
 *
 * 백엔드는 Agent 가 죽었는지 아직 돌고 있는지 알 수 없다. 돌고 있는 작업에 /continue · /run 을 겹쳐 보내면
 * 같은 thread 를 두 번 돌리게 되므로, 진행 중인 작업은 마지막 변화 뒤 조용한 시간이 지나야 받는다.
 * FAILED 는 Agent 가 이미 멈춘 것이므로 바로 받는다.
 */
final class RetryGuard {

    private static final String FIRST = "(처음 실패: ";

    private RetryGuard() {}

    /**
     * 다시 시도가 실패했을 때 남길 사유. 처음 실패 사유를 뒤에 붙인다.
     * 여러 번 다시 시도해도 맨 처음 원인 하나만 남긴다.
     */
    static String failureReason(String reason, String earlier) {
        if (earlier == null || earlier.isBlank()) return reason;
        int i = earlier.indexOf(FIRST);
        String first = i < 0 ? earlier : earlier.substring(i + FIRST.length(), earlier.length() - (earlier.endsWith(")") ? 1 : 0));
        return reason + " " + FIRST + first + ")";
    }

    /** 거절 사유. 비어 있으면 받아도 된다. */
    static Optional<String> problem(TaskStatus status, OffsetDateTime updatedAt, int quietSeconds, OffsetDateTime now) {
        if (!status.canRetry()) {
            return Optional.of("다시 시도할 수 없는 상태입니다 (" + status + "): "
                    + (status.isTerminal() ? "끝난 작업입니다. 새로 올려 주세요" : "승인을 기다리는 작업입니다. 확인 화면에서 결정해 주세요"));
        }
        if (status == TaskStatus.FAILED || quietSeconds <= 0 || updatedAt == null) return Optional.empty();
        long quietFor = Duration.between(updatedAt, now).getSeconds();
        if (quietFor >= quietSeconds) return Optional.empty();
        return Optional.of("아직 진행 중일 수 있습니다. 마지막 변화 뒤 " + quietSeconds + "초가 지나야 다시 시도할 수 있습니다 ("
                + (quietSeconds - quietFor) + "초 남음)");
    }
}
