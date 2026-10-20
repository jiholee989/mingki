package com.ruleripple.backend.task;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

public interface RuleProposalRepository extends JpaRepository<RuleProposal, Long> {
    List<RuleProposal> findByTaskIdOrderByProposalKeyAscRoundAsc(UUID taskId);

    Optional<RuleProposal> findByTaskIdAndProposalKeyAndRound(UUID taskId, String proposalKey, int round);

    boolean existsByTaskId(UUID taskId);
}
