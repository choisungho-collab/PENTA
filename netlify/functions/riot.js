// PENTA — Riot API 프록시
// 키는 Netlify 환경변수(RIOT_API_KEY)에만 존재. 코드·git·클라이언트에 절대 노출되지 않음.
// 녹화기와 웹 갤러리는 모두 이 프록시를 통해서만 Riot 데이터에 접근한다.
//
// 호출 예:
//   /api/riot?action=account&riotId=몽정구#KR1
//   /api/riot?action=matches&puuid=...&count=20
//   /api/riot?action=match&matchId=KR_1234567890
//   /api/riot?action=timeline&matchId=KR_1234567890
//   /api/riot?action=spectator&puuid=...           (현재 진행 중인 게임)
// platform 파라미터 기본값은 kr(한국). 다른 서버면 platform=na1 등으로 지정.

const KEY = process.env.RIOT_API_KEY || '';

// 플랫폼(지역 샤드) → Match-V5/Account가 쓰는 리저널 라우팅
const PLATFORM_TO_REGIONAL = {
  kr:'asia', jp1:'asia', tw2:'asia', sg2:'asia', th2:'asia', vn2:'asia', ph2:'asia',
  na1:'americas', br1:'americas', la1:'americas', la2:'americas', oc1:'americas',
  euw1:'europe', eun1:'europe', tr1:'europe', ru:'europe'
};

const CORS = {
  'Access-Control-Allow-Origin': '*',            // TODO: 공개 배포 전 자기 도메인만 허용으로 좁힐 것
  'Access-Control-Allow-Methods': 'GET, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type'
};

function reply(statusCode, obj) {
  return { statusCode, headers: { ...CORS, 'Content-Type': 'application/json' }, body: JSON.stringify(obj) };
}

async function riot(host, path) {
  const url = `https://${host}.api.riotgames.com${path}`;
  const r = await fetch(url, { headers: { 'X-Riot-Token': KEY } });
  const text = await r.text();
  let body;
  try { body = JSON.parse(text); } catch (e) { body = { raw: text }; }
  return { status: r.status, body, retryAfter: r.headers.get('retry-after') };
}

exports.handler = async (event) => {
  if (event.httpMethod === 'OPTIONS') return { statusCode: 204, headers: CORS, body: '' };
  if (!KEY) return reply(500, { error: 'RIOT_API_KEY 환경변수가 설정되지 않았습니다' });

  const q = event.queryStringParameters || {};
  const action = q.action || '';
  const platform = String(q.platform || 'kr').toLowerCase();        // 한국 서버 기본
  const regional = PLATFORM_TO_REGIONAL[platform] || 'asia';

  try {
    let res;
    switch (action) {
      case 'account': {
        // riotId = "게임이름#태그"
        const raw = String(q.riotId || '');
        const hash = raw.lastIndexOf('#');
        const name = hash >= 0 ? raw.slice(0, hash) : raw;
        const tag  = hash >= 0 ? raw.slice(hash + 1) : '';
        if (!name || !tag) return reply(400, { error: 'riotId 형식은 이름#태그 입니다' });
        res = await riot(regional, `/riot/account/v1/accounts/by-riot-id/${encodeURIComponent(name)}/${encodeURIComponent(tag)}`);
        break;
      }
      case 'matches': {
        if (!q.puuid) return reply(400, { error: 'puuid 필요' });
        const count = Math.min(parseInt(q.count, 10) || 20, 100);
        const qs = ['count=' + count];
        if (q.queue) qs.push('queue=' + encodeURIComponent(q.queue));   // 큐 필터(선택)
        if (q.start) qs.push('start=' + encodeURIComponent(q.start));
        res = await riot(regional, `/lol/match/v5/matches/by-puuid/${encodeURIComponent(q.puuid)}/ids?` + qs.join('&'));
        break;
      }
      case 'match': {
        if (!q.matchId) return reply(400, { error: 'matchId 필요' });
        res = await riot(regional, `/lol/match/v5/matches/${encodeURIComponent(q.matchId)}`);
        break;
      }
      case 'timeline': {
        if (!q.matchId) return reply(400, { error: 'matchId 필요' });
        res = await riot(regional, `/lol/match/v5/matches/${encodeURIComponent(q.matchId)}/timeline`);
        break;
      }
      case 'spectator': {
        // 현재 진행 중인 게임(활성). 플랫폼 라우팅 사용.
        if (!q.puuid) return reply(400, { error: 'puuid 필요' });
        res = await riot(platform, `/lol/spectator/v5/active-games/by-summoner/${encodeURIComponent(q.puuid)}`);
        break;
      }
      case 'recent': {
        // riotId → puuid → 최근 matchId들 → 첫 매치 상세까지 모두 같은 키로 연속 처리
        // (puuid를 클라이언트가 거치지 않으므로 키 불일치로 인한 복호화 오류가 원천 차단됨)
        const raw = String(q.riotId || ''); const hash = raw.lastIndexOf('#');
        const name = hash >= 0 ? raw.slice(0, hash) : raw;
        const tag  = hash >= 0 ? raw.slice(hash + 1) : '';
        if (!name || !tag) return reply(400, { error: 'riotId 형식은 이름#태그 입니다' });
        const acc = await riot(regional, `/riot/account/v1/accounts/by-riot-id/${encodeURIComponent(name)}/${encodeURIComponent(tag)}`);
        if (acc.status !== 200) return reply(acc.status, acc.body);
        const puuid = (acc.body || {}).puuid;
        const cnt = Math.min(parseInt(q.count, 10) || 3, 20);
        const ids = await riot(regional, `/lol/match/v5/matches/by-puuid/${encodeURIComponent(puuid)}/ids?count=${cnt}`);
        if (ids.status !== 200) return reply(ids.status, { puuid, error: ids.body });
        const matchIds = ids.body;
        if (!Array.isArray(matchIds) || !matchIds.length) return reply(200, { puuid, matchIds: [], match: null });
        const m = await riot(regional, `/lol/match/v5/matches/${encodeURIComponent(matchIds[0])}`);
        return reply(200, { puuid, matchIds, match: (m.status === 200 ? m.body : { error: m.body }) });
      }
      default:
        return reply(400, { error: '알 수 없는 action: ' + action });
    }

    if (res.status === 429) return reply(429, { error: 'Riot rate limit', retryAfter: res.retryAfter });
    return reply(res.status, res.body);
  } catch (e) {
    return reply(502, { error: String((e && e.message) || e) });
  }
};
