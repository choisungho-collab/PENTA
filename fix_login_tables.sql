-- ═══════════════════════════════════════════════════════════════
--  로그인 복구 — login_codes / sessions 테이블 생성
--  원인: issue_login_code RPC 가 넣으려는 login_codes 테이블이 DB에 없어
--        (42P01 relation "login_codes" does not exist) 로그인 코드 발급 실패.
--  이 스크립트를 Supabase → SQL Editor 에 붙여넣고 Run 하면 됩니다.
--  (여러 번 실행해도 안전 — if not exists)
-- ═══════════════════════════════════════════════════════════════

-- 1) 로그인 코드 테이블 (레코더 Archive 버튼 → 일회용 코드 → 웹에서 토큰 교환)
create table if not exists login_codes (
  code     text primary key,
  puuid    text not null,
  created  timestamptz default now(),
  used     boolean default false
);

-- 2) 세션 토큰 테이블 (교환된 토큰 보관 → 페이지마다 신원 검증)
create table if not exists sessions (
  token    text primary key,
  puuid    text not null,
  created  timestamptz default now(),
  seen     timestamptz default now()
);

-- 3) 코드/토큰은 비밀값 → 직접 접근 차단.
--    접근은 security definer RPC(issue/exchange/whoami/end_session)로만 이뤄지고,
--    이 함수들은 소유자 권한으로 실행돼 RLS 를 우회하므로 로그인은 정상 동작합니다.
alter table login_codes enable row level security;
alter table sessions    enable row level security;

-- 확인용(선택): 아래 두 줄을 실행하면 테이블이 생겼는지 보입니다.
-- select count(*) as login_codes_ok from login_codes;
-- select count(*) as sessions_ok    from sessions;
