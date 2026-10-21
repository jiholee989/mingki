import pytest
from app.tools.local import LocalTools
from app.graph import build_graph


def test_sample_diff_uses_real_articles_and_new_obligation():
    tools = LocalTools()
    diff = tools.diff_versions("credit-loan-ops", "v3", "v4")
    changes = {c["article_id"]: c for c in diff["changes"]}
    assert changes["15-2"]["change"] == "added"
    assert changes["15-2"]["old_text"] is None
    assert "계약" in changes["15-2"]["new_text"]
    assert changes["8"]["old_uri"] == "reg://credit-loan-ops/v3/8"
    assert diff["effective_from"] == "2026-12-01"
    assert tools.diff_versions("credit-loan-ops", "v4", "v4")["changes"] == []


def test_scope_and_supplementary_articles_are_available_even_if_unchanged():
    tools = LocalTools()
    ids = {a["article_id"] for a in tools.list_articles("credit-loan-ops", "v4")}
    assert {"3", "15", "15-2", "supp-2", "supp-3"} <= ids
    assert "모든 개인신용대출" in tools.get_article("credit-loan-ops", "v4", "3")["text"]
    assert "5년" in tools.get_article("credit-loan-ops", "v4", "15-2")["text"]


def test_local_products_and_rules_use_same_identifiers_as_mcp():
    tools = LocalTools()
    products, rules = tools.get_products(), tools.get_product_rules()
    assert len(products) == 12 and len(rules) == 82
    assert all(row["productId"] in {p["productId"] for p in products} for row in rules)
    rows = tools.get_product_rules("DSR_LIMIT", "P003")
    assert len(rows) == 1 and rows[0]["value"] == "0.35"


def test_node_permissions_and_no_default_reasoner():
    tools = LocalTools()
    with pytest.raises(PermissionError):
        tools.subset("diff_versions").get_products()
    with pytest.raises(ValueError, match="LLM"):
        build_graph(tools, None)


def test_effective_rule_snapshot_does_not_use_closed_or_future_rows():
    from app.data import active_rules
    tools = LocalTools()
    rows = tools.get_product_rules(as_of="2026-11-30")
    assert len(rows) == 80
    assert not {"R070", "R074"} & {r["ruleId"] for r in rows}
    assert {r["ruleId"] for r in rows if r["productId"] == "P010"} == {"R071", "R072", "R073"}
    future = {**rows[0], "ruleId": "future", "effectiveFrom": "2026-12-01"}
    assert active_rules([future], "2026-11-30") == []
    assert len(active_rules([future], "2026-12-01")) == 1


def test_all_product_documents_and_related_regulations_are_observed():
    tools = LocalTools()
    ids = [p["productId"] for p in tools.get_products()]
    documents = tools.get_product_documents(ids)
    assert len(documents["documents"]) == 12 and not documents["data_gaps"]
    context = tools.get_regulation_context("credit-loan-ops", "v4")
    assert {a["regulation_id"] for a in context["articles"]} == {"credit-loan-ops"}   # 바뀐 규정 조항만
    assert all("/v3/" not in a["uri"] for a in context["articles"])
    assert {(r["regulation_id"], r["version"]) for r in context["related"]} == {
        ("consumer-explanation", "v1"), ("dsr-management", "v2"), ("senior-protection", "v1")}
    toc = next(r["articles"] for r in context["related"] if r["regulation_id"] == "dsr-management")
    assert {"article_id": "10", "title": "적용 예외"} in toc and all("text" not in a for a in toc)   # 목차만, 본문 없음
    assert "소액신용대출" in tools.get_article("dsr-management", "v2", "10")["text"]          # 다른 규정은 골라서 본다
    assert ("dsr-management", "10") in {(h["regulation_id"], h["article_id"]) for h in tools.search_regulation("소액신용대출 적용 예외")}
    assert "가계대출이 아니므로" in next(d["content"] for d in documents["documents"] if d["productId"] == "P009")


def test_missing_product_document_is_explicit_and_path_traversal_is_rejected(tmp_path):
    tools = LocalTools(tmp_path)
    assert tools.get_product_documents(["P999"])["data_gaps"]
    with pytest.raises(ValueError):
        tools.get_product_documents(["../secret"])
