package com.ruleripple.backend.internal;

import com.ruleripple.backend.task.*;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

import java.time.LocalDate;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/** Agent 노드가 만든 산출물을 저장한다. 각 노드가 쓸 수 있는 시점을 상태로 제한한다. */
@Service
public class AgentResultService {

    public record RequirementItem(String reqKey, String summary, String target, LocalDate effectiveDate,
                                  String transitional, String articleRef, String oldText, String newText,
                                  Map<String, Object> detail) {}

    public record ChangeSpecItem(String specKey, String reqKey, ChangeSpec.LocationKind locationKind, String filePath,
                                 String symbol, Integer lineNo, String snippet, ChangeSpec.ChangeType changeType,
                                 Boolean target, String reason, String bundle, Map<String, Object> detail) {}

    public record TestCaseItem(String testKey, String reqKey, String name, TestCase.Kind kind, String code,
                               Map<String, Object> detail) {}

    /** verify 결과만 갱신할 때는 diff 를 비워도 된다 (같은 bundle·round·filePath 의 행을 갱신). */
    public record PatchItem(String bundle, Integer round, List<String> specKeys, String filePath, String diff,
                            CodePatch.VerifyStatus verifyStatus, String verifyLog, CodePatch.FailureKind failureKind,
                            Map<String, Object> detail) {}

    private final AnalysisTaskRepository tasks;
    private final RequirementRepository requirements;
    private final ChangeSpecRepository changeSpecs;
    private final TestCaseRepository testCases;
    private final CodePatchRepository patches;

    public AgentResultService(AnalysisTaskRepository tasks, RequirementRepository requirements,
                              ChangeSpecRepository changeSpecs, TestCaseRepository testCases, CodePatchRepository patches) {
        this.tasks = tasks;
        this.requirements = requirements;
        this.changeSpecs = changeSpecs;
        this.testCases = testCases;
        this.patches = patches;
    }

    /** requirement_agent: 요건 추출 중에만, 전체 교체. */
    @Transactional
    public int replaceRequirements(UUID taskId, List<RequirementItem> items) {
        lockIn(taskId, "요건은", TaskStatus.EXTRACTING);
        requirements.deleteAll(requirements.findByTaskIdOrderByIdAsc(taskId));
        requirements.flush();
        for (RequirementItem i : nonNull(items)) {
            if (blank(i.reqKey()) || blank(i.summary())) throw bad("reqKey, summary 는 필수입니다");
            Requirement r = new Requirement();
            r.setTaskId(taskId);
            r.setReqKey(i.reqKey());
            r.setSummary(i.summary());
            r.setTarget(i.target());
            r.setEffectiveDate(i.effectiveDate());
            r.setTransitional(i.transitional());
            r.setArticleRef(i.articleRef());
            r.setOldText(i.oldText());
            r.setNewText(i.newText());
            r.setDetail(i.detail() == null ? Map.of() : i.detail());
            requirements.save(r);
        }
        return nonNull(items).size();
    }

    /** locate_agent: specKey 기준 upsert (system test 실패로 locate 가 다시 돌면 위치가 추가된다). 요건 확정 뒤에만. */
    @Transactional
    public int upsertChangeSpecs(UUID taskId, List<ChangeSpecItem> items) {
        lockIn(taskId, "영향 위치는", TaskStatus.LOCATING, TaskStatus.DESIGNING, TaskStatus.VERIFYING);
        for (ChangeSpecItem i : nonNull(items)) {
            if (blank(i.specKey()) || blank(i.reqKey()) || i.locationKind() == null || i.target() == null || blank(i.reason())) {
                throw bad("specKey, reqKey, locationKind, target, reason 은 필수입니다");
            }
            if (i.target() && i.changeType() == null) throw bad(i.specKey() + ": 대상이면 changeType 이 필요합니다");
            ChangeSpec c = changeSpecs.findByTaskIdAndSpecKey(taskId, i.specKey()).orElseGet(ChangeSpec::new);
            c.setTaskId(taskId);
            c.setSpecKey(i.specKey());
            c.setReqKey(i.reqKey());
            c.setLocationKind(i.locationKind());
            c.setFilePath(i.filePath());
            c.setSymbol(i.symbol());
            c.setLineNo(i.lineNo());
            c.setSnippet(i.snippet());
            c.setChangeType(i.target() ? i.changeType() : null);
            c.setTarget(i.target());
            c.setReason(i.reason());
            c.setBundle(i.bundle());
            c.setDetail(i.detail() == null ? Map.of() : i.detail());
            changeSpecs.save(c);
        }
        return nonNull(items).size();
    }

    /** test_agent: 요건 확정 뒤 한 번만 저장. 이후 수정 불가 (자기채점 방지). */
    @Transactional
    public int saveTestCases(UUID taskId, List<TestCaseItem> items) {
        lockIn(taskId, "테스트는", TaskStatus.LOCATING);
        if (testCases.existsByTaskId(taskId)) throw conflict("테스트는 이미 고정되었습니다. 수정할 수 없습니다");
        for (TestCaseItem i : nonNull(items)) {
            if (blank(i.testKey()) || blank(i.reqKey()) || blank(i.name()) || i.kind() == null || blank(i.code())) {
                throw bad("testKey, reqKey, name, kind, code 는 필수입니다");
            }
            TestCase t = new TestCase();
            t.setTaskId(taskId);
            t.setTestKey(i.testKey());
            t.setReqKey(i.reqKey());
            t.setName(i.name());
            t.setKind(i.kind());
            t.setCode(i.code());
            t.setDetail(i.detail() == null ? Map.of() : i.detail());
            testCases.save(t);
        }
        return nonNull(items).size();
    }

    /**
     * design_agent(diff 저장) · verify(결과 갱신) 공용. (bundle, round, filePath) 기준 upsert.
     * 검토 대기부터는 고정한다. 개발자가 본 diff 와 승인된 diff 가 같아야 한다.
     */
    @Transactional
    public int upsertPatches(UUID taskId, List<PatchItem> items) {
        lockIn(taskId, "패치는", TaskStatus.DESIGNING, TaskStatus.VERIFYING);
        for (PatchItem i : nonNull(items)) {
            if (blank(i.bundle()) || i.round() == null || i.round() < 1 || blank(i.filePath())) {
                throw bad("bundle, round(1 이상), filePath 는 필수입니다");
            }
            CodePatch p = patches.findByTaskIdAndBundleAndRoundAndFilePath(taskId, i.bundle(), i.round(), i.filePath())
                    .orElse(null);
            if (p == null) {
                if (blank(i.diff())) throw bad(i.bundle() + ":" + i.filePath() + " round " + i.round() + " — 새 패치에는 diff 가 필요합니다");
                p = new CodePatch();
                p.setTaskId(taskId);
                p.setBundle(i.bundle());
                p.setRound(i.round());
                p.setFilePath(i.filePath());
            }
            if (!blank(i.diff())) p.setDiff(i.diff());
            if (i.specKeys() != null) p.setSpecKeys(List.copyOf(i.specKeys()));
            if (i.verifyStatus() != null) p.setVerifyStatus(i.verifyStatus());
            if (i.verifyLog() != null) p.setVerifyLog(i.verifyLog());
            if (i.failureKind() != null) p.setFailureKind(i.failureKind());
            if (i.detail() != null) p.setDetail(i.detail());
            patches.save(p);
        }
        return nonNull(items).size();
    }

    @Transactional
    public void saveReport(UUID taskId, Map<String, Object> report) {
        AnalysisTask task = load(taskId);
        task.setReport(report);
        tasks.save(task);
    }

    @Transactional
    public void saveEvaluation(UUID taskId, Map<String, Object> evaluation) {
        AnalysisTask task = load(taskId);
        task.setEvaluation(evaluation);
        tasks.save(task);
    }

    /** 작업 행을 잠그고 상태를 확인한다. 상태 전이(TaskEventService)와 같은 잠금을 쓴다. */
    private void lockIn(UUID taskId, String what, TaskStatus... allowed) {
        AnalysisTask task = tasks.findForUpdate(taskId)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "task not found"));
        if (!Arrays.asList(allowed).contains(task.getStatus())) {
            throw conflict(what + " " + Arrays.toString(allowed) + " 상태에서만 저장할 수 있습니다 (현재 " + task.getStatus() + ")");
        }
    }

    private AnalysisTask load(UUID taskId) {
        return tasks.findById(taskId).orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "task not found"));
    }

    private static <T> List<T> nonNull(List<T> l) {
        return l == null ? List.of() : l;
    }

    private static boolean blank(String s) {
        return s == null || s.isBlank();
    }

    private static ResponseStatusException bad(String m) {
        return new ResponseStatusException(HttpStatus.BAD_REQUEST, m);
    }

    private static ResponseStatusException conflict(String m) {
        return new ResponseStatusException(HttpStatus.CONFLICT, m);
    }
}
