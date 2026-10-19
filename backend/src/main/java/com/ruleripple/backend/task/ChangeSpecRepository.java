package com.ruleripple.backend.task;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

public interface ChangeSpecRepository extends JpaRepository<ChangeSpec, Long> {
    List<ChangeSpec> findByTaskIdOrderByIdAsc(UUID taskId);

    Optional<ChangeSpec> findByTaskIdAndSpecKey(UUID taskId, String specKey);
}
