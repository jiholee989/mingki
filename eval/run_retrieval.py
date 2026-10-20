"""검색 평가: 키워드(BM25) vs 의미(Vector DB) vs 혼합.

eval/retrieval.yaml 의 질의로 recall@k, MRR, not_top1 위반 건수를 잰다.
의미 · 혼합 검색은 OPENAI_API_KEY가 있을 때만 실행한다 (임베딩 호출 비용 발생, 1회 수백 건).

실행 (레포 루트에서):
    uv run --project mcp/regulation-mcp --with pyyaml python eval/run_retrieval.py
"""

import os
import sys
from collections import defaultdict
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp" / "regulation-mcp"))

from regulation_mcp.search import TOP_K, SearchIndex, openai_embedder  # noqa: E402

SPEC = yaml.safe_load((Path(__file__).parent / "retrieval.yaml").read_text(encoding="utf-8"))
K = SPEC["k"]


def run_regulation(index, q, mode):
    rid, _, version = (q.get("scope") or "").partition("/")
    hits = index.search_regulations(q["query"], rid or None, version or None, k=TOP_K, mode=mode)
    return [f"{h['regulation_id']}/{h['article_id']}" for h in hits]


def run_doc(index, q, mode):
    hits = index.search_docs(q["query"], q.get("scope"), k=TOP_K, mode=mode)
    return list(dict.fromkeys(h["product_id"] for h in hits))


def evaluate(index, mode):
    print(f"\n========== {mode} ==========")
    for name, items, run in (("규정", SPEC["regulation"], run_regulation), ("상품 문서", SPEC["product_docs"], run_doc)):
        hits, rr, violations, rows = 0, 0.0, 0, []
        by_type = defaultdict(lambda: [0, 0])
        for q in items:
            ranked = run(index, q, mode)
            rank = next((i + 1 for i, r in enumerate(ranked) if r in q["expected"]), None)
            hit = rank is not None and rank <= K
            violated = bool(ranked) and ranked[0] in q.get("not_top1", [])
            hits += hit
            rr += 1 / rank if rank else 0
            violations += violated
            t = by_type[q.get("type", "basic")]
            t[0] += hit
            t[1] += 1
            mark = ("hit " if hit else "MISS") + (" !top1" if violated else "")
            rows.append(f"  {q['id']} {mark:11} {', '.join(ranked[:K]):58} {q['query']}")
        n = len(items)
        types = " · ".join(f"{t} {h}/{c}" for t, (h, c) in by_type.items())
        print(f"[{name}] recall@{K} {hits}/{n} ({hits / n:.0%}) · MRR {rr / n:.2f} · not_top1 위반 {violations}  ({types})")
        print("\n".join(rows))


evaluate(SearchIndex(None), "keyword")
if os.environ.get("OPENAI_API_KEY"):
    index = SearchIndex(openai_embedder)
    evaluate(index, "vector")
    evaluate(index, "hybrid")
else:
    print("\n[vector · hybrid] OPENAI_API_KEY가 없어 건너뜀")
