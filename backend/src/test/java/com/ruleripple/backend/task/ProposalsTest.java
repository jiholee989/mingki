package com.ruleripple.backend.task;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.nio.file.Path;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/** 제안 규칙 (docs/BACKEND_API.md 10.2 · 10.3). 계약 예시(docs/contracts)를 그대로 읽는다. */
class ProposalsTest {

    private static final Path CONTRACTS = Path.of("../docs/contracts");
    private static final ObjectMapper JSON = new ObjectMapper().findAndRegisterModules();

    private static List<Proposals.Item> exampleItems() throws IOException {
        JsonNode items = JSON.readTree(CONTRACTS.resolve("proposals.put.json").toFile()).get("items");
        List<Proposals.Item> out = new ArrayList<>();
        for (JsonNode n : items) out.add(JSON.treeToValue(n, Proposals.Item.class));
        return out;
    }

    private static Proposals.Item change(String ruleId, String currentValue, String unit) {
        return new Proposals.Item("P001:DSR_LIMIT", "REQ-8", "P001", ruleId, "DSR_LIMIT", "change_required",
                "DSR 한도 40%", "DSR 한도 35%", unit, currentValue, "0.35", LocalDate.of(2026, 12, 1),
                "reg://credit-loan-ops/v4/8", "개정 기준 초과", null, List.of(), 1, null, null);
    }

    @Test
    void contractExampleIsValid() throws IOException {
        List<Proposals.Item> items = exampleItems();
        assertThat(items).hasSize(4);
        assertThat(items).allSatisfy(i -> assertThat(Proposals.invalid(i)).isNull());
        assertThat(items.get(1).unit()).isEqualTo("percent");
        assertThat(items.get(1).verifyStatus()).isEqualTo(RuleProposal.VerifyStatus.PASSED);
    }

    @Test
    void changeRequiredNeedsValuesToApply() {
        assertThat(Proposals.invalid(change("R001", "0.40", "ratio"))).isNull();
        assertThat(Proposals.invalid(change("R001", null, "ratio"))).contains("currentValue");
        assertThat(Proposals.invalid(change("R001", "0.40", null))).contains("unit");
        // 새 규칙은 지금 값이 없어도 된다
        assertThat(Proposals.invalid(change(null, null, "bool"))).isNull();
    }

    @Test
    void rejectsUnknownImpactAndMissingReason() {
        var base = change("R001", "0.40", "ratio");
        var badImpact = new Proposals.Item(base.proposalKey(), base.reqKey(), base.productId(), base.ruleId(), base.ruleKey(),
                "CHANGE_REQUIRED", null, null, base.unit(), base.currentValue(), base.proposedValue(), base.effectiveDate(),
                null, "이유", null, null, 1, null, null);
        var noReason = new Proposals.Item("P003:DSR_LIMIT", "REQ-8", "P003", "R015", "DSR_LIMIT", "keep",
                null, null, null, null, null, null, null, " ", null, null, 1, null, null);
        assertThat(Proposals.invalid(badImpact)).contains("impact");
        assertThat(Proposals.invalid(noReason)).contains("reason");
    }

    @Test
    void latestPicksHighestRoundPerKey() {
        var all = List.of(row("P001:DSR_LIMIT", 1, "change_required", RuleProposal.VerifyStatus.FAILED),
                row("P001:DSR_LIMIT", 2, "change_required", RuleProposal.VerifyStatus.PASSED),
                row("P003:DSR_LIMIT", 1, "keep", RuleProposal.VerifyStatus.PASSED));
        List<RuleProposal> latest = Proposals.latest(all);
        assertThat(latest).extracting(RuleProposal::getProposalKey, RuleProposal::getRound)
                .containsExactly(org.assertj.core.groups.Tuple.tuple("P001:DSR_LIMIT", 2),
                        org.assertj.core.groups.Tuple.tuple("P003:DSR_LIMIT", 1));
        assertThat(Proposals.changeKeys(latest)).containsExactly("P001:DSR_LIMIT");
    }

    @Test
    void canApproveOnlyWhenEveryChangePassed() {
        var passed = row("P001:DSR_LIMIT", 2, "change_required", RuleProposal.VerifyStatus.PASSED);
        var failed = row("P005:DSR_LIMIT", 1, "change_required", RuleProposal.VerifyStatus.FAILED);
        var keep = row("P003:DSR_LIMIT", 1, "keep", RuleProposal.VerifyStatus.PENDING);

        assertThat(Proposals.canApprove(TaskStatus.WAITING_REVIEW, List.of(passed, keep))).isTrue();
        assertThat(Proposals.canApprove(TaskStatus.WAITING_REVIEW, List.of(passed, failed))).isFalse();
        assertThat(Proposals.canApprove(TaskStatus.WAITING_REVIEW, List.of(keep))).isFalse();   // 반영할 게 없음
        assertThat(Proposals.canApprove(TaskStatus.VERIFYING, List.of(passed))).isFalse();
    }

    @Test
    void reviewExampleCarriesExcludedProposalKeys() throws IOException {
        var req = JSON.readValue(CONTRACTS.resolve("review.post.json").toFile(), TaskController.ReviewRequest.class);
        assertThat(req.decision()).isEqualTo(Approval.Decision.APPROVE);
        assertThat(req.excludedProposalKeys()).containsExactly("P005:DSR_LIMIT");
        // 제외 키는 제안 예시 안의 change_required 제안이어야 한다
        assertThat(exampleItems()).anySatisfy(i -> {
            assertThat(i.proposalKey()).isEqualTo("P005:DSR_LIMIT");
            assertThat(i.impact()).isEqualTo(Proposals.CHANGE_REQUIRED);
        });
    }

    private static RuleProposal row(String key, int round, String impact, RuleProposal.VerifyStatus status) {
        RuleProposal p = new RuleProposal();
        p.setProposalKey(key);
        p.setRound(round);
        p.setImpact(impact);
        p.setVerifyStatus(status);
        return p;
    }
}
