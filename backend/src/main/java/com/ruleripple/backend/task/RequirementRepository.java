package com.ruleripple.backend.task;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

public interface RequirementRepository extends JpaRepository<Requirement, Long> {
    List<Requirement> findByTaskIdOrderByIdAsc(UUID taskId);

    Optional<Requirement> findByTaskIdAndReqKey(UUID taskId, String reqKey);
}
