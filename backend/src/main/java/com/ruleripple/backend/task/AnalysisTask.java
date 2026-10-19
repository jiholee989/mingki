package com.ruleripple.backend.task;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

import java.time.OffsetDateTime;
import java.util.Map;
import java.util.UUID;

@Entity
@Table(name = "analysis_tasks")
@Getter
@Setter
@NoArgsConstructor
public class AnalysisTask {

    @Id
    private UUID id;

    @Column(name = "requester_id", nullable = false)
    private Long requesterId;

    @Column(nullable = false, length = 200)
    private String title;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 40)
    private TaskStatus status;

    @Column(name = "current_node", length = 64)
    private String currentNode;

    @Column(name = "verify_round", nullable = false)
    private int verifyRound;

    @Column(name = "thread_id", nullable = false, length = 128)
    private String threadId;

    @Column(name = "error_message", columnDefinition = "text")
    private String errorMessage;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(columnDefinition = "jsonb")
    private Map<String, Object> report;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(columnDefinition = "jsonb")
    private Map<String, Object> evaluation;

    @Column(name = "created_at", nullable = false, insertable = false, updatable = false)
    private OffsetDateTime createdAt;

    @Column(name = "updated_at", nullable = false)
    private OffsetDateTime updatedAt = OffsetDateTime.now();

    @PreUpdate
    void touch() {
        this.updatedAt = OffsetDateTime.now();
    }

    public static AnalysisTask create(Long requesterId, String title) {
        AnalysisTask t = new AnalysisTask();
        t.id = UUID.randomUUID();
        t.threadId = t.id.toString();
        t.requesterId = requesterId;
        t.title = title;
        t.status = TaskStatus.EXTRACTING;
        t.currentNode = "requirement_agent";
        return t;
    }
}
