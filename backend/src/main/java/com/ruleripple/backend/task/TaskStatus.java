package com.ruleripple.backend.task;

import java.util.Set;

/** docs/FRONTEND_PLAN.md "작업 상태" 와 1:1. */
public enum TaskStatus {
    EXTRACTING,                    // 요건 추출 중
    WAITING_REQUIREMENT_APPROVAL,  // interrupt ① 요건 확정 대기 (OFFICER)
    LOCATING,                      // 영향 위치 탐색 · 테스트 생성 중
    DESIGNING,                     // 수정안 생성 중
    VERIFYING,                     // 검증 중 (verify_round 회차)
    WAITING_REVIEW,                // interrupt ② 검토 · 승인 대기 (DEVELOPER)
    PUBLISHING,                    // PR · 티켓 생성 중
    DONE,                          // 완료
    NO_CHANGE,                     // 실질 변경 없음
    HELD,                          // 전부 보류로 종료
    REJECTED,                      // 거절로 종료
    FAILED;                        // 시스템 오류

    private static final Set<TaskStatus> TERMINAL = Set.of(DONE, NO_CHANGE, HELD, REJECTED, FAILED);

    public boolean isTerminal() {
        return TERMINAL.contains(this);
    }

    /** Agent 가 보내는 노드 이름 → 진행 상태. 모르는 노드면 null (상태 유지). */
    public static TaskStatus fromNode(String node) {
        if (node == null) return null;
        return switch (node) {
            case "requirement_agent" -> EXTRACTING;
            case "test_agent", "locate_agent" -> LOCATING;
            case "design_agent", "plan", "db_change", "worker", "merge" -> DESIGNING;
            case "verify" -> VERIFYING;
            case "publish" -> PUBLISHING;
            default -> null;
        };
    }
}
