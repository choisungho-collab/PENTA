-- PENTA Supabase 스키마 (SQL Editor에 붙여넣고 실행)
-- 멀티 시점: 같은 게임(matchId)을 여러 명이 녹화하면 각각 다른 행(id 고유)으로 저장되고,
-- match_id(그룹키)로 묶인다. 좋아요/조회/댓글은 match_id 단위로 그룹 전체에 공유된다.

drop table if exists matches cascade;
create table matches (
  id          text primary key,         -- 시점별 고유 행 id (matchId + 녹화자)
  match_id    text not null,             -- Riot matchId = 멀티 시점 그룹키
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
create index if not exists matches_match_id_idx on matches(match_id);
create index if not exists matches_uploaded_idx on matches(uploaded desc);

-- 그룹(게임) 단위 좋아요/조회수
drop table if exists group_stats cascade;
create table group_stats (
  match_id text primary key,
  likes    int default 0,
  views    int default 0
);

-- 그룹(게임) 단위 댓글
drop table if exists comments cascade;
create table comments (
  id        bigserial primary key,
  match_id  text,                        -- Riot matchId(그룹 단위 댓글)
  author    text,
  body      text,
  created   text
);
create index if not exists comments_match_id_idx on comments(match_id);

-- 좋아요/조회수 RPC (match_id 기준 upsert)
create or replace function like_group(mid text, delta int)
returns int language sql as $$
  insert into group_stats(match_id, likes) values (mid, greatest(0, delta))
  on conflict(match_id) do update set likes = greatest(0, group_stats.likes + delta)
  returning likes;
$$;
create or replace function view_group(mid text)
returns void language sql as $$
  insert into group_stats(match_id, views) values (mid, 1)
  on conflict(match_id) do update set views = group_stats.views + 1;
$$;

-- RLS: 익명은 읽기+추가만, 그룹 카운터는 RPC로 갱신
alter table matches enable row level security;
alter table group_stats enable row level security;
alter table comments enable row level security;
create policy m_sel on matches      for select using (true);
create policy m_ins on matches      for insert with check (true);
create policy g_sel on group_stats  for select using (true);
create policy g_ins on group_stats  for insert with check (true);
create policy g_upd on group_stats  for update using (true);
create policy c_sel on comments     for select using (true);
create policy c_ins on comments     for insert with check (true);
