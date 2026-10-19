# Rule Ripple · Frontend

Vue 3 + Vite + TypeScript + Tailwind CSS v4 + shadcn-vue

## 요구 사항

- Node 22 LTS (`.nvmrc`)
- pnpm 10

## 시작

```bash
pnpm install
pnpm dev          # http://localhost:5173, mock API 사용
```

## 명령

| 명령                                | 설명                                |
| ----------------------------------- | ----------------------------------- |
| `pnpm dev`                          | 개발 서버                           |
| `pnpm build`                        | 타입 검사 + 프로덕션 빌드 (`dist/`) |
| `pnpm typecheck`                    | 타입 검사만                         |
| `pnpm lint` / `pnpm lint:fix`       | ESLint                              |
| `pnpm format` / `pnpm format:check` | Prettier                            |
| `pnpm test` / `pnpm test:watch`     | Vitest                              |

## 환경 변수

| 변수            | 개발 기본값 | 설명                                                |
| --------------- | ----------- | --------------------------------------------------- |
| `VITE_API_BASE` | `/api`      | 백엔드 API 기본 경로                                |
| `VITE_USE_MOCK` | `true`      | `true`면 MSW가 API 요청을 가로채 가짜 데이터로 응답 |

실서버와 연결할 때는 `.env.development`에서 `VITE_USE_MOCK=false`로 바꾼다.

## 폴더 구조

```
src/
├─ domain/        # 도메인 타입 (요건·영향 위치·패치·검증·승인·작업 상태)
├─ api/           # 백엔드 호출 + 응답→도메인 변환. 백엔드 변경은 여기만 영향
├─ mocks/         # MSW 핸들러 + 시나리오 fixture
├─ stores/        # Pinia
├─ components/
│  ├─ ui/         # shadcn-vue 생성 컴포넌트 (pnpm dlx shadcn-vue@latest add <name>)
│  └─ domain/     # 도메인 데이터를 그리는 컴포넌트
├─ pages/         # 라우트 단위 화면
├─ router/
└─ composables/
```

## 규칙

- 화면과 컴포넌트는 `api/`를 통해서만 서버와 통신한다. `fetch`를 직접 쓰지 않는다.
- `components/ui/`는 shadcn-vue CLI로 추가하고, 필요하면 직접 수정한다.
- 라우터는 history 모드다. 배포 시 Spring에 SPA fallback(모든 경로 → `index.html`)이 필요하다.
