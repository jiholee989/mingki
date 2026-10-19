"""design: plan → worker × 파일 묶음 (Send) → merge."""

from collections import defaultdict
from datetime import timedelta

from langgraph.types import Send

from app.schemas import Bundle, ChangeSpec, Contract, Event, PatchResult, Plan, PlanItem
from app.state import RippleState

MAX_ROUND = 2


def _change_type(spec: ChangeSpec) -> str:
    if spec.kind == "db":
        return "db"
    if spec.kind == "new":
        return "new"
    if spec.kind == "code" and any(op in spec.snippet for op in ("<", ">")):
        return "logic"
    return "value"


def _retryable(patch: PatchResult | None) -> bool:
    return patch is not None and patch.status in ("patch_failed", "conflict") and patch.round < MAX_ROUND


def make_plan(tools):
    """위치별 유형, 공유 계약, 파일 묶음, 의존 순서. 재작업 시에는 바뀐 묶음·실패 묶음만 pending."""

    def plan(state: RippleState) -> dict:
        specs = [s for s in state["change_specs"] if s.is_target]
        existing = {b.id: b for b in state.get("bundles", [])}
        patches = {p.bundle_id: p for p in state.get("code_patches", [])}

        by_file: dict[str, list[ChangeSpec]] = defaultdict(list)
        for s in specs:
            by_file[s.file].append(s)

        items = [PlanItem(spec_id=s.id, change_type=_change_type(s)) for s in specs]
        types = {i.spec_id: i.change_type for i in items}

        bundles, pending = [], []
        for file, file_specs in by_file.items():
            bid = f"B:{file}"
            spec_ids = sorted(s.id for s in file_specs)
            kinds = {types[sid] for sid in spec_ids}
            change_type = next(t for t in ("db", "new", "logic", "value") if t in kinds or t == "value")
            bundle = Bundle(id=bid, files=[file], spec_ids=spec_ids, change_type=change_type,
                            stage=0 if change_type == "db" else 1)
            bundles.append(bundle)
            old = existing.get(bid)
            if old is None or old.spec_ids != spec_ids or _retryable(patches.get(bid)):
                pending.append(bid)

        contracts = [
            Contract(name="policy", kind="function_signature",
                     definition="policy(key: str, as_of: date) -> Any  # 버전 있는 config/policy.yaml 조회"),
            *[Contract(name=r.target, kind="config_key",
                       definition=f"{r.target}: [{{value: {r.old_value}}}, {{value: {r.new_value}, "
                                  f"effective_from: {r.effective_date}}}]")
              for r in state["requirements"] if r.change == "modified"],
            *[Contract(name=s.symbol, kind="function_signature",
                       definition=f"{s.symbol}(contract_id: str) -> bool  # {s.reason}")
              for s in specs if s.kind == "new"],
        ]
        return {
            "plan": Plan(items=items, contracts=contracts, bundles=bundles),
            "bundles": bundles,
            "pending_bundle_ids": pending,
            "events": [Event(node="plan", message=f"묶음 {len(bundles)}개, 작업 대상 {len(pending)}개")],
        }

    return plan


def _dispatch(state: RippleState) -> list[Send]:
    """pending 묶음 중 가장 앞 stage만 병렬로 보낸다 (③DB가 있으면 먼저 순차)."""
    pending = set(state.get("pending_bundle_ids", []))
    bundles = [b for b in state["bundles"] if b.id in pending]
    if not bundles:
        return []
    stage = min(b.stage for b in bundles)
    specs = {s.id: s for s in state["change_specs"]}
    patches = {p.bundle_id: p for p in state.get("code_patches", [])}
    sends = []
    for b in bundles:
        if b.stage != stage:
            continue
        prev = patches.get(b.id)
        sends.append(Send("worker", {
            "bundle": b,
            "specs": [specs[sid] for sid in b.spec_ids],
            "contracts": state["plan"].contracts,
            "requirements": state["requirements"],
            "feedback": prev.errors if prev else [],
            "round": prev.round if prev else 0,
        }))
    return sends


def route_after_plan(state: RippleState):
    return _dispatch(state) or "merge"


def route_after_merge(state: RippleState):
    return _dispatch(state) or "verify"


def _rewrite(spec: ChangeSpec, req) -> str:
    """위치 유형별 수정안. (LLM 자리, 유형별 프롬프트 예정 — 스텁은 공유 계약 형태만 맞춘다)"""
    eff = req.effective_date
    if spec.kind == "new":
        return f"def {spec.symbol}(contract_id: str) -> bool: raise NotImplementedError  # {req.article}"
    if spec.kind == "config":
        # 경과조치: 값을 덮어쓰지 않고 시행일 버전을 추가
        return f"{req.target}: [{{value: {req.old_value}}}, {{value: {req.new_value}, effective_from: {eff}}}]"
    if spec.kind == "product_rule":
        # data/business/README.md: 기존 행은 effective_to로 닫고 새 행 추가
        return f"{spec.snippet} effective_to={eff - timedelta(days=1)} / + 새 행 value={req.new_value} effective_from={eff}"
    if spec.kind == "ui":
        old_pct, new_pct = (f"{round(float(v) * 100)}%" for v in (req.old_value, req.new_value))
        return spec.snippet.replace(old_pct, new_pct)
    return f"{spec.snippet}  # → policy(\"{req.target}\", as_of=application_date)"


def make_worker(tools):
    """파일 묶음 하나의 패치 작성. (LLM 자리, 유형별 프롬프트 예정)"""

    def worker(inp: dict) -> dict:
        bundle = inp["bundle"]
        reqs = {r.id: r for r in inp["requirements"]}
        for f in bundle.files:
            tools.get_file(f)
        hunks = [f"@@ {s.file}:{s.line} @@\n-{s.snippet}\n+{_rewrite(s, reqs[s.requirement_id])}" for s in inp["specs"]]
        patch = PatchResult(
            bundle_id=bundle.id,
            files=bundle.files,
            locations=[s.location for s in inp["specs"]],
            diff="\n".join(hunks),
            round=inp["round"],
        )
        return {
            "code_patches": [patch],
            "events": [Event(node="worker", message=f"{bundle.id} 패치 작성 (round {inp['round']})")],
        }

    return worker


def merge(state: RippleState) -> dict:
    """방금 끝난 stage의 패치를 샌드박스 하나에 모은다. 파일이 겹치는 묶음은 충돌 처리."""
    pending = set(state.get("pending_bundle_ids", []))
    bundles = [b for b in state["bundles"] if b.id in pending]
    stage = min((b.stage for b in bundles), default=None)
    done = {b.id for b in bundles if b.stage == stage}

    file_owner: dict[str, str] = {}
    updated = []
    for p in state.get("code_patches", []):
        for f in p.files:
            file_owner.setdefault(f, p.bundle_id)
        if p.bundle_id not in done:
            continue
        conflict = any(file_owner[f] != p.bundle_id for f in p.files)
        updated.append(p.model_copy(update={
            "status": "conflict" if conflict else "merged",
            "errors": ["merge conflict"] if conflict else [],
        }))
    return {
        "code_patches": updated,
        "pending_bundle_ids": sorted(pending - done),
        "events": [Event(node="merge", message=f"{len(updated)}개 묶음 병합")],
    }
