package com.ruleripple.backend.task;

import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/** 공개 API 응답 형태. 프론트 src/api/mappers.ts 가 이 모양을 도메인 타입으로 바꾼다. */
public final class TaskDtos {
    private TaskDtos() {}

    public static final int MAX_VERIFY_ROUNDS = 2;

    public record TaskSummary(UUID id, String title, String status, String currentNode, int verifyRound,
                              Long requesterId, OffsetDateTime createdAt, OffsetDateTime updatedAt) {
        public static TaskSummary of(AnalysisTask t) {
            return new TaskSummary(t.getId(), t.getTitle(), t.getStatus().name(), t.getCurrentNode(),
                    t.getVerifyRound(), t.getRequesterId(), t.getCreatedAt(), t.getUpdatedAt());
        }
    }

    public record DocumentMeta(String side, String versionLabel, String filename, String sha256) {
        public static DocumentMeta of(RegulationDocument d) {
            return new DocumentMeta(d.getSide().name(), d.getVersionLabel(), d.getFilename(), d.getSha256());
        }
    }

    /** 지금 사람이 해야 할 일. 없으면 null. */
    public record PendingAction(String step, String role, String path) {
        public static PendingAction of(TaskStatus s, UUID id) {
            return switch (s) {
                case WAITING_REQUIREMENT_APPROVAL -> new PendingAction("REQUIREMENTS", "OFFICER", "/tasks/" + id + "/requirements");
                case WAITING_REVIEW -> new PendingAction("REVIEW", "DEVELOPER", "/tasks/" + id + "/review");
                default -> null;
            };
        }
    }

    public record Counts(int requirements, int targets, int nonTargets, int patches, int testCases) {}

    public record TaskDetail(TaskSummary task, String errorMessage, int maxVerifyRounds,
                             List<DocumentMeta> documents, PendingAction pendingAction, Counts counts,
                             List<ApprovalView> approvals, List<DeliveryView> deliveries) {}

    public record RequirementView(Long id, String reqKey, String summary, String target, LocalDate effectiveDate,
                                  String transitional, String articleRef, String oldText, String newText,
                                  String status, Map<String, Object> detail) {
        public static RequirementView of(Requirement r) {
            return new RequirementView(r.getId(), r.getReqKey(), r.getSummary(), r.getTarget(), r.getEffectiveDate(),
                    r.getTransitional(), r.getArticleRef(), r.getOldText(), r.getNewText(), r.getStatus().name(), r.getDetail());
        }
    }

    public record RequirementsResponse(TaskSummary task, List<DocumentMeta> documents, List<RequirementView> requirements) {}

    public record ChangeSpecView(Long id, String specKey, String reqKey, String locationKind, String filePath,
                                 String symbol, Integer lineNo, String snippet, String changeType, boolean target,
                                 String reason, String bundle, Map<String, Object> detail) {
        public static ChangeSpecView of(ChangeSpec c) {
            return new ChangeSpecView(c.getId(), c.getSpecKey(), c.getReqKey(), c.getLocationKind().name(),
                    c.getFilePath(), c.getSymbol(), c.getLineNo(), c.getSnippet(),
                    c.getChangeType() == null ? null : c.getChangeType().name(), c.isTarget(), c.getReason(),
                    c.getBundle(), c.getDetail());
        }
    }

    public record ChangeSpecsResponse(TaskSummary task, List<ChangeSpecView> targets, List<ChangeSpecView> nonTargets) {}

    public record PatchView(Long id, String bundle, int round, List<String> specKeys, String filePath, String diff,
                            String verifyStatus, String verifyLog, String failureKind, boolean latest,
                            Map<String, Object> detail) {
        public static PatchView of(CodePatch p, boolean latest) {
            return new PatchView(p.getId(), p.getBundle(), p.getRound(), p.getSpecKeys(), p.getFilePath(), p.getDiff(),
                    p.getVerifyStatus().name(), p.getVerifyLog(),
                    p.getFailureKind() == null ? null : p.getFailureKind().name(), latest, p.getDetail());
        }
    }

    public record TestCaseView(Long id, String testKey, String reqKey, String name, String kind, String code,
                               Map<String, Object> detail) {
        public static TestCaseView of(TestCase t) {
            return new TestCaseView(t.getId(), t.getTestKey(), t.getReqKey(), t.getName(), t.getKind().name(),
                    t.getCode(), t.getDetail());
        }
    }

    /** canApprove=false 면 화면에서도 승인 버튼을 막는다 (서버도 409 로 막음). */
    public record PatchesResponse(TaskSummary task, int maxVerifyRounds, int latestRound, int passed, int failed,
                                  int pending, boolean canApprove, List<PatchView> patches, List<TestCaseView> testCases) {}

    public record ApprovalView(Long id, String step, String decision, Long approverId, String comment,
                               Map<String, Object> payload, OffsetDateTime createdAt) {
        public static ApprovalView of(Approval a) {
            return new ApprovalView(a.getId(), a.getStep().name(), a.getDecision().name(), a.getApproverId(),
                    a.getComment(), a.getPayload(), a.getCreatedAt());
        }
    }

    public record DeliveryView(Long id, String kind, String externalRef, String url, Long approvalId, OffsetDateTime createdAt) {
        public static DeliveryView of(Delivery d) {
            return new DeliveryView(d.getId(), d.getKind().name(), d.getExternalRef(), d.getUrl(), d.getApprovalId(), d.getCreatedAt());
        }
    }

    public record ReportResponse(TaskSummary task, Map<String, Object> report, List<DeliveryView> deliveries) {}

    public record EvaluationResponse(TaskSummary task, Map<String, Object> evaluation) {}

    public record EventView(int seq, String type, Map<String, Object> payload, OffsetDateTime createdAt) {
        public static EventView of(TaskEvent e) {
            return new EventView(e.getSeq(), e.getType(), e.getPayload(), e.getCreatedAt());
        }
    }
}
