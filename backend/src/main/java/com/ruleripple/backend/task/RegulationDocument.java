package com.ruleripple.backend.task;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;
import java.util.UUID;

/** 업로드한 규정 원문. side = OLD(v3) | NEW(v4). */
@Entity
@Table(name = "regulation_documents")
@Getter
@NoArgsConstructor
public class RegulationDocument {

    public enum Side { OLD, NEW }

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "task_id", nullable = false)
    private UUID taskId;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 8)
    private Side side;

    @Column(name = "version_label", nullable = false, length = 32)
    private String versionLabel;

    @Column(nullable = false)
    private String filename;

    @Column(nullable = false, columnDefinition = "text")
    private String content;

    @Column(nullable = false, length = 64)
    private String sha256;

    @Column(name = "created_at", nullable = false, insertable = false, updatable = false)
    private OffsetDateTime createdAt;

    public RegulationDocument(UUID taskId, Side side, String versionLabel, String filename, String content, String sha256) {
        this.taskId = taskId;
        this.side = side;
        this.versionLabel = versionLabel;
        this.filename = filename;
        this.content = content;
        this.sha256 = sha256;
    }
}
