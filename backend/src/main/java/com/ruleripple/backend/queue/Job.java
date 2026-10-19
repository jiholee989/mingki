package com.ruleripple.backend.queue;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

import java.time.OffsetDateTime;
import java.util.Map;
import java.util.UUID;

/**
 * 대기열 작업 이력. type: CHECK_PATCH | CREATE_DRAFT_PR | CREATE_TICKET
 * status: QUEUED → RUNNING → DONE | RETRYING → ... | DEAD
 */
@Entity
@Table(name = "jobs")
@Getter
@Setter
@NoArgsConstructor
public class Job {

    public enum Status { QUEUED, RUNNING, RETRYING, DONE, DEAD }

    @Id
    private UUID id;

    @Column(name = "task_id")
    private UUID taskId;

    @Column(nullable = false, length = 32)
    private String type;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(nullable = false, columnDefinition = "jsonb")
    private Map<String, Object> payload;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 16)
    private Status status;

    @Column(nullable = false)
    private int attempts;

    @Column(name = "last_error", columnDefinition = "text")
    private String lastError;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(columnDefinition = "jsonb")
    private Map<String, Object> result;

    @Column(name = "created_at", nullable = false, insertable = false, updatable = false)
    private OffsetDateTime createdAt;

    @Column(name = "updated_at", nullable = false)
    private OffsetDateTime updatedAt = OffsetDateTime.now();

    @PreUpdate
    void touch() { this.updatedAt = OffsetDateTime.now(); }

    public static Job create(UUID taskId, String type, Map<String, Object> payload) {
        Job j = new Job();
        j.id = UUID.randomUUID();
        j.taskId = taskId;
        j.type = type;
        j.payload = payload == null ? Map.<String, Object>of() : payload;
        j.status = Status.QUEUED;
        return j;
    }
}
