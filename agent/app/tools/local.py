"""MCP 없이 샘플 원문·상품 JSON을 읽는다. 분석·제안은 실제 LLM이 담당한다."""

import re
from pathlib import Path
from app.data import DATA_DIR, active_rules, load_business, load_regulation, list_regulations
from app.tools.base import ToolBelt


def _camel(row):
    return {re.sub(r"_(\w)", lambda m: m[1].upper(), k): v for k, v in row.items()}


class LocalTools:
    is_local = True

    def __init__(self, data_dir: Path = DATA_DIR):
        self.data_dir = Path(data_dir)
        self.calls: list[tuple[str, dict]] = []

    def subset(self, *names: str) -> ToolBelt:
        return ToolBelt(self, frozenset(names))

    def close(self):
        pass

    def _log(self, name: str, **kwargs) -> None:
        self.calls.append((name, kwargs))

    def called(self, name: str) -> list[dict]:
        return [kw for n, kw in self.calls if n == name]

    def diff_versions(
        self, regulation_id: str, old_version: str, new_version: str
    ) -> dict:
        """원문 기준 결정적 diff. 바뀐 조항만 돌려준다 (자구 수정 포함 — 실질 여부 판단은 Agent 몫)."""
        self._log(
            "diff_versions",
            regulation_id=regulation_id,
            old_version=old_version,
            new_version=new_version,
        )
        old = load_regulation(regulation_id, old_version, self.data_dir)
        new = load_regulation(regulation_id, new_version, self.data_dir)
        changes = []
        for aid in dict.fromkeys([*old["articles"], *new["articles"]]):
            o, n = old["articles"].get(aid), new["articles"].get(aid)
            if o and n and o == n:
                continue
            changes.append(
                {
                    "article_id": aid,
                    "title": (n or o)["title"],
                    "change": "added"
                    if o is None
                    else "removed"
                    if n is None
                    else "modified",
                    "old_text": o["text"] if o else None,
                    "new_text": n["text"] if n else None,
                    "old_uri": f"reg://{regulation_id}/{old_version}/{aid}"
                    if o
                    else None,
                    "new_uri": f"reg://{regulation_id}/{new_version}/{aid}"
                    if n
                    else None,
                }
            )
        return {
            "regulation_id": regulation_id,
            "old_version": old_version,
            "new_version": new_version,
            "effective_from": new["meta"].get("effective_from"),
            "changes": changes,
        }

    def get_products(self) -> list[dict]:
        self._log("get_products")
        return [_camel(p) for p in load_business("products", self.data_dir)]

    def get_product_rules(
        self, rule_key: str | None = None, product_id: str | None = None, as_of: str | None = None
    ) -> list[dict]:
        """[{ruleId, productId, ruleKey, value, unit, effectiveFrom, effectiveTo}] — 상품명은 get_products"""
        self._log("get_product_rules", rule_key=rule_key, product_id=product_id, as_of=as_of)
        rows = [
            _camel(r)
            for r in load_business("product_rules", self.data_dir)
            if (rule_key is None or r["rule_key"] == rule_key)
            and (product_id is None or r["product_id"] == product_id)
        ]
        return active_rules(rows, as_of) if as_of else rows

    def list_articles(self, regulation_id: str, version: str) -> list[dict]:
        self._log("list_articles", regulation_id=regulation_id, version=version)
        regulation = load_regulation(regulation_id, version, self.data_dir)
        return [{"uri": f"reg://{regulation_id}/{version}/{aid}", "article_id": aid, "title": article["title"]}
                for aid, article in regulation["articles"].items()]

    def get_article(self, regulation_id: str, version: str, article_id: str) -> dict:
        self._log("get_article", regulation_id=regulation_id, version=version, article_id=article_id)
        article = load_regulation(regulation_id, version, self.data_dir)["articles"][article_id]
        return {"uri": f"reg://{regulation_id}/{version}/{article_id}", "article_id": article_id, **article}

    def get_regulation_context(self, regulation_id: str, version: str) -> dict:
        primary = load_regulation(regulation_id, version, self.data_dir)
        horizon = primary["meta"].get("effective_from", "9999-12-31")
        selected = {regulation_id: primary["meta"]}
        for meta in list_regulations(self.data_dir):
            rid = meta["regulation_id"]
            if rid == regulation_id or meta.get("effective_from", "") > horizon:
                continue
            if rid not in selected or meta["effective_from"] > selected[rid]["effective_from"]:
                selected[rid] = meta
        # 바뀐 규정의 조항만 준다. 다른 규정은 목록(related)만 주고, Agent가 필요할 때 골라 본다 (app/lookups.py)
        articles = [{**self.get_article(regulation_id, version, row["article_id"]), "regulation_id": regulation_id, "version": version}
                    for row in self.list_articles(regulation_id, version)]
        # 다른 규정은 조항 목차(번호 · 제목)까지 준다. 모델이 번호를 추측하지 않고 목차에서 고른다
        related = [{"regulation_id": rid, "version": meta["version"], "title": meta.get("title", ""),
                    "articles": [{"article_id": row["article_id"], "title": row["title"]}
                                 for row in self.list_articles(rid, meta["version"])]}
                   for rid, meta in selected.items() if rid != regulation_id]
        return {"articles": articles, "related": related, "data_gaps": []}

    def search_regulation(self, query: str, regulation_id: str | None = None, version: str | None = None) -> list[dict]:
        """로컬 모드용 단어 검색 (MCP 모드는 의미 검색). 조항 제목 · 본문에 검색어 단어가 많을수록 앞, 최대 5개."""
        self._log("search_regulation", query=query, regulation_id=regulation_id, version=version)
        latest = {}
        for meta in list_regulations(self.data_dir):
            rid = meta["regulation_id"]
            if (regulation_id and rid != regulation_id) or (version and meta["version"] != version):
                continue
            if rid not in latest or meta.get("effective_from", "") > latest[rid].get("effective_from", ""):
                latest[rid] = meta
        words = [w for w in query.split() if len(w) >= 2]
        hits = []
        for rid, meta in latest.items():
            for aid, article in load_regulation(rid, meta["version"], self.data_dir)["articles"].items():
                score = sum((article["title"] + " " + article["text"]).count(w) for w in words)
                if score:
                    hits.append((score, {"uri": f"reg://{rid}/{meta['version']}/{aid}", "regulation_id": rid,
                                         "version": meta["version"], "article_id": aid, **article}))
        return [hit for _, hit in sorted(hits, key=lambda h: -h[0])[:5]]

    def get_product_documents(self, product_ids: list[str]) -> dict:
        self._log("get_product_documents", product_ids=product_ids)
        documents, gaps = [], []
        for pid in product_ids:
            if not re.fullmatch(r"[A-Za-z0-9_-]+", pid):
                raise ValueError("상품 문서 ID 형식이 올바르지 않습니다")
            path = self.data_dir / "product-docs" / f"{pid}.md"
            if not path.is_file():
                gaps.append(f"{pid}: 상품 설명서·업무 절차 미조회")
                continue
            documents.append({"productId": pid, "uri": f"product-doc://{pid}",
                              "content": path.read_text(encoding="utf-8")})
        return {"documents": documents, "data_gaps": gaps}
