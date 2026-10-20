"""체크포인터. AGENT_CHECKPOINT_DB가 있으면 Postgres, 없으면 메모리(개발용)."""

import os

from app.graph import SERDE

CHECKPOINT_DB = os.getenv("AGENT_CHECKPOINT_DB")
SCHEMA = "agent"


def make_checkpointer(url=CHECKPOINT_DB):
    """승인 대기 중 Agent가 재시작돼도 같은 thread_id로 재개할 수 있게 상태를 DB에 둔다.

    백엔드와 같은 Postgres를 쓰되 agent 스키마에 테이블을 만든다. Flyway 테이블과 섞지 않는다.
    """
    if not url:
        return None
    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    # 연결 하나를 프로세스 수명 내내 쓰면 DB 재시작 · idle 끊김 뒤 모든 호출이 실패해 Agent 를 재시작해야 한다.
    # 풀은 꺼낼 때 연결을 검사해(check) 끊긴 연결을 버리고 새로 맺는다.
    pool = ConnectionPool(
        url,
        min_size=1,
        max_size=4,
        open=True,
        check=ConnectionPool.check_connection,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row,
                "options": f"-c search_path={SCHEMA}"},
    )
    with pool.connection() as conn:
        conn.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    saver = PostgresSaver(pool, serde=SERDE)
    saver.setup()
    return saver
