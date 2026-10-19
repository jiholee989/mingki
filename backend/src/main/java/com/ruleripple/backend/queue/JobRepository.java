package com.ruleripple.backend.queue;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

public interface JobRepository extends JpaRepository<Job, UUID> {
    List<Job> findByTaskIdOrderByCreatedAtAsc(UUID taskId);

    Optional<Job> findByIdempotencyKey(String idempotencyKey);
}
