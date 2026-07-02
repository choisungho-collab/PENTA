-- ═══════════════════════════════════════════════════════════════════
--  로그인 전체 복구 (한 번 실행으로 로그인 스택 전부 보장 - 여러 번 실행 안전)
--  Supabase -> SQL Editor 에 전체 붙여넣고 Run
-- ═══════════════════════════════════════════════════════════════════

-- 0) 암호 확장 (digest / gen_random_bytes)
create extension if not exists pgcrypto with schema extensions;

-- 1) 테이블
create table if not exists login_codes (
  code     text primary key,
  puuid    text not null,
  created  timestamptz default now(),
  used     boolean default false
);
create table if not exists sessions (
  token    text primary key,
  puuid    text not null,
  created  timestamptz default now(),
  seen     timestamptz default now()
);
alter table login_codes enable row level security;
alter table sessions    enable row level security;

-- 2) 로그인 RPC 4종 (스키마 원본 그대로)
-- (기존에 반환 타입이 다른 구버전 함수가 있으면 교체가 막히므로 먼저 제거 — 42P13 방지)
drop function if exists issue_login_code(text, text, text);
drop function if exists exchange_login_code(text);
drop function if exists session_whoami(text);
drop function if exists end_session(text);


create or replace function issue_login_code(p_puuid text, p_secret text, p_code text)
returns void language plpgsql security definer set search_path = public, extensions as $$
declare h text; ok boolean;
begin
  h := encode(digest(p_secret, 'sha256'), 'hex');
  select (h = any(device_secrets)) into ok from identities where puuid = p_puuid;
  if not coalesce(ok, false) then raise exception 'unauthorized'; end if;
  delete from login_codes where created < now() - interval '10 minutes';
  insert into login_codes(code, puuid) values (p_code, p_puuid)
    on conflict (code) do nothing;
end; $$;

create or replace function exchange_login_code(p_code text)
returns jsonb language plpgsql security definer set search_path = public, extensions as $$
declare r record; tok text; nm text; ic int;
begin
  select * into r from login_codes
    where code = p_code and used = false and created > now() - interval '10 minutes';
  if not found then raise exception 'invalid or expired code'; end if;
  update login_codes set used = true where code = p_code;
  tok := encode(gen_random_bytes(24), 'hex');
  insert into sessions(token, puuid) values (tok, r.puuid);
  select name, icon into nm, ic from identities where puuid = r.puuid;
  return jsonb_build_object('token', tok, 'puuid', r.puuid, 'name', nm, 'icon', ic);
end; $$;

create or replace function session_whoami(p_token text)
returns jsonb language plpgsql security definer set search_path = public as $$
declare r record; nm text; ic int;
begin
  select * into r from sessions where token = p_token;
  if not found then return null; end if;
  update sessions set seen = now() where token = p_token;
  select name, icon into nm, ic from identities where puuid = r.puuid;
  return jsonb_build_object('puuid', r.puuid, 'name', nm, 'icon', ic);
end; $$;

create or replace function end_session(p_token text)
returns void language sql security definer set search_path = public as $$
  delete from sessions where token = p_token;
$$;


-- 3) 확인 (Run 후 아래 줄의 결과가 에러 없이 나오면 성공)
select 'login stack OK' as status,
  (select count(*) from login_codes) as codes,
  (select count(*) from sessions)    as sessions;
