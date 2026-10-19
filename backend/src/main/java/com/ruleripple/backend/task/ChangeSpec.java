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

/** locate_agent 결과. 대상이 아닌 위치(isTarget=false)도 이유와 함께 남긴다. */
@Entity
@Table(name = "change_specs")
@Getter
@Setter
@NoArgsConstructor
public class ChangeSpec {

    public enum LocationKind { CODE, CONFIG, DB, PRODUCT, DOC, UI }

    /** ① 값 · ② 로직 · ③ DB · ④ 신규. 대상 아님이면 null. */
    public enum ChangeType { VALUE, LOGIC, DB, NEW }

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "task_id", nullable = false)
    private UUID taskId;

    @Column(name = "spec_key", nullable = false, length = 32)
    private String specKey;

    @Column(name = "req_key", nullable = false, length = 32)
    private String reqKey;

    @Enumerated(EnumType.STRING)
    @Column(name = "location_kind", nullable = false, length = 16)
    private LocationKind locationKind;

    @Column(name = "file_path")
    private String filePath;

    @Column
    private String symbol;

    @Column(name = "line_no")
    private Integer lineNo;

    @Column(columnDefinition = "text")
    private String snippet;

    @Enumerated(EnumType.STRING)
    @Column(name = "change_type", length = 16)
    private ChangeType changeType;

    @Column(name = "is_target", nullable = false)
    private boolean target;

    @Column(nullable = false, columnDefinition = "text")
    private String reason;

    @Column(length = 64)
    private String bundle;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(nullable = false, columnDefinition = "jsonb")
    private Map<String, Object> detail = Map.of();

    @Column(name = "created_at", nullable = false, insertable = false, updatable = false)
    private OffsetDateTime createdAt;
}
