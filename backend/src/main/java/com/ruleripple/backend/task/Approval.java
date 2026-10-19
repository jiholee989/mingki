package com.ruleripple.backend.task;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

import java.time.OffsetDateTime;
import java.util.Map;
import java.util.UUID;

@Entity
@Table(name = "approvals")
@Getter
@NoArgsConstructor
public class Approval {

    public enum Step { REVIEW, PUBLISH }
    public enum Decision { APPROVE, REJECT }

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "task_id", nullable = false)
    private UUID taskId;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 16)
    private Step step;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 16)
    private Decision decision;

    @Column(name = "approver_id", nullable = false)
    private Long approverId;

    @Column(columnDefinition = "text")
    private String comment;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(columnDefinition = "jsonb")
    private Map<String, Object> payload;

    @Column(name = "created_at", nullable = false, insertable = false, updatable = false)
    private OffsetDateTime createdAt;

    public Approval(UUID taskId, Step step, Decision decision, Long approverId, String comment, Map<String, Object> payload) {
        this.taskId = taskId;
        this.step = step;
        this.decision = decision;
        this.approverId = approverId;
        this.comment = comment;
        this.payload = payload;
    }
}
