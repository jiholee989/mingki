package com.ruleripple.backend.task;

import java.util.Set;

/** 작업 상태. docs/BACKEND_API.md 10.1 의 노드 → 상태 표와 같다. */
public enum TaskStatus {
    EXTRACTING,      // 바뀐 조항에서 요건 추출 중
    LOCATING,        // 상품별 영향 판단 중
    DESIGNING,       // 상품별 변경 제안 작성 중
    VERIFYING,       // 근거 검사 중 (verify_round 회차)
    WAITING_REVIEW,  // 사람 확인 대기
    PUBLISHING,      // 상품 규칙 반영 중
    DONE,            // 반영 완료
    NO_CHANGE,       // 바꿀 상품 없음
    REJECTED,        // 거절로 종료
    FAILED;          // 시스템 오류

    private static final Set<TaskStatus> TERMINAL = Set.of(DONE, NO_CHANGE, REJECTED, FAILED);

    public boolean isTerminal() {
        return TERMINAL.contains(this);
    }

    /**
     * "다시 시도"할 수 있는 상태. 진행 중(Agent 가 도중에 죽음)과 FAILED(Agent 호출 실패)다.
     * 승인 대기는 확인 API 로 풀고, 정상 종료는 다시 하지 않는다.
     */
    public boolean canRetry() {
        return this == FAILED || (!isTerminal() && !isWaiting());
    }

    public boolean isWaiting() {
        return this == WAITING_REVIEW;
    }

    /**
     * Agent 이벤트로 옮길 수 있는 다음 상태. 같은 상태는 언제나 허용한다.
     * WAITING_REVIEW 에서 나가는 전이는 사람이 확인 API 로만 한다. FAILED 도 예외가 아니다. 확인 대기 중인 Agent 는
     * 아무것도 실행하지 않으므로, 그때 오는 FAILED 는 엉뚱한 요청(예: 실행 중에 누른 "다시 시도")의 뒷처리다.
     */
    public boolean agentCanMoveTo(TaskStatus next) {
        if (next == this) return true;
        if (isTerminal() || isWaiting()) return false;
        if (next == FAILED) return true;
        return switch (this) {
            case EXTRACTING -> next == LOCATING || next == NO_CHANGE;   // 요건 0건이면 바로 변경 없음
            case LOCATING -> next == DESIGNING || next == NO_CHANGE;     // 전 상품 유지
            case DESIGNING -> next == VERIFYING;
            case VERIFYING -> next == DESIGNING || next == WAITING_REVIEW;
            case PUBLISHING -> next == DONE;
            default -> false;
        };
    }

    /**
     * FAILED 작업을 "다시 시도"할 때 되돌릴 상태. 승인 뒤면 반영 중, 확인 대기에서 멈췄으면 확인 대기로 돌아간다
     * (Agent 는 그대로 기다리고 있으니 사람이 결정만 하면 된다). 그 밖에는 마지막 노드의 상태, 모르면 처음부터.
     */
    public static TaskStatus restoredAfterFailure(String currentNode, boolean approved) {
        if (approved) return PUBLISHING;
        if ("interrupt_review".equals(currentNode)) return WAITING_REVIEW;
        TaskStatus fromNode = fromNode(currentNode);
        return fromNode == null ? EXTRACTING : fromNode;
    }

    /** Agent 가 보내는 노드 이름 → 진행 상태. 모르는 노드면 null (상태 유지). */
    public static TaskStatus fromNode(String node) {
        if (node == null) return null;
        return switch (node) {
            case "requirement_agent" -> EXTRACTING;
            case "impact_agent", "product_impact_agent" -> LOCATING;
            case "proposal_agent" -> DESIGNING;
            case "verify" -> VERIFYING;
            case "apply" -> PUBLISHING;
            default -> null;
        };
    }
}
