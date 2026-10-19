package com.ruleripple.backend.task;

import jakarta.persistence.LockModeType;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

public interface AnalysisTaskRepository extends JpaRepository<AnalysisTask, UUID> {
    List<AnalysisTask> findByRequesterIdOrderByCreatedAtDesc(Long requesterId);

    List<AnalysisTask> findAllByOrderByCreatedAtDesc();

    /** 이벤트 seq 채번·상태 전이를 직렬화하기 위한 행 잠금 (Agent 콜백과 큐 워커가 동시에 쓴다). */
    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select t from AnalysisTask t where t.id = :id")
    Optional<AnalysisTask> findForUpdate(@Param("id") UUID id);
}
