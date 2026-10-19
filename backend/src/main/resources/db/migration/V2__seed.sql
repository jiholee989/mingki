-- 시연용 계정 시드. 비밀번호는 모두 'password' (BCrypt).
-- 상품 · 규칙 · 계약은 BusinessDataLoader 가 data/business/*.json 에서 넣는다.
INSERT INTO users (username, password_hash, display_name, role) VALUES
 ('officer1', '$2a$10$m.6flkw75tg9L.pr50CYLOxyHgt4100Ois5paxWAKxiI4qkijw1rG', '김준법', 'OFFICER'),
 ('planner1', '$2a$10$m.6flkw75tg9L.pr50CYLOxyHgt4100Ois5paxWAKxiI4qkijw1rG', '박상품', 'OFFICER'),
 ('dev1',     '$2a$10$m.6flkw75tg9L.pr50CYLOxyHgt4100Ois5paxWAKxiI4qkijw1rG', '이개발', 'DEVELOPER'),
 ('dev2',     '$2a$10$m.6flkw75tg9L.pr50CYLOxyHgt4100Ois5paxWAKxiI4qkijw1rG', '최개발', 'DEVELOPER');

