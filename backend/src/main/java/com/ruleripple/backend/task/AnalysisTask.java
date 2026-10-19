package com.ruleripple.backend.task;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.time.OffsetDateTime;
import java.util.UUID;

@Entity
@Table(name = "analysis_tasks")
@Getter
@Setter
@NoArgsConstructor
public class AnalysisTask {

    public enum Status { QUEUED, RUNNING, WAITING_REVIEW, WAITING_PUBLISH, PUBLISHING, DONE, FAILED, REJECTED }

    @Id
    private UUID id;

    @Column(name = "requester_id", nullable = false)
    private Long requesterId;

    @Column(name = "regulation_id", nullable = false, length = 64)
    private String regulationId;

    @Column(name = "old_version", nullable = false, length = 32)
    private String oldVersion;

    @Column(name = "new_version", nullable = false, length = 32)
    private String newVersion;

    @Column(columnDefinition = "text")
    private String question;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 32)
    private Status status;

    @Column(name = "thread_id", length = 128)
    private String threadId;

    @Column(name = "current_step", length = 64)
    private String currentStep;

    @Column(name = "error_message", columnDefinition = "text")
    private String errorMessage;

    @Column(name = "created_at", nullable = false, insertable = false, updatable = false)
    private OffsetDateTime createdAt;

    @Column(name = "updated_at", nullable = false)
    private OffsetDateTime updatedAt = OffsetDateTime.now();

    @PreUpdate
    void touch() {
        this.updatedAt = OffsetDateTime.now();
    }

    public static AnalysisTask create(Long requesterId, String regulationId, String oldVersion, String newVersion, String question) {
        AnalysisTask t = new AnalysisTask();
        t.id = UUID.randomUUID();
        t.threadId = t.id.toString();
        t.requesterId = requesterId;
        t.regulationId = regulationId;
        t.oldVersion = oldVersion;
        t.newVersion = newVersion;
        t.question = question;
        t.status = Status.QUEUED;
        t.currentStep = "queued";
        return t;
    }
}
