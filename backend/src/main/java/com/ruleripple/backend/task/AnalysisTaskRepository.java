package com.ruleripple.backend.task;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.UUID;

public interface AnalysisTaskRepository extends JpaRepository<AnalysisTask, UUID> {
    List<AnalysisTask> findByRequesterIdOrderByCreatedAtDesc(Long requesterId);
    List<AnalysisTask> findAllByOrderByCreatedAtDesc();
}
