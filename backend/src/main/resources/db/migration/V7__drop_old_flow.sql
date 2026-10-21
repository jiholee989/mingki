-- 단순화 전(코드 수정 · 요건 확정 · 역할) 흐름을 지운다 (docs/BACKEND_API.md 10.7).
-- 그 흐름의 흔적이 있는 작업은 통째로 지운다. 남은 작업과 업무 데이터는 그대로 둔다.

CREATE TEMP TABLE old_tasks ON COMMIT DROP AS
SELECT id FROM analysis_tasks WHERE status IN ('WAITING_REQUIREMENT_APPROVAL', 'HELD')
UNION SELECT task_id FROM approvals WHERE step <> 'REVIEW' OR decision NOT IN ('APPROVE', 'REJECT')
UNION SELECT task_id FROM change_specs
UNION SELECT task_id FROM code_patches
UNION SELECT task_id FROM test_cases
UNION SELECT task_id FROM deliveries WHERE kind <> 'RULE_VERSION'
UNION SELECT task_id FROM jobs WHERE type <> 'APPLY_RULE_VERSION' AND task_id IS NOT NULL;

-- jobs · work_tickets 는 approvals 를 cascade 없이 참조해서 작업보다 먼저 지운다
DELETE FROM jobs WHERE type <> 'APPLY_RULE_VERSION' OR task_id IN (SELECT id FROM old_tasks);
DROP TABLE work_tickets;
DELETE FROM analysis_tasks WHERE id IN (SELECT id FROM old_tasks);

DROP TABLE change_specs;
DROP TABLE code_patches;
DROP TABLE test_cases;
DROP TABLE db_migrations;

ALTER TABLE approvals DROP CONSTRAINT approvals_step_check;
ALTER TABLE approvals ADD CONSTRAINT approvals_step_check CHECK (step IN ('REVIEW'));
ALTER TABLE approvals DROP CONSTRAINT approvals_decision_check;
ALTER TABLE approvals ADD CONSTRAINT approvals_decision_check CHECK (decision IN ('APPROVE', 'REJECT'));

ALTER TABLE deliveries DROP CONSTRAINT deliveries_kind_check;
ALTER TABLE deliveries ADD CONSTRAINT deliveries_kind_check CHECK (kind IN ('RULE_VERSION'));

ALTER TABLE requirements DROP COLUMN status;
ALTER TABLE users DROP COLUMN role;
