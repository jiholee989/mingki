package com.ruleripple.backend.task;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/** design_agent 패치 + verify 결과. round 마다 새 행이라 회차별 이력이 남는다. */
@Entity
@Table(name = "code_patches")
@Getter
@Setter
@NoArgsConstructor
public class CodePatch {

    public enum VerifyStatus { PENDING, PASSED, FAILED }

    /** PATCH: 패치 적용·문법·단위 테스트 실패 → design 으로. SYSTEM_TEST: 놓친 위치 의심 → locate 로. */
    public enum FailureKind { PATCH, SYSTEM_TEST }

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "task_id", nullable = false)
    private UUID taskId;

    @Column(nullable = false, length = 64)
    private String bundle;

    @Column(nullable = false)
    private int round;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "spec_keys", nullable = false, columnDefinition = "jsonb")
    private List<String> specKeys = List.of();

    @Column(name = "file_path", nullable = false)
    private String filePath;

    @Column(nullable = false, columnDefinition = "text")
    private String diff;

    @Enumerated(EnumType.STRING)
    @Column(name = "verify_status", nullable = false, length = 16)
    private VerifyStatus verifyStatus = VerifyStatus.PENDING;

    @Column(name = "verify_log", columnDefinition = "text")
    private String verifyLog;

    @Enumerated(EnumType.STRING)
    @Column(name = "failure_kind", length = 16)
    private FailureKind failureKind;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(nullable = false, columnDefinition = "jsonb")
    private Map<String, Object> detail = Map.of();

    @Column(name = "created_at", nullable = false, insertable = false, updatable = false)
    private OffsetDateTime createdAt;
}
