package com.ruleripple.backend.task;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.Map;
import java.util.UUID;

/** requirement_agent 결과. 바뀐 조항에서 뽑은 요건 하나. */
@Entity
@Table(name = "requirements")
@Getter
@Setter
@NoArgsConstructor
public class Requirement {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "task_id", nullable = false)
    private UUID taskId;

    @Column(name = "req_key", nullable = false, length = 32)
    private String reqKey;

    @Column(nullable = false, columnDefinition = "text")
    private String summary;

    @Column(columnDefinition = "text")
    private String target;

    @Column(name = "effective_date")
    private LocalDate effectiveDate;

    @Column(columnDefinition = "text")
    private String transitional;

    @Column(name = "article_ref", length = 64)
    private String articleRef;

    @Column(name = "old_text", columnDefinition = "text")
    private String oldText;

    @Column(name = "new_text", columnDefinition = "text")
    private String newText;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(nullable = false, columnDefinition = "jsonb")
    private Map<String, Object> detail = Map.of();

    @Column(name = "created_at", nullable = false, insertable = false, updatable = false)
    private OffsetDateTime createdAt;
}
