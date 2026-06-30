-- ============================================================================
-- myPENTA 계정 모델 마이그레이션 — 신원 = Riot ID, 멀티 PC 한 계정 통합
-- ============================================================================
-- 무엇이 바뀌나:
--   - 계정 신원 = riot_key (gameName#tagline 을 소문자/공백정리한 값). PC에 묶지 않음.
--   - identities.puuid 컬럼이 이제 riot_key 를 담는다(컬럼명은 호환 위해 그대로 둠).
--   - 신원당 "여러 기기 비밀키"를 허용 → 같은 Riot ID 면 어느 PC에서 올려도 한 계정으로 묶인다.
--   - 보안 모델: 레코더가 Live Client 에서 본 내 Riot ID 로 동작(honest-client).
--     비밀키는 서버에 sha256 해시로만 저장. 완전 무결성(타 클라 위조 차단)은 추후 RSO 레이어로.
-- 안전: 멱등(여러 번 실행 가능). Supabase → SQL Editor 에서 그대로 실행.
-- ============================================================================

create extension if not exists pgcrypto with schema extensions;

-- 1) 신원당 여러 기기 비밀키(배열) 컬럼 추가. 기존 단일 secret_hash 는 무해하게 남겨둠.
alter table identities add column if not exists device_secrets text[] not null default '{}';

-- 기존 단일 비밀키를 배열로 이관(아직 비어있는 신원만).
update identities
   set device_secrets = array[secret_hash]
 where secret_hash is not null
   and coalesce(array_length(device_secrets, 1), 0) = 0;

-- 더 이상 단일 비밀키를 필수로 두지 않음(과거 데이터 보존, 신규는 배열 사용).
alter table identities alter column secret_hash drop not null;

-- 반환 타입이 바뀌므로 기존 함수를 먼저 제거(없으면 무시) 후 재생성. (Postgres: create or replace 로는 반환타입 변경 불가)
drop function if exists register_identity(text, text, text, integer);
drop function if exists upload_match(text, text, jsonb);
drop function if exists issue_login_code(text, text, text);

-- 2) 신원 등록/갱신 — 이 기기 비밀키를 "인가 기기 목록"에 추가(멀티 PC).
--    같은 Riot ID 면 어느 PC 든 자동 합류. 이름/아이콘은 최신으로 갱신.
create or replace function register_identity(p_puuid text, p_secret text, p_name text default null, p_icon int default null)
returns boolean language plpgsql security definer set search_path = public, extensions as $$
declare h text;
begin
  if p_puuid is null or p_secret is null or length(p_secret) < 16 then
    raise exception 'bad identity args';
  end if;
  h := encode(digest(p_secret, 'sha256'), 'hex');
  insert into identities(puuid, name, icon, device_secrets)
       values (p_puuid, p_name, p_icon, array[h])
  on conflict (puuid) do update set
       name           = coalesce(p_name, identities.name),
       icon           = coalesce(p_icon, identities.icon),
       updated        = now(),
       device_secrets = (select array(select distinct e
                                        from unnest(identities.device_secrets || array[h]) as e));
  return true;
end; $$;

-- 3) 매치 업로드 — 인가 기기만(비밀키가 신원의 기기 목록에 있어야). owner = riot_key 로 서버가 박는다.
create or replace function upload_match(p_puuid text, p_secret text, p_row jsonb)
returns text language plpgsql security definer set search_path = public, extensions as $$
declare h text; ok boolean;
begin
  h := encode(digest(p_secret, 'sha256'), 'hex');
  select (h = any(device_secrets)) into ok from identities where puuid = p_puuid;
  if not coalesce(ok, false) then raise exception 'unauthorized'; end if;

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

-- 4) 로그인 코드 발급 — 인가 기기만. (Archive 클릭 시 레코더가 호출)
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

-- exchange_login_code / session_whoami / end_session / update_match_meta / delete_match
--   → 변경 없음. 모두 puuid(=이제 riot_key) 텍스트 기준으로 그대로 동작한다.
-- ============================================================================
