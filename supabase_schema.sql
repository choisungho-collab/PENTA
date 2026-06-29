-- ============================================================================
-- PENTA Supabase 스키마 (완전판) — Supabase SQL Editor 에 붙여넣고 실행
-- ============================================================================
-- 이 파일은 웹/녹화기 코드가 실제로 호출하는 테이블·컬럼·RPC 전체를 코드 사용처에서
-- 역추출해 재구성한 것입니다. 인증/소유자/로그인코드/세션/영상관리 계층까지 포함합니다.
--
-- ★★★ 라이브 DB 에 그대로 덮어쓰기 전에 반드시 대조하세요 ★★★
--   라이브에 이미 동작 중인 RPC 가 있다면, 그 내부 로직이 이 재구성본과 다를 수 있습니다.
--   먼저 Supabase 대시보드(Database → Functions)나 pg_dump 로 현재 정의를 뽑아 이 파일과 diff 한 뒤,
--   다른 부분만 적용하는 것을 권장합니다.
--
-- 이 파일의 성질:
--   - 비파괴적(idempotent): 기존 데이터 테이블을 drop 하지 않습니다.
--     (matches/group_stats/comments 는 create table IF NOT EXISTS, 컬럼은 add column IF NOT EXISTS)
--   - 따라서 빈 새 DB 를 처음부터 세울 때도, 운영 중 DB 에 누락분만 채울 때도 안전하게 실행됩니다.
--   - 함수는 create OR REPLACE 라서, 실행하면 라이브 RPC 를 이 정의로 "덮어씁니다" → 그래서 위 대조 경고가 중요.
--
-- 보안 모델 요약:
--   - 읽기(select)는 anon 공개. 쓰기 중 카운터/댓글은 정책으로 허용, 그 외는 RPC 로만.
--   - 신원 비밀키는 서버에 sha256 해시로만 저장. anon 은 identities/login_codes/sessions 를 직접 못 읽음.
--   - 소유권 행(owner_puuid)은 secret 검증을 통과한 upload_match(security definer)로만 생성됨.
--   - 익명 직접 insert 는 owner_puuid 가 NULL 일 때만 허용(남의 puuid 사칭 방지).
-- ============================================================================

create extension if not exists pgcrypto with schema extensions;   -- digest(), gen_random_bytes()

-- ───────────────────────────── 매치(시점별 행) ─────────────────────────────
-- 멀티 시점: 같은 게임(matchId)을 여러 명이 녹화하면 각각 다른 행(id 고유)으로 저장되고,
-- match_id(그룹키)로 묶인다. 좋아요/조회/댓글은 match_id 단위로 그룹 전체에 공유된다.
create table if not exists matches (
  id          text primary key,          -- 시점별 고유 행 id (matchId + 녹화자)
  match_id    text not null,             -- Riot matchId = 멀티 시점 그룹키
  players     jsonb,                     -- 참가자 카드(챔피언/KDA/CS/골드/아이템...)
  analysis    jsonb,                     -- 분석(골드 추이/오브젝트/킬 이벤트 등)
  map         text,                      -- "Summoner's Rift"
  matchup     text,
  length      text,                      -- "32:15"
  length_sec  int,
  type        text,                      -- queueId
  winner      int,                       -- 승리 팀 100/200
  saver       text,                      -- 녹화한 사람
  np          int,                       -- 참가자 수
  uploader    text,
  uploaded    text,
  video       text,
  thumb       text,
  replay      text,                      -- LoL은 없음(null)
  won         boolean,                   -- 녹화자 승패
  video_size  bigint,
  owner_puuid text,                      -- 소유자 puuid (upload_match 가 검증 후 세팅; 익명 업로드는 NULL)
  title       text                       -- 소유자가 단 제목(선택)
);
-- 운영 중 DB 에 위 두 컬럼이 없을 수 있으므로 보강(이미 있으면 무시됨)
alter table matches add column if not exists owner_puuid text;
alter table matches add column if not exists title       text;

create index if not exists matches_match_id_idx on matches(match_id);
create index if not exists matches_uploaded_idx on matches(uploaded desc);
create index if not exists matches_owner_idx    on matches(owner_puuid);

-- ───────────────────────── 그룹(게임) 단위 좋아요/조회 ─────────────────────────
create table if not exists group_stats (
  match_id text primary key,
  likes    int default 0,
  views    int default 0
);

-- ───────────────────────────── 그룹 단위 댓글 ─────────────────────────────
create table if not exists comments (
  id        bigserial primary key,
  match_id  text,                        -- Riot matchId(그룹 단위 댓글)
  author    text,
  body      text,
  created   text
);
create index if not exists comments_match_id_idx on comments(match_id);

-- ════════════════════════════ 인증/신원 계층 ════════════════════════════
-- Riot 클라이언트가 본인을 증명(Live Client/계정 API) → 녹화기가 기기 비밀키를 보유 →
-- Archive 클릭 시 일회용 로그인 코드 발급 → 웹이 코드를 토큰으로 교환 → 토큰으로 수정/삭제.

-- 신원: puuid → 기기 비밀키 해시
create table if not exists identities (
  puuid       text primary key,
  secret_hash text not null,             -- sha256(기기 비밀키) — 원문은 서버에 저장하지 않음
  name        text,                      -- "이름#태그"
  icon        int,
  created     timestamptz default now(),
  updated     timestamptz default now()
);

-- 일회용 로그인 코드 (Archive 클릭 시 발급, 10분 내 1회 교환)
create table if not exists login_codes (
  code     text primary key,
  puuid    text not null,
  created  timestamptz default now(),
  used     boolean default false
);

-- 세션 토큰 (브라우저 localStorage 에 보관)
create table if not exists sessions (
  token    text primary key,
  puuid    text not null,
  created  timestamptz default now(),
  seen     timestamptz default now()
);

-- ════════════════════════════════ RPC ════════════════════════════════
-- 모두 security definer (RLS 우회해 통제된 동작만 수행). search_path 고정은 보안 권장사항.

-- 좋아요/조회수 (match_id 기준 upsert) — anon 호출 OK
create or replace function like_group(mid text, delta int)
returns int language sql security definer set search_path = public as $$
  insert into group_stats(match_id, likes) values (mid, greatest(0, delta))
  on conflict(match_id) do update set likes = greatest(0, group_stats.likes + delta)
  returning likes;
$$;

create or replace function view_group(mid text)
returns void language sql security definer set search_path = public as $$
  insert into group_stats(match_id, views) values (mid, 1)
  on conflict(match_id) do update set views = group_stats.views + 1;
$$;

-- 신원 등록/갱신 (TOFU: 처음이면 청구, 이후엔 비밀키 일치해야 갱신) — 녹화기 호출
create or replace function register_identity(p_puuid text, p_secret text, p_name text default null, p_icon int default null)
returns boolean language plpgsql security definer set search_path = public, extensions as $$
declare h text; cur text;
begin
  if p_puuid is null or p_secret is null or length(p_secret) < 16 then
    raise exception 'bad identity args';
  end if;
  h := encode(digest(p_secret, 'sha256'), 'hex');
  select secret_hash into cur from identities where puuid = p_puuid;
  if cur is null then
    insert into identities(puuid, secret_hash, name, icon) values (p_puuid, h, p_name, p_icon);
    return true;
  elsif cur = h then
    update identities set name = coalesce(p_name, name), icon = coalesce(p_icon, icon), updated = now()
      where puuid = p_puuid;
    return true;
  else
    raise exception 'identity already claimed by another device';
  end if;
end; $$;

-- 매치 업로드 (소유자 박아 저장) — 녹화기 호출. owner_puuid 는 검증된 puuid 로 서버가 세팅.
create or replace function upload_match(p_puuid text, p_secret text, p_row jsonb)
returns text language plpgsql security definer set search_path = public, extensions as $$
declare h text; cur text;
begin
  h := encode(digest(p_secret, 'sha256'), 'hex');
  select secret_hash into cur from identities where puuid = p_puuid;
  if cur is null or cur <> h then raise exception 'unauthorized'; end if;

  insert into matches(
    id, match_id, players, analysis, map, matchup, length, length_sec, type,
    winner, saver, np, uploader, uploaded, video, thumb, replay, won, video_size, owner_puuid)
  values (
    p_row->>'id',
    p_row->>'match_id',
    p_row->'players',
    p_row->'analysis',
    p_row->>'map',
    p_row->>'matchup',
    p_row->>'length',
    nullif(p_row->>'length_sec','')::int,
    p_row->>'type',
    nullif(p_row->>'winner','')::int,
    p_row->>'saver',
    nullif(p_row->>'np','')::int,
    p_row->>'uploader',
    p_row->>'uploaded',
    p_row->>'video',
    p_row->>'thumb',
    p_row->>'replay',
    nullif(p_row->>'won','')::boolean,
    nullif(p_row->>'video_size','')::bigint,
    p_puuid)
  on conflict (id) do update set
    players    = excluded.players,
    analysis   = excluded.analysis,
    video      = excluded.video,
    thumb      = excluded.thumb,
    won        = excluded.won,
    video_size = excluded.video_size,
    uploaded   = excluded.uploaded,
    length     = excluded.length,
    length_sec = excluded.length_sec,
    winner     = excluded.winner;
  return p_row->>'id';
end; $$;

-- 로그인 코드 발급 (Archive 클릭 시) — 녹화기 호출. 오래된 코드 청소 후 발급.
create or replace function issue_login_code(p_puuid text, p_secret text, p_code text)
returns void language plpgsql security definer set search_path = public, extensions as $$
declare h text; cur text;
begin
  h := encode(digest(p_secret, 'sha256'), 'hex');
  select secret_hash into cur from identities where puuid = p_puuid;
  if cur is null or cur <> h then raise exception 'unauthorized'; end if;
  delete from login_codes where created < now() - interval '10 minutes';
  insert into login_codes(code, puuid) values (p_code, p_puuid)
    on conflict (code) do update set puuid = excluded.puuid, created = now(), used = false;
end; $$;

-- 코드 → 토큰 교환 (웹 페이지 로드 시) — 일회용·10분 만료
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

-- 토큰 검증 (매 페이지 로드) → 신원 반환, 무효면 null
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

-- 로그아웃
create or replace function end_session(p_token text)
returns void language sql security definer set search_path = public as $$
  delete from sessions where token = p_token;
$$;

-- 제목 수정 (소유자만) — 토큰→puuid 가 소유한 그룹 내 본인 행만
create or replace function update_match_meta(p_token text, p_match_id text, p_title text)
returns void language plpgsql security definer set search_path = public as $$
declare pu text;
begin
  select puuid into pu from sessions where token = p_token;
  if pu is null then raise exception 'not logged in'; end if;
  update matches set title = p_title where match_id = p_match_id and owner_puuid = pu;
end; $$;

-- 삭제 (소유자만) — 본인 행만
create or replace function delete_match(p_token text, p_match_id text)
returns void language plpgsql security definer set search_path = public as $$
declare pu text;
begin
  select puuid into pu from sessions where token = p_token;
  if pu is null then raise exception 'not logged in'; end if;
  delete from matches where match_id = p_match_id and owner_puuid = pu;
end; $$;

-- ════════════════════════════════ RLS ════════════════════════════════
alter table matches      enable row level security;
alter table group_stats  enable row level security;
alter table comments     enable row level security;
alter table identities   enable row level security;
alter table login_codes  enable row level security;
alter table sessions     enable row level security;

-- 읽기 공개
drop policy if exists m_sel on matches;       create policy m_sel on matches     for select using (true);
drop policy if exists g_sel on group_stats;   create policy g_sel on group_stats for select using (true);
drop policy if exists g_upd on group_stats;   create policy g_upd on group_stats for update using (true);
drop policy if exists g_ins on group_stats;   create policy g_ins on group_stats for insert with check (true);
drop policy if exists c_sel on comments;      create policy c_sel on comments    for select using (true);
drop policy if exists c_ins on comments;      create policy c_ins on comments    for insert with check (true);

-- 익명 직접 insert(레코더 익명 폴백)는 owner_puuid 가 NULL 일 때만 허용 → 남의 puuid 사칭 차단.
-- 소유권 행은 secret 검증을 통과한 upload_match(security definer)만 생성.
drop policy if exists m_ins on matches;
create policy m_ins on matches for insert to anon, authenticated with check (owner_puuid is null);

-- identities / login_codes / sessions: 정책 없음 = anon 직접 접근 차단.
--   (비밀키 해시·로그인 코드·토큰은 오직 위 security definer RPC 를 통해서만 다뤄짐)

-- ===== Storage(영상 파일) 업로드 정책 =====
-- media 버킷은 PUBLIC(읽기 공개). 업로드(INSERT/UPDATE)는 아래 정책이 있어야 anon 키로 가능.
-- ★ 함정 주의: 조건에 (select ... from storage.buckets ...) 같은 서브쿼리를 쓰면 anon 으로 실행될 때
--   buckets 를 못 읽어 빈 결과 → 차단됨. 버킷이 하나뿐이므로 조건 없이(true) 허용이 가장 확실. 삭제는 안 줌.
drop policy if exists s_sel on storage.objects;
drop policy if exists s_ins on storage.objects;
drop policy if exists s_upd on storage.objects;
drop policy if exists s_del on storage.objects;
create policy s_sel on storage.objects for select to anon, authenticated using (true);
create policy s_ins on storage.objects for insert to anon, authenticated with check (true);
create policy s_upd on storage.objects for update to anon, authenticated using (true) with check (true);
