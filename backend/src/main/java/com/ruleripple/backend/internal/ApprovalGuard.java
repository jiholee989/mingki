package com.ruleripple.backend.internal;

import com.ruleripple.backend.task.*;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

import java.util.UUID;

/**
 * 반영 요청(apply_rule_version)의 승인 기록 검증.
 * 그래프의 interrupt 만 믿지 않고, 호출마다 approvalId 가 유효한지 다시 확인한다.
 * 그 제안이 반영으로 골라졌는지는 RuleVersionService 가 확인한다.
 *
 * 통과 조건
 *  1. approval 이 존재하고 같은 작업의 것
 *  2. step = REVIEW, decision = APPROVE
 *  3. 그 작업의 가장 최근 확인 결정
 *  4. 작업 상태 = PUBLISHING
 */
@Component
public class ApprovalGuard {

    private final ApprovalRepository approvals;
    private final AnalysisTaskRepository tasks;

    public ApprovalGuard(ApprovalRepository approvals, AnalysisTaskRepository tasks) {
        this.approvals = approvals;
        this.tasks = tasks;
    }

    @Transactional(readOnly = true)
    public Approval check(UUID taskId, Long approvalId) {
        if (taskId == null || approvalId == null) throw forbidden("taskId 와 approvalId 가 필요합니다");
        Approval a = approvals.findById(approvalId).orElseThrow(() -> forbidden("존재하지 않는 approvalId: " + approvalId));
        if (!a.getTaskId().equals(taskId)) throw forbidden("다른 작업의 승인입니다");
        if (a.getStep() != Approval.Step.REVIEW || a.getDecision() != Approval.Decision.APPROVE) {
            throw forbidden("확인 · 승인(REVIEW/APPROVE) 기록이 아닙니다");
        }
        Approval latestReview = approvals.findByTaskIdOrderByIdAsc(taskId).stream()
                .filter(x -> x.getStep() == Approval.Step.REVIEW)
                .reduce((first, second) -> second)
                .orElseThrow();
        if (!latestReview.getId().equals(a.getId())) throw forbidden("이후 결정으로 무효가 된 승인입니다");

        AnalysisTask task = tasks.findById(taskId).orElseThrow(() -> forbidden("task not found"));
        if (task.getStatus() != TaskStatus.PUBLISHING) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "작업 상태가 PUBLISHING 이 아닙니다 (현재 " + task.getStatus() + ")");
        }
        return a;
    }

    private static ResponseStatusException forbidden(String m) {
        return new ResponseStatusException(HttpStatus.FORBIDDEN, m);
    }
}
