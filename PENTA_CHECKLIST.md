# PENTA — 최성호님이 하실 일

제가 만든 것: Riot 프록시, 레코더(penta_recorder.py + penta_lol.py), 빌드 설정, DB 스키마, 설정 예시.
아래는 키·계정처럼 제가 대신 못 하는 것만 모았습니다. 위에서부터 순서대로.

## 1. Riot 개발 키 (5분)
- developer.riotgames.com 로그인 → "DEVELOPMENT API KEY" 복사 (24시간마다 갱신, 개발용으론 충분)
- 커뮤니티 공개 시점에만 Production 신청(나중)

## 2. Supabase (10분)
- supabase.com 새 프로젝트 생성 (Seoul)
- SQL Editor에 `supabase_schema.sql` 붙여넣고 실행
- Storage에서 `media` 버킷 생성 → Public
- Settings → API에서 URL / anon key / service_role key 복사

## 3. GitHub + Netlify (10분)
- 이 폴더를 새 GitHub repo로 push
- Netlify에 repo 연결 (publish=web, functions 자동 인식)
- Netlify 환경변수: `RIOT_API_KEY` = (1번 키)
- 배포 후 프록시 주소 확인 (예: https://penta.netlify.app)

## 4. 실제 매치로 검증 (5분) — 가장 중요
브라우저 주소창에 차례로 입력:
- `https://<주소>/api/riot?action=account&riotId=Mongjungguy#KR1` → puuid 나오는지
- `.../api/riot?action=matches&puuid=<puuid>&count=3` → matchId 목록
- `.../api/riot?action=match&matchId=<matchId>` → 상세 JSON
→ 이 JSON을 저에게 보여주시면 penta_lol.py 필드명(길이가 초/ms 등)을 실제에 맞게 확정합니다.

## 5. 레코더 설정
- 빌드된 exe 옆에 `config.json`을 두고 `config.example.json`처럼 채우기: `proxy_url`(3번 주소), `supabase`(2번 키들)
- GitHub에 push하면 자동 빌드 → Actions에서 `penta_recorder.zip` 다운로드

---
## 제가 이어서 할 것 (최성호님 손 불필요)
- [ ] 웹 갤러리(index/match) — LoL 카드·match 페이지
- [ ] GUI 텍스트 LoL화 (현재 일부 스타 문구 잔존)
- [ ] 4번 JSON 받으면 필드 확정
