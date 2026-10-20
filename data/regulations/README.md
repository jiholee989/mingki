# 규정 원문 (가상)

시연용 가상 규정입니다. `regulation-mcp`의 `diff_versions` · `search_regulation` · Resource가 이 파일을 원문으로 씁니다.

## 파일 구조

```
data/regulations/
  {regulation_id}/
    {version}.md
```

| regulation_id | 제목 | 버전 |
|---|---|---|
| `credit-loan-ops` | 개인신용대출 운영기준 | v3 (2024-01-01), v4 (2026-12-01) |
| `dsr-management` | 가계대출 DSR 관리기준 | v2 (2025-07-01) |
| `consumer-explanation` | 금융소비자 설명의무 기준 | v1 (2024-03-25) |
| `senior-protection` | 고령 금융소비자 보호기준 | v1 (2025-01-01) |

규정끼리 서로 참조합니다(예: DSR 관리기준 제8조 → 운영기준 제8조). 이전 버전이 없는 규정은 `previous_version`을 적지 않습니다. 삭제된 조항은 번호를 남기고 `### 제N조(삭제)`로 둡니다.

## 포맷 규칙

파서가 결정적으로 읽을 수 있도록 다음 규칙을 지킵니다.

1. **frontmatter**: `regulation_id`, `title`, `version`, `effective_from`(YYYY-MM-DD), `previous_version`, `fictional`
2. **장**: `## 제N장 제목`. 구조 표시용이며 조항 ID에는 들어가지 않습니다.
3. **조항**: `### 제N조(제목)` 또는 `### 제N조의M(제목)`. 다음 `###` 또는 `##` 전까지가 조항 본문입니다.
4. **부칙**: `## 부칙` 아래 `### 부칙 제N조(제목)`.
5. **항 · 호**: 항은 `①②③`, 호는 `1.` 목록. 조항 안에서만 씁니다.
6. 조항을 새로 넣을 때는 기존 번호를 밀지 않고 `제N조의M`으로 끼워 넣습니다. 그래야 신·구 버전에서 같은 조항이 같은 ID를 갖습니다.

조항 헤더 정규식:

```
^### (부칙 )?제(\d+)조(?:의(\d+))?\((.+)\)$
```

## 조항 ID와 Resource URI

| 헤더 | article_id | Resource URI |
|---|---|---|
| `### 제15조(고령자 기준)` | `15` | `reg://credit-loan-ops/v4/15` |
| `### 제15조의2(고령자 설명 확인)` | `15-2` | `reg://credit-loan-ops/v4/15-2` |
| `### 부칙 제2조(경과조치)` | `supp-2` | `reg://credit-loan-ops/v4/supp-2` |

이 폴더는 Agent가 MCP로 보는 원문입니다. Vector DB에는 `{version}.md`만 색인하고 이 README는 넣지 않습니다. 변경 내용 · 정답은 `eval/`에 둡니다.
