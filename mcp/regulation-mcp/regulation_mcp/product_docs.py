"""상품설명서 · 업무 절차 문서 읽기 · 섹션 분리. MCP와 무관한 순수 함수.

포맷 규칙은 data/product-docs/README.md 를 따른다.
접근 범위: PRODUCT_DOCS_DIR/{product_id}.md 만 읽는다 (README, eval/, docs/ 는 볼 수 없다).
"""

import os
import re
from functools import lru_cache
from pathlib import Path

from regulation_mcp.regulations import RegulationError, split_frontmatter


def _default_dir() -> Path:
    # 로컬: mcp/regulation-mcp/regulation_mcp/ → 레포 루트 data/product-docs. Docker에서는 환경 변수로 준다.
    return Path(__file__).resolve().parents[3] / "data" / "product-docs"


PRODUCT_DOCS_DIR = Path(os.environ.get("PRODUCT_DOCS_DIR") or _default_dir()).resolve()

_PRODUCT_ID = re.compile(r"^P\d{3}$")
_SECTION = re.compile(r"^## (?:\d+\.\s*)?(.+)$")


class ProductDocError(RegulationError):
    """Agent에게 그대로 보여줄 수 있는 입력 오류."""


def uri(product_id: str, section_no: int | None = None) -> str:
    return f"doc://{product_id}" + (f"#{section_no}" if section_no else "")


def list_products(root: Path = PRODUCT_DOCS_DIR) -> list[str]:
    if not root.is_dir():
        return []
    return sorted(p.stem for p in root.glob("*.md") if _PRODUCT_ID.match(p.stem))


def doc_path(product_id: str, root: Path = PRODUCT_DOCS_DIR) -> Path:
    """입력값으로 파일 경로를 만들되, 허용 범위(root/P000.md) 밖이면 거절한다."""
    if not _PRODUCT_ID.match(product_id):
        raise ProductDocError(f"잘못된 product_id: {product_id!r} (예: P001)")
    path = (root / f"{product_id}.md").resolve()
    if not path.is_relative_to(root.resolve()):
        raise ProductDocError("허용된 문서 폴더 밖입니다")
    if not path.is_file():
        raise ProductDocError(f"상품 문서가 없습니다: {product_id} (가능: {list_products(root)})")
    return path


@lru_cache
def load(product_id: str, root: Path = PRODUCT_DOCS_DIR) -> dict:
    """{"meta": {frontmatter}, "sections": [{"no", "section", "text"}]}"""
    meta, body = split_frontmatter(doc_path(product_id, root).read_text(encoding="utf-8"), f"{product_id}.md")

    sections: list[dict] = []
    for line in body.splitlines():
        if m := _SECTION.match(line):
            sections.append({"no": len(sections) + 1, "section": m[1].strip(), "lines": []})
        elif sections:
            sections[-1]["lines"].append(line)
    return {
        "meta": meta,
        "sections": [{"no": s["no"], "section": s["section"], "text": "\n".join(s["lines"]).strip()} for s in sections],
    }


def get_doc(product_id: str, root: Path = PRODUCT_DOCS_DIR) -> dict:
    doc = load(product_id, root)
    return {
        "uri": uri(product_id),
        "product_id": product_id,
        "name": doc["meta"].get("name", ""),
        "updated_at": doc["meta"].get("updated_at", ""),
        "sections": [{"uri": uri(product_id, s["no"]), "section": s["section"], "text": s["text"]} for s in doc["sections"]],
    }
