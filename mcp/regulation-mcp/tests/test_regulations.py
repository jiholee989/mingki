import pytest

from regulation_mcp import regulations as reg
from regulation_mcp.regulations import RegulationError


def test_articles_follow_readme_id_rules():
    ids = [a["article_id"] for a in reg.list_articles("credit-loan-ops", "v4")]
    assert "15" in ids and "15-2" in ids and "supp-2" in ids
    assert reg.get_article("credit-loan-ops", "v4", "15-2")["title"] == "고령자 설명 확인"


def test_diff_finds_substantive_and_wording_changes():
    diff = reg.diff_versions("credit-loan-ops", "v3", "v4")
    assert diff["effective_from"] == "2026-12-01"
    changes = {c["article_id"]: c for c in diff["changes"]}

    assert changes["8"]["change"] == "modified"
    assert changes["15"]["change"] == "modified"
    assert changes["15-2"]["change"] == "added"
    assert changes["15-2"]["old_text"] is None
    assert changes["15-2"]["new_uri"] == "reg://credit-loan-ops/v4/15-2"
    # 바뀌지 않은 조항은 빠진다
    assert "1" not in changes


def test_diff_is_deterministic():
    assert reg.diff_versions("credit-loan-ops", "v3", "v4") == reg.diff_versions("credit-loan-ops", "v3", "v4")


def test_search_requires_all_terms():
    hits = reg.search("고령자", "credit-loan-ops", "v4")
    assert {"15", "15-2", "16"} <= {h["article_id"] for h in hits}
    assert all("DSR" in h["text"] or "DSR" in h["title"] for h in reg.search("DSR 한도", "credit-loan-ops", "v4"))


@pytest.mark.parametrize(
    ("regulation_id", "version"),
    [
        ("../../eval", "answer_key"),   # 정답지
        ("../../docs", "v1"),
        ("credit-loan-ops", "../README"),
        ("credit-loan-ops", "README"),  # 같은 폴더의 README도 범위 밖
        ("/etc", "v1"),
    ],
)
def test_scope_is_limited_to_versioned_regulation_files(regulation_id, version):
    with pytest.raises(RegulationError):
        reg.load(regulation_id, version)


def test_symlink_escape_is_blocked(tmp_path):
    (tmp_path / "secret.md").write_text("---\ntitle: x\n---\n### 제1조(정답)\n정답\n", encoding="utf-8")
    root = tmp_path / "regs"
    (root / "leak").mkdir(parents=True)
    (root / "leak" / "v1.md").symlink_to(tmp_path / "secret.md")
    with pytest.raises(RegulationError, match="폴더 밖"):
        reg.regulation_path("leak", "v1", root)


def test_unknown_version_lists_available():
    with pytest.raises(RegulationError, match="v4"):
        reg.load("credit-loan-ops", "v9")


def _write(root, rid, version, front, body="### 제1조(목적)\n본문"):
    d = root / rid
    d.mkdir(exist_ok=True)
    (d / f"{version}.md").write_text(f"---\n{front}\n---\n{body}\n", encoding="utf-8")


def test_list_regulations_reads_applies_to(tmp_path):
    _write(tmp_path, "a-rule", "v1", "title: 가 기준\nversion: v1\neffective_from: 2025-01-01\napplies_to: [P001, P002]")
    _write(tmp_path, "b-rule", "v1", "title: 나 기준\nversion: v1\neffective_from: 2025-01-01")
    regs = {r["regulation_id"]: r for r in reg.list_regulations(tmp_path)}
    assert regs["a-rule"]["applies_to"] == ["P001", "P002"]
    assert regs["b-rule"]["applies_to"] is None  # 정보 없음 ≠ 빈 목록


def test_previous_version_must_exist(tmp_path):
    _write(tmp_path, "c-rule", "v2", "title: 다 기준\nversion: v2\neffective_from: 2025-01-01\nprevious_version: v1")
    with pytest.raises(RegulationError, match="원문이 없습니다"):
        reg.diff_versions("c-rule", root=tmp_path)
