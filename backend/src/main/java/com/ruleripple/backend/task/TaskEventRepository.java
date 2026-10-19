package com.ruleripple.backend.task;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.List;
import java.util.UUID;

public interface TaskEventRepository extends JpaRepository<TaskEvent, Long> {
    List<TaskEvent> findByTaskIdAndSeqGreaterThanOrderBySeqAsc(UUID taskId, int afterSeq);

    @Query("select coalesce(max(e.seq), 0) from TaskEvent e where e.taskId = :taskId")
    int maxSeq(@Param("taskId") UUID taskId);
}
