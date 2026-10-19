package com.ruleripple.backend.task;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

public interface CodePatchRepository extends JpaRepository<CodePatch, Long> {
    List<CodePatch> findByTaskIdOrderByRoundAscIdAsc(UUID taskId);

    Optional<CodePatch> findByTaskIdAndBundleAndRoundAndFilePath(UUID taskId, String bundle, int round, String filePath);
}
