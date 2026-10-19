package com.ruleripple.backend.task;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.UUID;

public interface RegulationDocumentRepository extends JpaRepository<RegulationDocument, Long> {
    List<RegulationDocument> findByTaskIdOrderBySideAsc(UUID taskId);
}
