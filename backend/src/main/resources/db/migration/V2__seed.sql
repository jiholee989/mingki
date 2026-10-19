-- 시연용 시드 (가상 데이터). 비밀번호는 모두 'password' (BCrypt).
INSERT INTO users (username, password_hash, display_name, role) VALUES
 ('officer1', '$2a$10$m.6flkw75tg9L.pr50CYLOxyHgt4100Ois5paxWAKxiI4qkijw1rG', '김준법', 'OFFICER'),
 ('planner1', '$2a$10$m.6flkw75tg9L.pr50CYLOxyHgt4100Ois5paxWAKxiI4qkijw1rG', '박상품', 'OFFICER'),
 ('dev1',     '$2a$10$m.6flkw75tg9L.pr50CYLOxyHgt4100Ois5paxWAKxiI4qkijw1rG', '이개발', 'DEVELOPER'),
 ('dev2',     '$2a$10$m.6flkw75tg9L.pr50CYLOxyHgt4100Ois5paxWAKxiI4qkijw1rG', '최개발', 'DEVELOPER');

INSERT INTO products (id, name, type) VALUES
 ('L001', '직장인 신용대출',       'credit'),
 ('L002', '시니어 안심 신용대출',  'credit'),
 ('L003', '비상금 소액 신용대출',  'credit');

-- PROJECT.md 10절 시나리오 대상(SENIOR_AGE, DSR_LIMIT)과 함정(LTV_LIMIT, RETIREMENT_AGE)을 함께 둔다.
-- 함정: 값이 같지만 의미가 달라서 바꾸면 안 되는 키
INSERT INTO product_rules (product_id, rule_key, value, description, regulation_ref, effective_from) VALUES
 ('L001', 'SENIOR_AGE',     '65',   '고령자 기준 나이',            '운영기준 제15조', '2020-01-01'),
 ('L002', 'SENIOR_AGE',     '65',   '고령자 기준 나이',            '운영기준 제15조', '2020-01-01'),
 ('L003', 'SENIOR_AGE',     '65',   '고령자 기준 나이',            '운영기준 제15조', '2020-01-01'),
 ('L001', 'DSR_LIMIT',      '0.40', 'DSR 한도',                    '운영기준 제9조',  '2020-01-01'),
 ('L002', 'DSR_LIMIT',      '0.40', 'DSR 한도',                    '운영기준 제9조',  '2020-01-01'),
 ('L003', 'DSR_LIMIT',      '0.40', 'DSR 한도',                    '운영기준 제9조',  '2020-01-01'),
 ('L001', 'LTV_LIMIT',      '0.40', 'LTV 한도 (함정: DSR 와 무관)', '담보운영기준 제4조', '2020-01-01'),
 ('L002', 'RETIREMENT_AGE', '65',   '소득 추정용 은퇴 나이 (함정: 고령자 기준과 무관)', '소득산정지침 제3조', '2020-01-01');

-- 경과조치 확인용: 60~64세, 시행일(2026-12-01) 전 신청 건은 종전 기준 유지 대상
INSERT INTO loan_contracts (product_id, customer_ref, customer_age, principal, applied_at, maturity_at) VALUES
 ('L001', 'C-0001', 42, 30000000, '2025-03-10', '2028-03-10'),
 ('L001', 'C-0002', 61, 20000000, '2025-06-01', '2027-06-01'),
 ('L001', 'C-0003', 64, 15000000, '2026-09-15', '2028-09-15'),
 ('L002', 'C-0004', 62, 10000000, '2026-02-20', '2028-02-20'),
 ('L002', 'C-0005', 67,  8000000, '2025-11-05', '2027-11-05'),
 ('L003', 'C-0006', 59,  3000000, '2026-04-01', '2027-04-01'),
 ('L003', 'C-0007', 60,  5000000, '2026-08-12', '2027-08-12');
