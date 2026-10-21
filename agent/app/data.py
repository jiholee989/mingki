"""레포 루트 data/ 읽기. 로컬 조회 전용 — 실제 운영에서는 MCP 서버가 같은 파일을 읽는다.

포맷 규칙은 data/regulations/README.md, data/business/README.md 참고.
"""

import json
import os
import re
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(os.getenv("RIPPLE_DATA_DIR", Path(__file__).resolve().parents[2] / "data"))

# data/regulations/README.md의 조항 헤더 정규식
_ARTICLE = re.compile(r"^### (부칙 )?제(\d+)조(?:의(\d+))?\((.+)\)$")


def article_id(supplementary: bool, num: str, sub: str | None) -> str:
    aid = f"{num}-{sub}" if sub else num
    return f"supp-{aid}" if supplementary else aid


@lru_cache
def load_regulation(regulation_id: str, version: str, data_dir: Path = DATA_DIR) -> dict:
    """{"meta": {...frontmatter}, "articles": {article_id: {"title", "text"}}}"""
    raw = (data_dir / "regulations" / regulation_id / f"{version}.md").read_text(encoding="utf-8")
    _, front, body = raw.split("---", 2)
    meta = dict(line.split(": ", 1) for line in front.strip().splitlines())

    articles: dict[str, dict] = {}
    current = None
    for line in body.splitlines():
        if m := _ARTICLE.match(line):
            current = article_id(bool(m[1]), m[2], m[3])
            articles[current] = {"title": m[4], "lines": []}
        elif line.startswith("## ") or line.startswith("# "):
            current = None
        elif current:
            articles[current]["lines"].append(line)
    return {
        "meta": meta,
        "articles": {k: {"title": v["title"], "text": "\n".join(v["lines"]).strip()} for k, v in articles.items()},
    }


@lru_cache
def load_business(name: str, data_dir: Path = DATA_DIR) -> list[dict]:
    return json.loads((data_dir / "business" / f"{name}.json").read_text(encoding="utf-8"))


def list_regulations(data_dir: Path = DATA_DIR) -> list[dict]:
    """정답지 대신 규정 파일의 메타데이터에서 목록을 만든다."""
    return [load_regulation(path.parent.name, path.stem, data_dir)["meta"]
            for path in sorted((data_dir / "regulations").glob("*/*.md"))]


def active_rules(rows: list[dict], as_of: str) -> list[dict]:
    """종료일은 포함한다. 종료·미시행 행을 현재 규칙으로 사용하지 않는다."""
    from datetime import date
    point = date.fromisoformat(as_of)
    return [row for row in rows
            if date.fromisoformat(row["effectiveFrom"]) <= point
            and (not row.get("effectiveTo") or point <= date.fromisoformat(row["effectiveTo"]))]


def unended_rules(rows: list[dict], as_of: str) -> list[dict]:
    """as_of에 끝나지 않은 행: 지금 유효한 행과 반영 예정(시작 전) 행. 이미 반영한 새 규칙을 알아볼 때 쓴다."""
    from datetime import date
    point = date.fromisoformat(as_of)
    return [row for row in rows if not row.get("effectiveTo") or point <= date.fromisoformat(row["effectiveTo"])]
