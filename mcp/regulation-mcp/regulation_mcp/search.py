"""규정 · 상품 문서 검색 (Vector DB + 키워드 혼합).

- 조각: 규정은 조항 1개, 상품 문서는 `##` 섹션 1개.
- 의미 검색: OpenAI 임베딩 + 프로세스 안 Chroma(메모리). 컬렉션은 regulations, product_docs.
- 키워드 검색: BM25. 한글은 단어와 글자 bigram, 영문 · 숫자는 그대로(DSR, 40%, 100분의) 토큰으로 쓴다.
- 혼합: 두 점수를 후보 안에서 0~1로 정규화한 뒤 가중합한다 (의미 HYBRID_ALPHA, 키워드 1 - HYBRID_ALPHA).
- OPENAI_API_KEY가 없거나 임베딩 호출이 실패하면 BM25만 쓴다.
- 색인은 원본 파일 내용이 바뀌었을 때만 다시 만든다.
색인 규칙은 docs/VECTOR_INDEX.md 를 따른다.
"""

import hashlib
import logging
import math
import os
import re
import uuid
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from regulation_mcp import product_docs as docs
from regulation_mcp import regulations as reg
from regulation_mcp.regulations import RegulationError

log = logging.getLogger(__name__)

EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")
TOP_K = int(os.environ.get("SEARCH_TOP_K", 5))
HYBRID_ALPHA = float(os.environ.get("HYBRID_ALPHA", 0.5))  # 혼합 점수에서 의미 검색 비중

Embedder = Callable[[list[str]], list[list[float]]]


def openai_embedder(texts: list[str]) -> list[list[float]]:
    from openai import OpenAI

    resp = OpenAI().embeddings.create(model=EMBEDDING_MODEL, input=texts)
    return [d.embedding for d in resp.data]


def article_label(aid: str) -> str:
    """'15-2' → '제15조의2', 'supp-2' → '부칙 제2조'."""
    supplementary = aid.startswith("supp-")
    num, _, sub = aid.removeprefix("supp-").partition("-")
    label = f"제{num}조" + (f"의{sub}" if sub else "")
    return f"부칙 {label}" if supplementary else label


# ---------- 키워드 (BM25) ----------

_TOKEN = re.compile(r"[가-힣]+|[A-Za-z]+|\d+(?:[.,]\d+)*%?")


def tokenize(text: str) -> list[str]:
    out = []
    for t in _TOKEN.findall(text):
        if "가" <= t[0] <= "힣":
            out.append(t)
            out.extend(t[i : i + 2] for i in range(len(t) - 1))
        else:
            out.append(t.lower())
    return out


class BM25:
    def __init__(self, texts: list[str], k1: float = 1.5, b: float = 0.75):
        self.docs = [Counter(tokenize(t)) for t in texts]
        self.lens = [sum(d.values()) for d in self.docs]
        self.avg = (sum(self.lens) / len(self.lens)) if self.lens else 0
        df = Counter(tok for d in self.docs for tok in d)
        n = len(self.docs)
        self.idf = {tok: math.log(1 + (n - f + 0.5) / (f + 0.5)) for tok, f in df.items()}
        self.k1, self.b = k1, b

    def scores(self, query: str) -> list[float]:
        q = tokenize(query)
        out = []
        for d, length in zip(self.docs, self.lens):
            s = 0.0
            for tok in q:
                f = d.get(tok, 0)
                if f:
                    s += self.idf[tok] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * length / self.avg))
            out.append(s)
        return out


# ---------- 조각 ----------


@dataclass(frozen=True)
class Chunk:
    id: str
    scope: str  # 필터 키: 규정은 "{regulation_id}/{version}", 문서는 product_id
    text: str  # 임베딩 · BM25 대상
    result: dict  # 검색 결과로 돌려줄 값


def regulation_chunks(root: Path) -> list[Chunk]:
    out = []
    for rid, versions in reg.list_versions(root).items():
        for v in versions:
            doc = reg.load(rid, v, root)
            title = doc["meta"].get("title", rid)
            for aid, a in doc["articles"].items():
                out.append(Chunk(
                    id=f"{rid}/{v}/{aid}",
                    scope=f"{rid}/{v}",
                    text=f"{title} > {article_label(aid)}({a['title']})\n{a['text']}",
                    result={"uri": reg.uri(rid, v, aid), "regulation_id": rid, "version": v, "article_id": aid, **a},
                ))
    return out


def doc_chunks(root: Path) -> list[Chunk]:
    out = []
    for pid in docs.list_products(root):
        doc = docs.load(pid, root)
        name = doc["meta"].get("name", pid)
        for s in doc["sections"]:
            out.append(Chunk(
                id=f"{pid}#{s['no']}",
                scope=pid,
                text=f"{name} > {s['section']}\n{s['text']}",
                result={"uri": docs.uri(pid, s["no"]), "product_id": pid, "name": name, "section": s["section"],
                        "text": s["text"], "updated_at": doc["meta"].get("updated_at", "")},
            ))
    return out


def _digest(chunks: list[Chunk]) -> str:
    return hashlib.sha256("\n\n".join(f"{c.id}\n{c.text}" for c in chunks).encode()).hexdigest()


class Collection:
    """조각 묶음 하나의 BM25 + (있으면) Chroma 색인."""

    def __init__(self, name: str, loader: Callable[[], list[Chunk]], embedder: Embedder | None, client=None):
        self._name, self._loader, self._embed, self._client = name, loader, embedder, client
        self._digest = None
        self.chunks: list[Chunk] = []

    def refresh(self) -> None:
        chunks = self._loader()
        digest = _digest(chunks)
        if digest == self._digest:
            return
        self.chunks, self._bm25 = chunks, BM25([c.text for c in chunks])
        self._col = None
        if self._embed and chunks:
            col = self._client.create_collection(
                f"{self._name}-{uuid.uuid4().hex}", metadata={"hnsw:space": "cosine"}, embedding_function=None
            )
            col.add(
                ids=[c.id for c in chunks],
                embeddings=self._embed([c.text for c in chunks]),
                metadatas=[{"scope": c.scope} for c in chunks],
            )
            self._col = col
        self._digest = digest

    def keyword_scores(self, query: str, scopes: set[str]) -> dict[str, float]:
        scores = self._bm25.scores(query)
        return {c.id: s for s, c in zip(scores, self.chunks) if c.scope in scopes and s > 0}

    def vector_scores(self, query: str, scopes: set[str], n: int) -> dict[str, float]:
        res = self._col.query(
            query_embeddings=self._embed([query]), n_results=n, where={"scope": {"$in": sorted(scopes)}}
        )
        return {cid: 1 - dist for cid, dist in zip(res["ids"][0], res["distances"][0])}  # 코사인 유사도

    def search(self, query: str, scopes: set[str], k: int, mode: str) -> list[dict]:
        """mode: hybrid | vector | keyword. 의미 검색을 쓸 수 없으면 keyword로 내려간다."""
        if not query.strip():
            raise RegulationError("query가 비어 있습니다")
        self.refresh()
        n = sum(1 for c in self.chunks if c.scope in scopes)
        if not n:
            return []
        keyword = self.keyword_scores(query, scopes) if mode != "vector" else {}
        vec: dict[str, float] = {}
        if mode != "keyword" and self._col is not None:
            try:
                vec = self.vector_scores(query, scopes, min(n, max(k * 4, 20)))
            except Exception:
                log.warning("의미 검색 실패, 키워드 검색으로 대체합니다", exc_info=True)
        if vec and mode == "vector":
            combined = vec
        elif vec:
            v, kw = _normalize(vec), _normalize(keyword)
            combined = {cid: HYBRID_ALPHA * v.get(cid, 0) + (1 - HYBRID_ALPHA) * kw.get(cid, 0) for cid in v | kw}
        else:
            combined = keyword
        ranked = sorted(combined, key=lambda cid: -combined[cid])
        by_id = {c.id: c for c in self.chunks}
        return [by_id[cid].result for cid in ranked[:k]]


def _normalize(scores: dict[str, float]) -> dict[str, float]:
    """후보 안에서 0~1로 정규화 (min-max)."""
    if not scores:
        return {}
    lo, hi = min(scores.values()), max(scores.values())
    return {cid: (s - lo) / (hi - lo) if hi > lo else 1.0 for cid, s in scores.items()}


class SearchIndex:
    def __init__(
        self,
        embedder: Embedder | None,
        regulations_root: Path = reg.REGULATIONS_DIR,
        docs_root: Path = docs.PRODUCT_DOCS_DIR,
    ):
        client = None
        if embedder:
            import chromadb
            from chromadb.config import Settings

            client = chromadb.EphemeralClient(settings=Settings(anonymized_telemetry=False))
        self.regulations_root, self.docs_root = regulations_root, docs_root
        self.regulations = Collection("regulations", lambda: regulation_chunks(regulations_root), embedder, client)
        self.docs = Collection("product-docs", lambda: doc_chunks(docs_root), embedder, client)

    def search_regulations(
        self, query: str, regulation_id: str | None = None, version: str | None = None, k: int = TOP_K, mode: str = "hybrid"
    ) -> list[dict]:
        scopes = {f"{rid}/{v}" for rid, v in reg.resolve_scope(regulation_id, version, self.regulations_root)}
        return self.regulations.search(query, scopes, k, mode)

    def search_docs(self, query: str, product_id: str | None = None, k: int = TOP_K, mode: str = "hybrid") -> list[dict]:
        if product_id is not None:
            docs.doc_path(product_id, self.docs_root)  # 허용 범위 검사
            scopes = {product_id}
        else:
            scopes = set(docs.list_products(self.docs_root))
        return self.docs.search(query, scopes, k, mode)


_index: SearchIndex | None = None


def index() -> SearchIndex:
    """서버가 쓰는 색인. OPENAI_API_KEY가 있으면 혼합 검색, 없으면 BM25만."""
    global _index
    if _index is None:
        _index = SearchIndex(openai_embedder if os.environ.get("OPENAI_API_KEY") else None)
    return _index
