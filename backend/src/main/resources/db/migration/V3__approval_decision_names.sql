-- 요건 확정 기록의 decision 을 요청 값(CONFIRMED · HELD)과 같게 맞춘다.
ALTER TABLE approvals DROP CONSTRAINT approvals_decision_check;
UPDATE approvals SET decision = 'CONFIRMED' WHERE decision = 'CONFIRM';
UPDATE approvals SET decision = 'HELD'      WHERE decision = 'HOLD';
ALTER TABLE approvals ADD CONSTRAINT approvals_decision_check
    CHECK (decision IN ('CONFIRMED', 'HELD', 'APPROVE', 'REJECT', 'REQUEST_CHANGES'));
