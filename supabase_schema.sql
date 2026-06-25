-- PENTA Supabase 스키마 (SQL Editor에 붙여넣고 실행)
create table if not exists matches (
  id          text primary key,         -- Riot matchId (멀티 시점 그룹키)
  likes       int  default 0,
  views       int  default 0,
  players     jsonb,                     -- 참가자 카드(챔피언/KDA/CS/골드/아이템...)
  analysis    jsonb,                     -- 분석(골드 추이/오브젝트 등)
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
  video_size  bigint
);

create table if not exists comments (
  id        bigserial primary key,
  match_id  text,
  author    text,
  body      text,
  created   text
);

-- 좋아요/조회수 RPC
create or replace function like_match(mid text, delta int)
returns int language sql as $$
  update matches set likes = greatest(0, coalesce(likes,0)+delta) where id=mid returning likes;
$$;
create or replace function bump_view(mid text)
returns void language sql as $$
  update matches set views = coalesce(views,0)+1 where id=mid;
$$;

-- RLS: 익명은 읽기+추가만, 수정/삭제는 service_key(녹화기 로컬)만
alter table matches enable row level security;
alter table comments enable row level security;
create policy m_sel on matches for select using (true);
create policy m_ins on matches for insert with check (true);
create policy c_sel on comments for select using (true);
create policy c_ins on comments for insert with check (true);
