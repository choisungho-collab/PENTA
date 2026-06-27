# PENTA

리그 오브 레전드 경기를 **자동 녹화 → Riot API 분석 → Supabase 업로드 → 공개 웹 갤러리**로 서빙하는 시스템.
ENCORE(스타크래프트)의 녹화·업로드·갤러리·멀티시점 인프라를 재사용하고, 분석 소스만 리플레이 파싱에서 **Riot 공식 API**로 교체했다.

## 구조

```
penta/
├── penta_recorder.py            레코더 (PyInstaller → Windows exe)
├── penta_lol.py                 데이터 레이어 (Live Client + Riot 매핑 + Match-V5 분석)
├── web/                         정적 웹 갤러리 (Netlify, publish = web)
│   ├── index.html               매치 카드 갤러리
│   ├── match.html               분석 화면(멀티시점/스코어보드/골드그래프/오브젝트/댓글)
│   ├── download.html            레코더 받기
│   └── penta-common.js          공통 모듈(Supabase 읽기 / Data Dragon / 그룹핑)
├── netlify/functions/riot.js    Riot API 프록시 (키 보관)
├── netlify.toml                 publish=web, /api/riot → 함수
├── supabase_schema.sql          DB 스키마
└── .github/workflows/build.yml  exe 자동 빌드(onedir, v* 태그 릴리스)
```

## 데이터 흐름

1. `League of Legends.exe` 프로세스 감지
2. Live Client Data API(`127.0.0.1:2999`) 폴링 → 게임 시작 감지 → 화면 녹화
3. 게임 종료 → 내 PUUID의 최근 매치를 녹화 시간대와 맞춰 matchId 확보
4. Match-V5(결과·챔피언·KDA·CS·아이템·룬) + Timeline(골드 추이) 분석
5. Supabase 저장 — **id**(시점별 고유 = matchId+puuid) + **match_id**(그룹키 = Riot matchId)
6. 웹 갤러리가 Supabase를 읽어 표시

## 멀티 시점

같은 게임(matchId)을 여러 명이 녹화하면 각자 **다른 행(id 고유)**으로 저장되고 **match_id**로 묶인다.
갤러리는 그룹 대표 1장으로 보여주고(N시점 뱃지), 분석 화면에서 시점 탭 전환·분할 비교한다.
좋아요/조회/댓글은 **match_id 단위(group_stats / comments.match_id)**로 그룹 전체에 공유된다.

## API 키 전략 (중요)

Riot 키는 **절대 클라이언트에 노출하지 않는다.** 레코더·갤러리는 Netlify 프록시(`netlify/functions/riot.js`)를 통해서만 Riot API를 호출하고, 키는 Netlify 환경변수 `RIOT_API_KEY`에만 둔다.

- 프록시 엔드포인트: `account` / `matches` / `match` / `timeline` / `spectator` / `recent`
- `recent`: riotId → puuid → 최근 매치를 **한 키로 연속 처리**(puuid는 발급 키에 묶여 암호화되므로 키가 바뀌면 복호화 실패 → 이를 원천 차단)
- 개발/본인: 개인 키(만료 없음). 커뮤니티 공개: 프로덕션 키(작동 프로토타입 + 도메인 + ToS/개인정보 + Riot 심사)

## 셋업

1. https://developer.riotgames.com → 개발 키 발급(또는 개인 키 신청)
2. Netlify에 이 저장소 연결 → 환경변수 `RIOT_API_KEY` 설정
3. Supabase SQL Editor에서 `supabase_schema.sql` 실행
4. 배포 후 확인: `/api/riot?action=recent&riotId=이름%23KR1` → puuid·최근 matchId·첫 매치 상세

> Riot API 실제 호출은 인증이 필요해 개발 샌드박스에서는 테스트가 불가하다. 키 발급 후 실제 응답 확인은 배포 환경에서 진행한다.
