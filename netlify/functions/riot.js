// PENTA — Riot API 프록시
const KEY = process.env.RIOT_API_KEY || '';

const PLATFORM_TO_REGIONAL = {
  kr:'asia', jp1:'asia', tw2:'asia', sg2:'asia', th2:'asia', vn2:'asia', ph2:'asia',
  na1:'americas', br1:'americas', la1:'americas', la2:'americas', oc1:'americas',
  euw1:'europe', eun1:'europe', tr1:'europe', ru:'europe'
};
const CORS = {
  'Access-Control-Allow-Origin': '*',
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
  const platform = String(q.platform || 'kr').toLowerCase();
  const regional = PLATFORM_TO_REGIONAL[platform] || 'asia';
  try {
    let res;
    switch (action) {
      case 'account': {
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
        if (q.queue) qs.push('queue=' + encodeURIComponent(q.queue));
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
        if (!q.puuid) return reply(400, { error: 'puuid 필요' });
        res = await riot(platform, `/lol/spectator/v5/active-games/by-summoner/${encodeURIComponent(q.puuid)}`);
        break;
      }
      case 'recent': {
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
