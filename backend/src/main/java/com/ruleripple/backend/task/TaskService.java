package com.ruleripple.backend.task;

import com.ruleripple.backend.auth.AuthUser;
import com.ruleripple.backend.auth.User;
import com.ruleripple.backend.auth.UserRepository;
import com.ruleripple.backend.queue.Job;
import com.ruleripple.backend.queue.JobRepository;
import com.ruleripple.backend.task.TaskDtos.ApprovalView;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.server.ResponseStatusException;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.*;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** 공개 API 의 업무 로직: 작업 생성, 화면별 조회, interrupt ①② 처리. */
@Service
public class TaskService {

    private static final long MAX_FILE_BYTES = 1024 * 1024;
    private static final Set<String> ALLOWED_EXT = Set.of("md", "markdown", "txt");

    private final AnalysisTaskRepository tasks;
    private final RegulationDocumentRepository documents;
    private final RequirementRepository requirements;
    private final ChangeSpecRepository changeSpecs;
    private final CodePatchRepository patches;
    private final TestCaseRepository testCases;
    private final ApprovalRepository approvals;
    private final DeliveryRepository deliveries;
    private final TaskEventService events;
    private final UserRepository users;
    private final RuleProposalRepository proposals;
    private final JobRepository jobs;

    public TaskService(AnalysisTaskRepository tasks, RegulationDocumentRepository documents,
                       RequirementRepository requirements, ChangeSpecRepository changeSpecs,
                       CodePatchRepository patches, TestCaseRepository testCases, ApprovalRepository approvals,
                       DeliveryRepository deliveries, TaskEventService events,
                       UserRepository users, RuleProposalRepository proposals, JobRepository jobs) {
        this.tasks = tasks;
        this.documents = documents;
        this.requirements = requirements;
        this.changeSpecs = changeSpecs;
        this.patches = patches;
        this.testCases = testCases;
        this.approvals = approvals;
        this.deliveries = deliveries;
        this.events = events;
        this.users = users;
        this.proposals = proposals;
        this.jobs = jobs;
    }

    // ===================== 생성 =====================

    /** 규정 v3(구) · v4(신) 파일을 받아 작업을 만든다. Agent 호출은 커밋 뒤 AgentDispatcher 가 한다. */
    @Transactional
    public AnalysisTask create(AuthUser me, MultipartFile oldFile, MultipartFile newFile,
                               String title, String oldVersion, String newVersion) {
        String oldText = readText(oldFile, "oldFile");
        String newText = readText(newFile, "newFile");
        if (sha256(oldText).equals(sha256(newText))) {
            throw bad("신·구 규정 파일 내용이 같습니다");
        }
        String oldLabel = blankToDefault(oldVersion, "v3");
        String newLabel = blankToDefault(newVersion, "v4");
        String taskTitle = blankToDefault(title, regulationName(newText, newFile) + " " + oldLabel + " → " + newLabel);

        AnalysisTask task = tasks.save(AnalysisTask.create(me.id(), taskTitle));
        documents.save(new RegulationDocument(task.getId(), RegulationDocument.Side.OLD, oldLabel,
                safeName(oldFile), oldText, sha256(oldText)));
        documents.save(new RegulationDocument(task.getId(), RegulationDocument.Side.NEW, newLabel,
                safeName(newFile), newText, sha256(newText)));
        events.append(task.getId(), "STEP", Map.<String, Object>of("node", "requirement_agent", "message", "규정 업로드 완료, 요건 추출을 시작합니다"));
        return task;
    }

    // ===================== 조회 =====================

    @Transactional(readOnly = true)
    public AnalysisTask get(UUID taskId) {
        return tasks.findById(taskId).orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "task not found"));
    }

    @Transactional(readOnly = true)
    public List<AnalysisTask> list(AuthUser me, boolean mine) {
        return mine ? tasks.findByRequesterIdOrderByCreatedAtDesc(me.id()) : tasks.findAllByOrderByCreatedAtDesc();
    }

    @Transactional(readOnly = true)
    public List<RegulationDocument> documents(UUID taskId) {
        get(taskId);
        return documents.findByTaskIdOrderByIdAsc(taskId);
    }

    @Transactional(readOnly = true)
    public List<Requirement> requirements(UUID taskId) {
        get(taskId);
        return requirements.findByTaskIdOrderByIdAsc(taskId);
    }

    @Transactional(readOnly = true)
    public List<ChangeSpec> changeSpecs(UUID taskId) {
        get(taskId);
        return changeSpecs.findByTaskIdOrderByIdAsc(taskId);
    }

    @Transactional(readOnly = true)
    public List<CodePatch> patches(UUID taskId) {
        get(taskId);
        return patches.findByTaskIdOrderByRoundAscIdAsc(taskId);
    }

    @Transactional(readOnly = true)
    public List<TestCase> testCases(UUID taskId) {
        get(taskId);
        return testCases.findByTaskIdOrderByIdAsc(taskId);
    }

    @Transactional(readOnly = true)
    public List<ApprovalView> approvals(UUID taskId) {
        List<Approval> list = approvals.findByTaskIdOrderByIdAsc(taskId);
        Map<Long, User> byId = new HashMap<>();
        users.findAllById(list.stream().map(Approval::getApproverId).distinct().toList())
                .forEach(u -> byId.put(u.getId(), u));
        return list.stream().map(a -> ApprovalView.of(a, byId.get(a.getApproverId()))).toList();
    }

    @Transactional(readOnly = true)
    public ApprovalView approvalView(Approval a) {
        return ApprovalView.of(a, users.findById(a.getApproverId()).orElseThrow());
    }

    @Transactional(readOnly = true)
    public List<RuleProposal> proposals(UUID taskId) {
        get(taskId);
        return proposals.findByTaskIdOrderByProposalKeyAscRoundAsc(taskId);
    }

    @Transactional(readOnly = true)
    public List<Map<String, Object>> contractImpacts(UUID taskId) {
        List<Map<String, Object>> items = get(taskId).getContractImpacts();
        return items == null ? List.of() : items;
    }

    /** 제안 키마다 가장 최근 반영 작업의 결과 (v2 10.4). */
    @Transactional(readOnly = true)
    public Map<String, TaskDtos.ApplyResult> applyResults(UUID taskId) {
        Map<String, TaskDtos.ApplyResult> out = new HashMap<>();
        for (Job j : jobs.findByTaskIdOrderByCreatedAtAsc(taskId)) {
            if (j.getType() != Job.Type.APPLY_RULE_VERSION || j.getPayload() == null) continue;
            Object key = j.getPayload().get("proposalKey");
            if (key == null) continue;
            Map<String, Object> r = j.getResult() == null ? Map.of() : j.getResult();
            out.put(key.toString(), new TaskDtos.ApplyResult(j.getId().toString(), j.getStatus().name(),
                    (String) r.get("closedRuleId"), (String) r.get("newRuleId")));
        }
        return out;
    }

    /** 가장 최근 확인(REVIEW) 기록. 제안마다 반영 · 제외를 붙일 때 쓴다. */
    @Transactional(readOnly = true)
    public Optional<Approval> latestReview(UUID taskId) {
        List<Approval> reviews = approvals.findByTaskIdOrderByIdAsc(taskId).stream()
                .filter(a -> a.getStep() == Approval.Step.REVIEW).toList();
        return reviews.isEmpty() ? Optional.empty() : Optional.of(reviews.get(reviews.size() - 1));
    }

    @Transactional(readOnly = true)
    public List<Delivery> deliveries(UUID taskId) {
        return deliveries.findByTaskIdOrderByIdAsc(taskId);
    }

    /** (bundle, file) 마다 가장 높은 회차의 패치 = 현재 패치. */
    public static List<CodePatch> latestPatches(List<CodePatch> all) {
        Map<String, CodePatch> latest = new LinkedHashMap<>();
        for (CodePatch p : all) {
            String key = p.getBundle() + "::" + p.getFilePath();
            CodePatch cur = latest.get(key);
            if (cur == null || p.getRound() >= cur.getRound()) latest.put(key, p);
        }
        return new ArrayList<>(latest.values());
    }

    // ===================== interrupt ① 요건 확정 (옛 흐름) =====================

    public record RequirementDecision(Long requirementId, Requirement.Status decision) {}

    @Transactional
    public Approval approveRequirements(UUID taskId, AuthUser me, List<RequirementDecision> decisions, String comment) {
        AnalysisTask task = lockAndExpect(taskId, TaskStatus.WAITING_REQUIREMENT_APPROVAL);

        List<Requirement> reqs = requirements.findByTaskIdOrderByIdAsc(taskId);
        if (reqs.isEmpty()) throw conflict("확정할 요건이 없습니다");
        Map<Long, Requirement.Status> byId = new HashMap<>();
        for (RequirementDecision d : decisions == null ? List.<RequirementDecision>of() : decisions) {
            if (d.decision() != Requirement.Status.CONFIRMED && d.decision() != Requirement.Status.HELD) {
                throw bad("decision 은 CONFIRMED 또는 HELD 입니다");
            }
            byId.put(d.requirementId(), d.decision());
        }
        List<Map<String, Object>> recorded = new ArrayList<>();
        List<String> confirmedKeys = new ArrayList<>();
        for (Requirement r : reqs) {
            Requirement.Status s = byId.remove(r.getId());
            if (s == null) throw bad("요건 " + r.getReqKey() + "(id " + r.getId() + ")에 대한 결정이 없습니다");
            r.setStatus(s);
            requirements.save(r);
            recorded.add(Map.<String, Object>of("requirementId", r.getId(), "reqKey", r.getReqKey(), "decision", s.name()));
            if (s == Requirement.Status.CONFIRMED) confirmedKeys.add(r.getReqKey());
        }
        if (!byId.isEmpty()) throw bad("이 작업에 없는 요건 id: " + byId.keySet());

        Approval.Decision overall = confirmedKeys.isEmpty() ? Approval.Decision.HELD : Approval.Decision.CONFIRMED;
        Approval saved = approvals.save(new Approval(taskId, Approval.Step.REQUIREMENTS, overall, me.id(), comment,
                Map.<String, Object>of("decisions", recorded, "confirmedReqKeys", confirmedKeys)));

        // 전부 보류 → 바로 HELD (Agent 는 report 만 만들고 끝낸다). 일부라도 확정 → 영향 위치 탐색.
        events.append(taskId, "RESUMED", Map.<String, Object>of("step", "REQUIREMENTS", "decision", overall.name(),
                "by", me.username(), "approvalId", saved.getId()));
        if (overall == Approval.Decision.HELD) {
            events.append(taskId, "STATUS", Map.<String, Object>of("status", TaskStatus.HELD.name()));
        } else {
            events.append(taskId, "STEP", Map.<String, Object>of("node", "locate_agent"));
        }
        return saved;
    }

    // ===================== interrupt ② 확인 (v2 제안 확인 · 옛 흐름 패치 검토) =====================

    @Transactional
    public Approval review(UUID taskId, AuthUser me, Approval.Decision decision, String comment,
                           List<String> excludedSpecKeys, List<String> excludedProposalKeys) {
        if (proposals.existsByTaskId(taskId)) return reviewProposals(taskId, me, decision, comment, excludedProposalKeys);
        if (decision != Approval.Decision.APPROVE && decision != Approval.Decision.REJECT
                && decision != Approval.Decision.REQUEST_CHANGES) {
            throw bad("decision 은 APPROVE | REJECT | REQUEST_CHANGES 입니다");
        }
        AnalysisTask task = lockAndExpect(taskId, TaskStatus.WAITING_REVIEW);
        List<String> excluded = excludedSpecKeys == null ? List.of() : List.copyOf(excludedSpecKeys);
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("excludedSpecKeys", excluded);

        switch (decision) {
            case APPROVE -> {
                // 제외하지 않은 패치만 publish 대상. 그중 검증을 통과하지 못한 패치가 있으면 차단 (예외 없음).
                List<CodePatch> targets = latestPatches(patches.findByTaskIdOrderByRoundAscIdAsc(taskId)).stream()
                        .filter(p -> p.getSpecKeys().isEmpty() || !excluded.containsAll(p.getSpecKeys()))
                        .toList();
                if (targets.isEmpty()) throw conflict("승인할 패치가 없습니다. 전부 제외하려면 REJECT 를 쓰세요");
                List<String> notPassed = targets.stream()
                        .filter(p -> p.getVerifyStatus() != CodePatch.VerifyStatus.PASSED)
                        .map(p -> p.getBundle() + ":" + p.getFilePath() + "(" + p.getVerifyStatus() + ")")
                        .toList();
                if (!notPassed.isEmpty()) {
                    throw conflict("검증을 통과하지 못한 패치가 있어 승인할 수 없습니다: " + notPassed
                            + " — 해당 위치를 제외하거나 수정 요청하세요");
                }
                payload.put("approvedPatchIds", targets.stream().map(CodePatch::getId).toList());
            }
            case REQUEST_CHANGES -> {
                if (comment == null || comment.isBlank()) throw bad("수정 요청에는 comment 가 필요합니다");
            }
            default -> { /* REJECT */ }
        }

        Approval saved = approvals.save(new Approval(taskId, Approval.Step.REVIEW, decision, me.id(), comment, payload));
        events.append(taskId, "RESUMED", Map.<String, Object>of("step", "REVIEW", "decision", decision.name(),
                "by", me.username(), "approvalId", saved.getId()));
        switch (decision) {
            case APPROVE -> events.append(taskId, "STEP", Map.<String, Object>of("node", "publish"));
            case REJECT -> events.append(taskId, "STATUS", Map.<String, Object>of("status", TaskStatus.REJECTED.name()));
            // 사람이 고친 내용도 다시 검증한다: design 으로 돌아가 반영 → verify
            default -> events.append(taskId, "STEP", Map.<String, Object>of("node", "design_agent", "message", "수정 요청 반영 후 재검증"));
        }
        return saved;
    }

    /**
     * v2 사용자 확인 (10.3). APPROVE 는 제외하지 않은 change_required 제안을 반영 대상으로 확정한다.
     * 역할 검사는 없다. 로그인한 사용자 누구나.
     */
    private Approval reviewProposals(UUID taskId, AuthUser me, Approval.Decision decision, String comment,
                                     List<String> excludedProposalKeys) {
        if (decision != Approval.Decision.APPROVE && decision != Approval.Decision.REJECT) {
            throw bad("decision 은 APPROVE | REJECT 입니다");
        }
        AnalysisTask task = lockAndExpect(taskId, TaskStatus.WAITING_REVIEW);
        List<RuleProposal> latest = Proposals.latest(proposals.findByTaskIdOrderByProposalKeyAscRoundAsc(taskId));
        List<String> changeKeys = Proposals.changeKeys(latest);
        List<String> excluded = excludedProposalKeys == null ? List.of() : List.copyOf(new LinkedHashSet<>(excludedProposalKeys));
        Map<String, Object> payload = new LinkedHashMap<>();

        if (decision == Approval.Decision.APPROVE) {
            if (!Proposals.canApprove(task.getStatus(), latest)) {
                throw conflict("근거 검사를 통과하지 못한 변경 제안이 있거나 반영할 제안이 없습니다");
            }
            List<String> unknown = excluded.stream().filter(k -> !changeKeys.contains(k)).toList();
            if (!unknown.isEmpty()) throw bad("변경 필요 제안이 아닌 키입니다: " + unknown);
            List<String> approved = changeKeys.stream().filter(k -> !excluded.contains(k)).toList();
            if (approved.isEmpty()) throw bad("반영할 제안이 없습니다. 전부 제외하려면 REJECT 를 쓰세요");
            payload.put("approvedProposalKeys", approved);
        }
        payload.put("excludedProposalKeys", excluded);

        Approval saved = approvals.save(new Approval(taskId, Approval.Step.REVIEW, decision, me.id(), comment, payload));
        events.append(taskId, "RESUMED", Map.<String, Object>of("step", "REVIEW", "decision", decision.name(),
                "by", me.username(), "approvalId", saved.getId()));
        if (decision == Approval.Decision.APPROVE) {
            events.append(taskId, "STEP", Map.<String, Object>of("node", "apply"));
        } else {
            events.append(taskId, "STATUS", Map.<String, Object>of("status", TaskStatus.REJECTED.name()));
        }
        return saved;
    }

    // ===================== 이어가기 (Agent 가 도중에 죽었을 때) =====================

    /**
     * "다시 시도" 준비. 진행 중이거나 FAILED 인 작업만. Agent 호출은 컨트롤러가 커밋 뒤에 동기로 한다.
     * FAILED 였으면 상태를 멈추기 전 자리로 되돌린다 (승인 뒤면 PUBLISHING, 아니면 마지막 노드의 상태).
     * Agent 이벤트는 FAILED 에서 나올 수 없어서 백엔드가 먼저 되돌려야 한다.
     */
    @Transactional
    public AnalysisTask prepareRetry(UUID taskId, AuthUser me) {
        AnalysisTask task = tasks.findForUpdate(taskId)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "task not found"));
        if (!task.getStatus().canRetry()) {
            String hint = task.getStatus().isTerminal() ? "끝난 작업입니다. 새로 올려 주세요"
                    : "승인을 기다리는 작업입니다. 확인 화면에서 결정해 주세요";
            throw conflict("다시 시도할 수 없는 상태입니다 (" + task.getStatus() + "): " + hint);
        }
        events.append(taskId, "RESUMED", Map.<String, Object>of("step", "RETRY", "by", me.username(),
                "message", "멈춘 자리부터 다시 시작합니다"));
        if (task.getStatus() == TaskStatus.FAILED) {
            TaskStatus restored = latestApprove(taskId).isPresent() ? TaskStatus.PUBLISHING
                    : Optional.ofNullable(TaskStatus.fromNode(task.getCurrentNode())).orElse(TaskStatus.EXTRACTING);
            task.setErrorMessage(null);
            tasks.save(task);
            events.append(taskId, "STATUS", Map.<String, Object>of("status", restored.name()));
            task.setStatus(restored);
        }
        return task;
    }

    /** 가장 최근 확인이 APPROVE 면 그 기록. Agent 가 확인 대기 상태로 남아 있을 때 다시 보낼 승인이다. */
    @Transactional(readOnly = true)
    public Optional<Approval> latestApprove(UUID taskId) {
        return latestReview(taskId).filter(a -> a.getDecision() == Approval.Decision.APPROVE);
    }

    /** 다시 시도가 FAILED 로 끝나면 사용자에게 보이게 기록한다. */
    @Transactional
    public void retryFailed(UUID taskId, String reason) {
        events.append(taskId, "FAILED", Map.<String, Object>of("reason", reason));
    }

    // ===================== helpers =====================

    private AnalysisTask lockAndExpect(UUID taskId, TaskStatus expected) {
        AnalysisTask task = tasks.findForUpdate(taskId)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "task not found"));
        if (task.getStatus() != expected) {
            throw conflict("작업 상태가 " + task.getStatus() + " 입니다 (필요: " + expected + ")");
        }
        return task;
    }

    private static String readText(MultipartFile file, String field) {
        if (file == null || file.isEmpty()) throw bad(field + " 파일이 필요합니다");
        if (file.getSize() > MAX_FILE_BYTES) throw bad(field + " 는 1MB 이하여야 합니다");
        String ext = extOf(file.getOriginalFilename());
        if (!ALLOWED_EXT.contains(ext)) throw bad(field + " 는 .md / .txt 파일이어야 합니다");
        try {
            String text = new String(file.getBytes(), StandardCharsets.UTF_8);
            if (text.isBlank()) throw bad(field + " 내용이 비어 있습니다");
            return text;
        } catch (IOException e) {
            throw bad(field + " 를 읽을 수 없습니다");
        }
    }

    static String sha256(String text) {
        try {
            byte[] h = MessageDigest.getInstance("SHA-256").digest(text.getBytes(StandardCharsets.UTF_8));
            return HexFormat.of().formatHex(h);
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
    }

    private static String safeName(MultipartFile f) {
        String n = f.getOriginalFilename();
        if (n == null || n.isBlank()) return "regulation.md";
        n = n.replace('\\', '/');
        n = n.substring(n.lastIndexOf('/') + 1);
        return n.length() > 255 ? n.substring(0, 255) : n;
    }

    private static String extOf(String name) {
        if (name == null) return "";
        int i = name.lastIndexOf('.');
        return i < 0 ? "" : name.substring(i + 1).toLowerCase(Locale.ROOT);
    }

    private static final Pattern FRONTMATTER_TITLE = Pattern.compile("\\A---\\R(?:(?!---).*\\R)*?title:\\s*(.+?)\\s*\\R");

    /** 규정 이름은 frontmatter 의 title 을 쓰고, 없으면 파일명을 쓴다. */
    private static String regulationName(String text, MultipartFile file) {
        Matcher m = FRONTMATTER_TITLE.matcher(text);
        return m.find() ? m.group(1) : stripExt(file.getOriginalFilename());
    }

    private static String stripExt(String name) {
        if (name == null || name.isBlank()) return "규정";
        String n = name.replace('\\', '/');
        n = n.substring(n.lastIndexOf('/') + 1);
        int i = n.lastIndexOf('.');
        return i <= 0 ? n : n.substring(0, i);
    }

    private static String blankToDefault(String v, String def) {
        if (v == null || v.isBlank()) return def;
        String t = v.trim();
        return t.length() > 200 ? t.substring(0, 200) : t;
    }

    private static ResponseStatusException bad(String m) {
        return new ResponseStatusException(HttpStatus.BAD_REQUEST, m);
    }

    private static ResponseStatusException conflict(String m) {
        return new ResponseStatusException(HttpStatus.CONFLICT, m);
    }
}
