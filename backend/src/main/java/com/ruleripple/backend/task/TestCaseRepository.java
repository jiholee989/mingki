package com.ruleripple.backend.task;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.UUID;

public interface TestCaseRepository extends JpaRepository<TestCase, Long> {
    List<TestCase> findByTaskIdOrderByIdAsc(UUID taskId);

    boolean existsByTaskId(UUID taskId);
}
