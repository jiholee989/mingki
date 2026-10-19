package com.ruleripple.backend.task;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.UUID;

public interface TaskArtifactRepository extends JpaRepository<TaskArtifact, Long> {
    List<TaskArtifact> findByTaskIdOrderByIdAsc(UUID taskId);
}
