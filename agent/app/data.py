"""레포 루트 data/ 읽기. mock 도구 전용 — 실제 운영에서는 MCP 서버가 같은 파일을 읽는다.

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


def article_label(aid: str) -> str:
    """'15-2' → '제15조의2', 'supp-2' → '부칙 제2조'"""
    prefix = "부칙 " if aid.startswith("supp-") else ""
    num, _, sub = aid.removeprefix("supp-").partition("-")
    return f"{prefix}제{num}조" + (f"의{sub}" if sub else "")


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
