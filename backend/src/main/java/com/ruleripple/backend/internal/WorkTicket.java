package com.ruleripple.backend.internal;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.time.OffsetDateTime;
import java.util.UUID;

/** create_work_ticket 결과. Jira 대신 사내 작업 티켓으로 둔다. */
@Entity
@Table(name = "work_tickets")
@Getter
@Setter
@NoArgsConstructor
public class WorkTicket {

    public enum Type { CODE, CONFIG, DB, DOC, TEST }

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "task_id")
    private UUID taskId;

    @Column(nullable = false)
    private String title;

    @Column(columnDefinition = "text")
    private String description;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 16)
    private Type type;

    @Column(name = "target_ref")
    private String targetRef;

    @Column(length = 64)
    private String assignee;

    @Column(nullable = false, length = 16)
    private String status = "OPEN";

    @Column(name = "approval_id")
    private Long approvalId;

    @Column(name = "created_by", nullable = false, length = 64)
    private String createdBy;

    @Column(name = "created_at", nullable = false, insertable = false, updatable = false)
    private OffsetDateTime createdAt;
}
