import hashlib
import math
from pathlib import Path

import pytest

from regulation_mcp import product_docs as docs
from regulation_mcp import regulations as reg
from regulation_mcp import search
from regulation_mcp.regulations import RegulationError
from regulation_mcp.search import BM25, SearchIndex


class FakeEmbedder:
    """글자 bigram 해시 벡터. 결정적이고 네트워크를 쓰지 않는다. 임베딩한 텍스트 수를 센다."""

    def __init__(self, dim: int = 512):
        self.dim = dim
        self.embedded = 0

    def __call__(self, texts: list[str]) -> list[list[float]]:
        self.embedded += len(texts)
        out = []
        for t in texts:
            v = [0.0] * self.dim
            for a, b in zip(t, t[1:]):
                if not (a + b).isspace():
                    v[int(hashlib.md5((a + b).encode()).hexdigest(), 16) % self.dim] += 1
            norm = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / norm for x in v])
        return out


@pytest.fixture
def hybrid():
    return SearchIndex(FakeEmbedder())


@pytest.fixture
def keyword_only():
    return SearchIndex(None)


def test_article_label():
    assert search.article_label("15") == "제15조"
    assert search.article_label("15-2") == "제15조의2"
    assert search.article_label("supp-2") == "부칙 제2조"


def test_tokenize_keeps_numbers_and_acronyms():
    toks = search.tokenize("DSR 40% 이내, 100분의 5")
    assert {"dsr", "40%", "100", "5", "이내", "분의"} <= set(toks)


def test_bm25_prefers_matching_text():
    scores = BM25(["DSR 한도 40%", "고령자 우대 금리", "연체 통지"]).scores("DSR 한도")
    assert scores[0] > scores[1] and scores[0] > scores[2]


@pytest.mark.parametrize("index", ["hybrid", "keyword_only"])
def test_default_scope_is_latest_version_of_every_regulation(index, request):
    hits = request.getfixturevalue(index).search_regulations("고령 금융소비자 녹취 보관", k=20)
    versions = {(h["regulation_id"], h["version"]) for h in hits}
    assert ("credit-loan-ops", "v3") not in versions  # 최신 버전만
    assert hits[0]["regulation_id"] == "senior-protection"


def test_result_format(hybrid):
    hit = hybrid.search_regulations("DSR 한도", "credit-loan-ops")[0]
    assert set(hit) == {"uri", "regulation_id", "version", "article_id", "title", "text"}
    assert hit["uri"] == f"reg://credit-loan-ops/v4/{hit['article_id']}"


def test_explicit_version_filter(hybrid):
    hits = hybrid.search_regulations("고령자 설명 확인 기록 보관", "credit-loan-ops", "v3", k=30)
    assert all(h["version"] == "v3" for h in hits)
    assert "15-2" not in {h["article_id"] for h in hits}  # v3에는 없는 조항


def test_version_without_regulation_is_rejected(hybrid):
    with pytest.raises(RegulationError, match="regulation_id"):
        hybrid.search_regulations("DSR", version="v4")


def test_keyword_finds_exact_number(keyword_only):
    assert keyword_only.search_regulations("100분의 5 예외 승인", "dsr-management")[0]["article_id"] == "11"


def test_indexes_once_until_files_change(tmp_path):
    root = tmp_path / "regs" / "r"
    root.mkdir(parents=True)
    f = root / "v1.md"
    f.write_text("---\ntitle: T\n---\n### 제1조(가)\n가나다\n### 제2조(나)\n라마바\n", encoding="utf-8")
    emb = FakeEmbedder()
    idx = SearchIndex(emb, regulations_root=tmp_path / "regs", docs_root=tmp_path / "none")
    idx.search_regulations("가나다")
    idx.search_regulations("라마바")
    assert emb.embedded == 2 + 2  # 조항 2개 색인 1번 + 질의 2번

    reg.load.cache_clear()
    f.write_text("---\ntitle: T\n---\n### 제1조(가)\n바뀐 내용\n### 제2조(나)\n라마바\n", encoding="utf-8")
    assert idx.search_regulations("바뀐 내용")[0]["article_id"] == "1"
    assert emb.embedded == 4 + 2 + 1  # 바뀌면 다시 색인


def test_embedding_failure_falls_back_to_keyword():
    calls = {"n": 0}

    def flaky(texts):
        calls["n"] += 1
        if calls["n"] > 1:  # 색인은 되고 질의 임베딩에서 실패
            raise ConnectionError("network down")
        return FakeEmbedder()(texts)

    idx = SearchIndex(flaky)
    hits = idx.search_regulations("100분의 5 예외 승인", "dsr-management")
    assert hits[0]["article_id"] == "11"


@pytest.mark.parametrize(("regulation_id", "version"), [("../../eval", "answer_key"), ("credit-loan-ops", "README")])
def test_regulation_out_of_scope_is_rejected(hybrid, regulation_id, version):
    with pytest.raises(RegulationError):
        hybrid.search_regulations("정답", regulation_id, version)


def test_empty_query_is_rejected(hybrid):
    with pytest.raises(RegulationError):
        hybrid.search_regulations("  ")


# ---------- 상품 문서 ----------


def test_doc_sections_follow_readme():
    d = docs.get_doc("P010")
    assert d["name"] == "리플 중금리 신용대출"
    assert [s["section"] for s in d["sections"]][:2] == ["신청 대상", "심사 절차"]
    assert d["sections"][1]["uri"] == "doc://P010#2"


def test_search_docs_result_format_and_filter(hybrid):
    hits = hybrid.search_docs("녹취", product_id="P002")
    assert hits and all(h["product_id"] == "P002" for h in hits)
    assert set(hits[0]) == {"uri", "product_id", "name", "section", "text", "updated_at"}


def test_search_docs_across_products(keyword_only):
    hits = keyword_only.search_docs("번역본 설명서")
    assert hits[0]["product_id"] == "P011"


@pytest.mark.parametrize("product_id", ["../README", "README", "p001", "P001/../../x", "/etc/passwd"])
def test_doc_out_of_scope_is_rejected(product_id):
    with pytest.raises(RegulationError):
        docs.load(product_id)


def test_doc_symlink_escape_is_blocked(tmp_path):
    (tmp_path / "secret.md").write_text("---\nname: x\n---\n## 1. 정답\n정답\n", encoding="utf-8")
    root = tmp_path / "docs"
    root.mkdir()
    (root / "P999.md").symlink_to(tmp_path / "secret.md")
    with pytest.raises(RegulationError, match="폴더 밖"):
        docs.doc_path("P999", root)


def test_readme_is_not_a_product_doc():
    assert "README" not in docs.list_products()
    assert docs.list_products()[:2] == ["P001", "P002"]


def test_server_index_without_api_key_is_keyword_only(monkeypatch):
    monkeypatch.setattr(search, "_index", None)
    assert search.index().regulations._embed is None
    monkeypatch.setattr(search, "_index", None)


def test_data_dirs_exist():
    assert Path(reg.REGULATIONS_DIR).is_dir() and Path(docs.PRODUCT_DOCS_DIR).is_dir()
