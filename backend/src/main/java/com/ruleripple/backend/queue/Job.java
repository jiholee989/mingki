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
 * 대기열 작업. status: QUEUED → RUNNING → DONE | RETRYING → … | DEAD
 * 쓰기 작업(CREATE_DRAFT_PR, CREATE_TICKET)은 approvalId 와 idempotencyKey 가 필수다.
 */
@Entity
@Table(name = "jobs")
@Getter
@Setter
@NoArgsConstructor
public class Job {

    public enum Status { QUEUED, RUNNING, RETRYING, DONE, DEAD }

    public enum Type {
        CHECK_PATCH(false), CREATE_DRAFT_PR(true), CREATE_TICKET(true), APPLY_RULE_VERSION(true);

        private final boolean write;

        Type(boolean write) { this.write = write; }

        public boolean isWrite() { return write; }
    }

    @Id
    private UUID id;

    @Column(name = "task_id")
    private UUID taskId;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 32)
    private Type type;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(nullable = false, columnDefinition = "jsonb")
    private Map<String, Object> payload;

    @Column(name = "approval_id")
    private Long approvalId;

    @Column(name = "idempotency_key", length = 128, unique = true)
    private String idempotencyKey;

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

    public static Job create(UUID taskId, Type type, Map<String, Object> payload, Long approvalId, String idempotencyKey) {
        Job j = new Job();
        j.id = UUID.randomUUID();
        j.taskId = taskId;
        j.type = type;
        j.payload = payload == null ? Map.of() : payload;
        j.approvalId = approvalId;
        j.idempotencyKey = idempotencyKey;
        j.status = Status.QUEUED;
        return j;
    }
}
