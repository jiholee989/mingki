"""code-mcp와 공유하는 @@ file:line @@ 형식. 승인 범위 밖 수정은 거부한다."""

def validate_diff(diff, specs):
    allowed = {}
    for spec in specs:
        allowed.setdefault(spec.location, set()).add(spec.snippet.strip())
    if not diff.startswith("@@ "):
        raise ValueError("수정안은 @@ file:line @@ 형식이어야 합니다")
    covered = set()
    for block in diff.split("@@ ")[1:]:
        header, sep, body = block.partition(" @@\n")
        if not sep or header not in allowed or header in covered:
            raise ValueError("승인되지 않았거나 중복된 수정 위치입니다")
        lines = body.rstrip("\n").splitlines()
        if not lines or any(not line.startswith(("-", "+")) for line in lines):
            raise ValueError("수정 블록에는 삭제(-)·추가(+) 행만 허용합니다")
        old = "\n".join(line[1:] for line in lines if line.startswith("-"))
        new = "\n".join(line[1:] for line in lines if line.startswith("+"))
        if old.strip() not in allowed[header] or old == new or not new.strip():
            raise ValueError("기존 코드가 근거와 다르거나 수정 내용이 없습니다")
        covered.add(header)
    if covered != set(allowed):
        raise ValueError("수정안에서 빠진 승인 위치가 있습니다")
