"""data/regulations 형식 검사. 데이터가 늘어날 때의 안전망.

파서는 형식이 어긋난 조항을 오류 없이 건너뛴다. 그래서 실제 데이터 전체를 읽어 조용히 빠지는 것이 없는지 본다.
규정 파일을 추가 · 수정하면 이 테스트로 확인한다:  uv run pytest tests/test_data_format.py -q
"""

import re
from datetime import date

import pytest

from regulation_mcp import regulations as reg

ROOT = reg.REGULATIONS_DIR
FILES = sorted(ROOT.glob("*/*.md"))
REQUIRED = ("regulation_id", "title", "version", "effective_from")


def _id(path):
    return f"{path.parent.name}/{path.name}"


def test_data_exists():
    assert reg.list_versions(), f"규정 원문이 없습니다: {ROOT}"


@pytest.mark.parametrize("path", FILES, ids=_id)
def test_file_is_readable_by_parser(path):
    # 폴더 이름(규정 ID)과 파일 이름(v{N}.md)이 파서 규칙에 맞아야 목록 · 검색에 나온다
    assert re.fullmatch(r"[a-z0-9][a-z0-9-]*", path.parent.name), "폴더 이름은 소문자 · 숫자 · 하이픈 (예: credit-loan-ops)"
    assert re.fullmatch(r"v\d+", path.stem), "파일 이름은 v{N}.md (예: v4.md)"


@pytest.mark.parametrize("path", FILES, ids=_id)
def test_frontmatter(path):
    rid, version = path.parent.name, path.stem
    meta = reg.load(rid, version)["meta"]
    missing = [k for k in REQUIRED if not meta.get(k)]
    assert not missing, f"frontmatter 필수 항목 없음: {missing}"
    assert meta["regulation_id"] == rid, "frontmatter regulation_id와 폴더 이름이 다름"
    assert meta["version"] == version, "frontmatter version과 파일 이름이 다름"
    date.fromisoformat(meta["effective_from"])  # YYYY-MM-DD

    prev = meta.get("previous_version")
    versions = reg.list_versions()[rid]
    if prev:
        assert int(prev[1:]) < int(version[1:]), "previous_version이 현재 버전보다 새 버전"
        # 가장 오래된 버전은 그 이전 원문이 없어도 된다 (예: credit-loan-ops v3 → v2 원문은 데이터에 없음)
        if version != versions[0]:
            assert prev in versions, f"previous_version {prev} 원문이 없음 (있는 버전: {versions})"
    elif version != versions[0]:
        pytest.fail(f"previous_version이 없음. diff_versions가 비교 대상을 찾지 못한다 (있는 버전: {versions})")


@pytest.mark.parametrize("path", FILES, ids=_id)
def test_every_article_header_is_parsed(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    headers = [ln for ln in lines if ln.startswith("### ")]
    assert headers, "조항(### 제N조(제목))이 하나도 없음"
    bad = [h for h in headers if not reg.ARTICLE.match(h)]
    assert not bad, f"형식이 틀려 조용히 빠지는 조항: {bad} (형식: ### 제N조(제목) · ### 제N조의M(제목) · ### 부칙 제N조(제목))"

    ids = [reg.article_id(bool(m[1]), m[2], m[3]) for m in map(reg.ARTICLE.match, headers)]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    assert not dup, f"같은 조항 번호가 두 번 나옴 (뒤의 것이 앞의 것을 덮어씀): {dup}"
