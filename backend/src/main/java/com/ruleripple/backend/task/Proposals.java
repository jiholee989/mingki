package com.ruleripple.backend.task;

import java.time.LocalDate;
import java.util.*;

/**
 * 제안 규칙 (docs/BACKEND_API.md 10.2 · 10.3). 저장 · 확인 API 가 같은 판단을 쓰도록 한곳에 둔다.
 * DB 없이 테스트할 수 있게 행 목록만 받는다.
 */
public final class Proposals {

    private Proposals() {}

    public static final String CHANGE_REQUIRED = "change_required";
    public static final Set<String> IMPACTS = Set.of(CHANGE_REQUIRED, "keep", "needs_check");

    /** Agent 가 보내는 제안 1건. (proposalKey, round) 기준 upsert. */
    public record Item(String proposalKey, String reqKey, String productId, String ruleId, String ruleKey,
                       String impact, String current, String proposed, String unit,
                       String currentValue, String proposedValue, LocalDate effectiveDate,
                       String basis, String reason, String transition, List<String> followUp,
                       Integer round, RuleProposal.VerifyStatus verifyStatus, String verifyLog) {}

    /** 계약 10.2 필드 규칙. 어긋나면 이유를, 맞으면 null 을 돌려준다. */
    public static String invalid(Item i) {
        if (blank(i.proposalKey())) return "proposalKey 는 필수입니다";
        String key = i.proposalKey();
        if (i.round() == null || i.round() < 1) return key + ": round 는 1 이상입니다";
        if (blank(i.productId())) return key + ": productId 는 필수입니다";
        if (!IMPACTS.contains(i.impact())) return key + ": impact 는 change_required | keep | needs_check 입니다";
        if (blank(i.reason())) return key + ": reason 은 필수입니다";
        if (CHANGE_REQUIRED.equals(i.impact())) {
            if (blank(i.ruleKey()) || blank(i.unit()) || blank(i.proposedValue()) || i.effectiveDate() == null) {
                return key + ": change_required 는 ruleKey · unit · proposedValue · effectiveDate 가 필요합니다";
            }
            if (!blank(i.ruleId()) && blank(i.currentValue())) {
                return key + ": 기존 규칙 변경은 currentValue 가 필요합니다";
            }
        }
        return null;
    }

    /**
     * 현재 제안. Agent 제안 묶음(reqKey × productId)마다 가장 높은 회차의 행만 남긴다. 키 순서.
     * 재작성 회차에서 빠진 규칙 행은 이전 회차에 남지만 현재 제안이 아니다. 키마다 최고 회차를 고르면
     * 1회차에만 있던 FAILED 행이 계속 남아 canApprove 를 영원히 막는다.
     */
    public static List<RuleProposal> latest(List<RuleProposal> all) {
        Map<String, Integer> topRound = new HashMap<>();
        for (RuleProposal p : all) topRound.merge(bundle(p), p.getRound(), Math::max);
        Map<String, RuleProposal> byKey = new TreeMap<>();
        for (RuleProposal p : all) {
            if (p.getRound() == topRound.get(bundle(p))) byKey.put(p.getProposalKey(), p);
        }
        return List.copyOf(byKey.values());
    }

    private static String bundle(RuleProposal p) {
        return p.getReqKey() + "|" + p.getProductId();
    }

    public static List<String> changeKeys(List<RuleProposal> latest) {
        return latest.stream().filter(p -> CHANGE_REQUIRED.equals(p.getImpact())).map(RuleProposal::getProposalKey).toList();
    }

    /** 확인 대기 중이고, 반영할 제안이 1건 이상이며 모두 근거 검사를 통과했다. */
    public static boolean canApprove(TaskStatus status, List<RuleProposal> latest) {
        List<RuleProposal> change = latest.stream().filter(p -> CHANGE_REQUIRED.equals(p.getImpact())).toList();
        return status == TaskStatus.WAITING_REVIEW && !change.isEmpty()
                && change.stream().allMatch(p -> p.getVerifyStatus() == RuleProposal.VerifyStatus.PASSED);
    }

    /** 반려는 작업을 끝내므로 사유가 필수다. 사유는 리포트 응답의 review 에 나온다 (10.3). */
    public static boolean missingRejectReason(Approval.Decision decision, String comment) {
        return decision == Approval.Decision.REJECT && blank(comment);
    }

    private static boolean blank(String s) {
        return s == null || s.isBlank();
    }
}
