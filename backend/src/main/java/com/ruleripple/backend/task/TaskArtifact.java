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
 * Agent 산출물. kind: REQUIREMENTS | CHANGE_SPEC | CODE_PATCH | DB_MIGRATION | TEST_CASE | VERIFY_RESULT | REPORT
 */
@Entity
@Table(name = "task_artifacts")
@Getter
@NoArgsConstructor
public class TaskArtifact {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "task_id", nullable = false)
    private UUID taskId;

    @Column(nullable = false, length = 32)
    private String kind;

    @Column(nullable = false)
    private int round;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(nullable = false, columnDefinition = "jsonb")
    private Map<String, Object> payload;

    @Column(name = "created_at", nullable = false, insertable = false, updatable = false)
    private OffsetDateTime createdAt;

    public TaskArtifact(UUID taskId, String kind, int round, Map<String, Object> payload) {
        this.taskId = taskId;
        this.kind = kind;
        this.round = round;
        this.payload = payload;
    }
}
