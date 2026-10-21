package com.ruleripple.backend.internal;

import com.ruleripple.backend.queue.Job;
import com.ruleripple.backend.queue.JobPublisher;
import com.ruleripple.backend.queue.JobRepository;
import com.ruleripple.backend.task.DeliveryRepository;
import com.ruleripple.backend.task.RuleProposal;
import com.ruleripple.backend.task.RuleProposalRepository;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.web.server.ResponseStatusException;

import java.time.LocalDate;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.contains;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.*;

/** 반영 접수의 멱등키 검증과 워커 반영의 완료 저장 (docs/BACKEND_API.md 10.4). DB 없이 저장소 · JDBC 를 대역으로 둔다. */
class RuleVersionServiceTest {

    private final UUID task = UUID.randomUUID();
    private final RuleProposalRepository proposals = mock(RuleProposalRepository.class);
    private final JobRepository jobs = mock(JobRepository.class);
    private final JobPublisher publisher = mock(JobPublisher.class);
    private final JdbcTemplate jdbc = mock(JdbcTemplate.class);
    private final RuleVersionService service = new RuleVersionService(mock(ApprovalGuard.class), proposals, jobs,
            publisher, mock(DeliveryRepository.class), jdbc);

    @Test
    void duplicateIdempotencyKeyMustBelongToTheSameTaskApprovalAndProposal() {
        Job existing = Job.create(task, Job.Type.APPLY_RULE_VERSION, Map.of("proposalKey", "P001:DSR_LIMIT", "proposalId", 1), 7L, "retry-1");
        when(jobs.findByIdempotencyKey("retry-1")).thenReturn(Optional.of(existing));

        assertThatThrownBy(() -> service.enqueue(new RuleVersionService.ApplyRequest(task, 7L, "P002:DSR_LIMIT", "retry-1")))
                .isInstanceOf(ResponseStatusException.class).hasMessageContaining("다른 제안");
        assertThatThrownBy(() -> service.enqueue(new RuleVersionService.ApplyRequest(task, 8L, "P001:DSR_LIMIT", "retry-1")))
                .isInstanceOf(ResponseStatusException.class).hasMessageContaining("다른 제안");
        assertThatThrownBy(() -> service.enqueue(new RuleVersionService.ApplyRequest(UUID.randomUUID(), 7L, "P001:DSR_LIMIT", "retry-1")))
                .isInstanceOf(ResponseStatusException.class).hasMessageContaining("다른 제안");

        JobPublisher.Enqueued same = service.enqueue(new RuleVersionService.ApplyRequest(task, 7L, "P001:DSR_LIMIT", "retry-1"));
        assertThat(same.duplicate()).isTrue();
        assertThat(same.jobId()).isEqualTo(existing.getId());
        verify(publisher, never()).publish(any(), any(), any(), any(), any());
    }

    @Test
    @SuppressWarnings("unchecked")
    void applyMarksTheJobDoneInsideTheSameTransaction() {
        Job job = Job.create(task, Job.Type.APPLY_RULE_VERSION, Map.of("proposalKey", "P001:DSR_LIMIT", "proposalId", 1), 7L, "k");
        RuleProposal p = new RuleProposal();
        p.setId(1L);
        p.setTaskId(task);
        p.setProposalKey("P001:DSR_LIMIT");
        p.setProductId("P001");
        p.setRuleId("R001");
        p.setRuleKey("DSR_LIMIT");
        p.setCurrentValue("0.40");
        p.setProposedValue("0.35");
        p.setUnit("ratio");
        p.setEffectiveDate(LocalDate.of(2026, 12, 1));
        when(proposals.findById(1L)).thenReturn(Optional.of(p));
        when(jdbc.query(anyString(), any(RowMapper.class), any(), any()))
                .thenReturn(List.of(new RuleVersions.Row("R001", "0.40", LocalDate.of(2024, 1, 1), null)));
        when(jdbc.queryForList(anyString(), eq(String.class))).thenReturn(List.of("R001", "R082"));

        Map<String, Object> result = service.apply(job);

        assertThat(result).containsEntry("closedRuleId", "R001").containsEntry("newRuleId", "R083")
                .containsEntry("effectiveFrom", "2026-12-01");
        // 워커가 따로 저장하기 전에 이미 DONE 이다. 그 사이에 죽어도 다시 반영하지 않는다.
        assertThat(job.getStatus()).isEqualTo(Job.Status.DONE);
        assertThat(job.getResult()).isEqualTo(result);
        assertThat(job.getLastError()).isNull();
        verify(jobs).save(job);
        // 새 행은 기존 행(R001)의 근거 조항을 이어받는다. 이어받을 행이 없을 때만 제안 basis 를 쓴다
        verify(jdbc).update(contains("coalesce((select basis_articles from product_rules where rule_id = ?), ?::jsonb)"),
                eq("R083"), eq("P001"), eq("DSR_LIMIT"), eq("0.35"), eq("ratio"), eq(LocalDate.of(2026, 12, 1)),
                eq("R001"), eq("[]"));
    }
}
