# PENTA

리그 오브 레전드 경기를 자동 녹화 → Riot API로 분석 → Supabase 업로드 → 공개 웹 갤러리로 서빙하는 시스템.
ENCORE(스타크래프트)의 녹화·업로드·갤러리·멀티시점 인프라를 재사용하고, 분석 데이터 소스만 리플레이 파싱에서 **Riot 공식 API**로 교체했다.

## 구조

```
penta/
├── recorder/recall_recorder.py     녹화기 (PyInstaller → Windows exe)
├── web/                            정적 웹 갤러리 (Netlify)
│   ├── index.html
│   ├── match.html
│   └── recall-common.js
├── netlify/functions/riot.js       Riot API 프록시 (키 보관)
├── netlify.toml
└── .github/workflows/build.yml     exe 자동 빌드
```

## 데이터 흐름

1. `League of Legends.exe` 프로세스 감지
2. Live Client Data API(`127.0.0.1:2999`) 폴링으로 게임 시작 감지 → 화면 녹화
3. 게임 종료 → 내 PUUID의 최근 매치를 Match-V5로 조회해 matchId 확보
4. Match-V5(결과·챔피언·KDA·CS·아이템·룬) + Timeline(골드·레벨 추이·오브젝트) 분석
5. Supabase에 영상 + 분석 저장 (matchId가 곧 그룹키 → 멀티 시점 자동 묶임)
6. 웹 갤러리가 Supabase를 읽어 표시

## API 키 전략 (중요)

Riot 키는 **절대 클라이언트에 노출하지 않는다.** 녹화기·갤러리는 Netlify 프록시(`netlify/functions/riot.js`)를 통해서만 Riot API를 호출하고, 키는 Netlify 환경변수에만 둔다.

- **개발/본인 테스트**: 개인 키(Personal Key, 만료 없음, 심사 없이 발급)
- **커뮤니티 공개**: 프로덕션 키 필요 (작동 프로토타입 + 도메인에 다운로드·ToS·개인정보처리방침 + Riot 심사)
- 프록시 구조라 키만 개인 → 프로덕션으로 교체하면 됨. 코드 변경 불필요.

## 셋업 (프록시 테스트)

1. https://developer.riotgames.com 로그인 → 개발 키 발급(또는 개인 키 신청)
2. Netlify에 이 저장소 연결 후, 환경변수 `RIOT_API_KEY` 설정
3. 배포 후 호출 테스트:
   - `/api/riot?action=account&riotId=이름#KR1` → PUUID 확인
   - `/api/riot?action=matches&puuid=<puuid>&count=5` → 최근 matchId 목록
   - `/api/riot?action=match&matchId=<matchId>` → 매치 상세

> Riot API 실제 호출은 인증이 필요해 개발 샌드박스에서는 테스트가 불가하다. 키 발급 후 실제 응답 확인은 로컬/배포 환경에서 진행한다.
