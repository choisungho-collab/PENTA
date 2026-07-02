-- ═══════════════════════════════════════════════════════════════════
--  '나의 협곡' 복구 — 예전 업로드의 소유자(owner_puuid) 백필
--  원인: 계정 체계(riot_key) 전환 때 기존 matches.owner_puuid 를 안 바꿔
--        옛 형식/NULL 소유자 행이 '나의 협곡'(소유자 조회)에서 빠짐.
--  Supabase → SQL Editor 에 전체 붙여넣고 Run (여러 번 실행 안전)
-- ═══════════════════════════════════════════════════════════════════

-- 1) 진단: 업로더별 소유자 상태 (Run 결과에서 owner 가 'name#tag' 형식이 아니면 복구 대상)
select saver,
       owner_puuid,
       count(*) as rows
from matches
group by saver, owner_puuid
order by saver;

-- 2) 복구: 업로더 이름(saver) ↔ 계정 게임명(identities.name 의 # 앞부분) 매칭으로 소유자 채움
--    안전장치: 같은 게임명이 두 계정에 있으면(모호) 건너뜀
update matches m
set owner_puuid = i.puuid
from identities i
where lower(split_part(i.name, '#', 1)) = lower(m.saver)
  and m.owner_puuid is distinct from i.puuid
  and (select count(*) from identities i2
        where lower(split_part(i2.name, '#', 1)) = lower(m.saver)) = 1;

-- 3) 확인: 계정별로 몇 판이 '나의 협곡'에 잡히는지
select i.name as account,
       count(m.id) as my_rift_games
from identities i
left join matches m on m.owner_puuid = i.puuid
group by i.name
order by my_rift_games desc;
