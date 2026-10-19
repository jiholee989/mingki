-- 시연용 시드. 비밀번호는 모두 'password' (BCrypt).
INSERT INTO users (username, password_hash, display_name, role) VALUES
 ('dev1',  '$2a$10$m.6flkw75tg9L.pr50CYLOxyHgt4100Ois5paxWAKxiI4qkijw1rG', '김개발', 'DEVELOPER'),
 ('dev2',  '$2a$10$m.6flkw75tg9L.pr50CYLOxyHgt4100Ois5paxWAKxiI4qkijw1rG', '이개발', 'DEVELOPER'),
 ('lead1', '$2a$10$m.6flkw75tg9L.pr50CYLOxyHgt4100Ois5paxWAKxiI4qkijw1rG', '박리드', 'LEAD');

INSERT INTO products (id, name, type) VALUES
 ('L001', '직장인 신용대출', 'credit'),
 ('L002', '시니어 안심 신용대출', 'credit'),
 ('L003', '청년 전세자금대출', 'jeonse');

-- 규정 v3 기준 적용값 (시연: 운영기준 v4 에서 SENIOR_AGE 65 -> 60, DSR_LIMIT 0.40 -> 0.35 로 변경될 예정)
INSERT INTO product_rules (product_id, rule_key, value, value_type, regulation_id, regulation_article, effective_from) VALUES
 ('L001', 'SENIOR_AGE',          '65',   'number', 'OPS-GUIDE', '제15조', '2025-01-01'),
 ('L002', 'SENIOR_AGE',          '65',   'number', 'OPS-GUIDE', '제15조', '2025-01-01'),
 ('L003', 'SENIOR_AGE',          '65',   'number', 'OPS-GUIDE', '제15조', '2025-01-01'),
 ('L001', 'DSR_LIMIT',           '0.40', 'number', 'DSR-STD',   '제3조',  '2025-01-01'),
 ('L002', 'DSR_LIMIT',           '0.40', 'number', 'DSR-STD',   '제3조',  '2025-01-01'),
 ('L001', 'PREPAY_FEE_RATE_MAX', '1.5',  'number', 'LOAN-OPS',  '제12조', '2025-01-01'),
 ('L002', 'PREPAY_FEE_RATE_MAX', '1.5',  'number', 'LOAN-OPS',  '제12조', '2025-01-01'),
 ('L003', 'PREPAY_FEE_RATE_MAX', '1.2',  'number', 'LOAN-OPS',  '제12조', '2025-01-01'),
 ('L001', 'OVERDUE_SPREAD_MAX',  '3.0',  'number', 'LOAN-OPS',  '제15조', '2025-01-01'),
 ('L002', 'OVERDUE_SPREAD_MAX',  '3.0',  'number', 'LOAN-OPS',  '제15조', '2025-01-01'),
 ('L003', 'OVERDUE_SPREAD_MAX',  '3.0',  'number', 'LOAN-OPS',  '제15조', '2025-01-01'),
 ('L003', 'MAX_AGE',             '34',   'number', 'YOUTH-JEONSE', '제2조', '2025-01-01'),
 ('L003', 'MAX_INCOME',          '50000000', 'number', 'YOUTH-JEONSE', '제2조', '2025-01-01');

-- 고령자 기준 변경 시 경과조치 확인용 계약 (60~64세 구간이 핵심)
INSERT INTO loan_contracts (product_id, customer_ref, customer_age, principal, rate_pct, contracted_at, maturity_at) VALUES
 ('L001', 'C-0001', 42, 30000000, 5.20, '2025-03-10', '2028-03-10'),
 ('L001', 'C-0002', 61, 20000000, 5.80, '2025-06-01', '2027-06-01'),
 ('L001', 'C-0003', 64, 15000000, 6.10, '2025-09-15', '2027-09-15'),
 ('L002', 'C-0004', 67, 10000000, 6.50, '2025-02-20', '2027-02-20'),
 ('L002', 'C-0005', 70, 8000000,  6.80, '2025-11-05', '2027-11-05'),
 ('L003', 'C-0006', 29, 120000000, 3.90, '2025-04-01', '2027-04-01'),
 ('L003', 'C-0007', 33, 100000000, 3.95, '2025-08-12', '2027-08-12');
