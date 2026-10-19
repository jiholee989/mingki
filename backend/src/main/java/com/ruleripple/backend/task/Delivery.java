package com.ruleripple.backend.task;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;
import java.util.UUID;

/** Draft PR / 티켓 등 외부로 나간 결과 (시연에서는 목 링크). */
@Entity
@Table(name = "deliveries")
@Getter
@NoArgsConstructor
public class Delivery {

    public enum Kind { PR, TICKET }

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "task_id", nullable = false)
    private UUID taskId;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 16)
    private Kind kind;

    @Column(name = "external_ref", length = 128)
    private String externalRef;

    @Column(length = 512)
    private String url;

    @Column(nullable = false, length = 16)
    private String status = "CREATED";

    @Column(name = "created_at", nullable = false, insertable = false, updatable = false)
    private OffsetDateTime createdAt;

    public Delivery(UUID taskId, Kind kind, String externalRef, String url) {
        this.taskId = taskId;
        this.kind = kind;
        this.externalRef = externalRef;
        this.url = url;
    }
}
