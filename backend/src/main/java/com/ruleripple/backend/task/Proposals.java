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

    /** 제안 키마다 가장 높은 회차. 키 순서. */
    public static List<RuleProposal> latest(List<RuleProposal> all) {
        Map<String, RuleProposal> byKey = new TreeMap<>();
        for (RuleProposal p : all) byKey.merge(p.getProposalKey(), p, (a, b) -> a.getRound() >= b.getRound() ? a : b);
        return List.copyOf(byKey.values());
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

    private static boolean blank(String s) {
        return s == null || s.isBlank();
    }
}
