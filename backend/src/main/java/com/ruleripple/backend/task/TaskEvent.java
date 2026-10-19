package com.ruleripple.backend.task;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

import java.time.OffsetDateTime;
import java.util.Map;
import java.util.UUID;

/**
 * Agent 가 보내는 진행 이벤트. SSE 로 중계되고, 재접속 시 seq 로 재생된다.
 * type: TOKEN | TOOL_START | TOOL_END | STEP | APPROVAL_REQUIRED | RESUMED | DONE | FAILED
 */
@Entity
@Table(name = "task_events")
@Getter
@NoArgsConstructor
public class TaskEvent {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "task_id", nullable = false)
    private UUID taskId;

    @Column(nullable = false)
    private int seq;

    @Column(nullable = false, length = 32)
    private String type;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(nullable = false, columnDefinition = "jsonb")
    private Map<String, Object> payload;

    @Column(name = "created_at", nullable = false, insertable = false, updatable = false)
    private OffsetDateTime createdAt;

    public TaskEvent(UUID taskId, int seq, String type, Map<String, Object> payload) {
        this.taskId = taskId;
        this.seq = seq;
        this.type = type;
        this.payload = payload == null ? Map.<String, Object>of() : payload;
    }
}
