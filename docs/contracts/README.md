# 계약 예시

`docs/BACKEND_API.md` 10절의 요청 · 응답 예시. 값은 `data/business`(#19)와 정답지(#21) DSR 시나리오를 따른다.

각 영역 테스트가 이 파일을 그대로 읽는다. 백엔드는 요청 예시를 받아들이는지, Agent · MCP · 프론트는 응답 예시를 처리하는지 확인한다. 모양을 바꾸려면 이 파일과 10절을 같은 PR로 고친다.

| 파일 | 방향 | API |
|---|---|---|
| `proposals.put.json` | Agent → Spring | `PUT {callbackBaseUrl}/proposals` |
| `review.post.json` | 화면 → Spring | `POST /api/ai/tasks/{id}/review` |
| `apply.post.json` | business-mcp → Spring | `POST /internal/product-rules/versions` |
| `apply.job.json` | Spring → business-mcp · Agent | `GET /internal/jobs/{jobId}` 결과 |
| `rule-keys.get.json` | Spring → business-mcp | `GET /internal/product-rules/keys` |
| `contract-impact.get.json` | Spring → business-mcp | `GET /internal/contracts/impact?dsrFrom=0.35&dsrTo=0.40&appliedBefore=2026-12-01` |
