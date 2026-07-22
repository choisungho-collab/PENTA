// PENTA — Storage 서명 업로드 프록시
// service_role 키는 Netlify 환경변수(SUPABASE_SERVICE_KEY)에만 존재. 클라이언트/레코더에 절대 배포되지 않음.
// 레코더는 기기 비밀키(secret)로 신원을 증명하고, 1회용 서명 업로드 URL 을 받아 직접 업로드한다.
//
// 호출:
//   POST /api/storage
//   { "action": "sign-upload", "puuid": "<riot key>", "secret": "<device secret>",
//     "paths": ["videos/xxx.mp4", "thumbs/xxx.jpg"] }
// 응답:
//   { "items": [ { "path", "uploadUrl", "publicUrl" } ] }
//
// 필요한 Netlify 환경변수:
//   SUPABASE_URL          (예: https://xxxx.supabase.co)
//   SUPABASE_SERVICE_KEY  (service_role 키 — 서버에만)
//   SUPABASE_BUCKET       (선택, 기본 media)

const SB_URL = (process.env.SUPABASE_URL || '').replace(/\/+$/, '');
const SB_KEY = process.env.SUPABASE_SERVICE_KEY || '';
const BUCKET = process.env.SUPABASE_BUCKET || 'media';

const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type'
};

// 허용 경로: videos/…mp4, thumbs/…jpg 만. 경로 탈출·타 버킷 접근 차단.
const PATH_RE = /^(videos|thumbs)\/[A-Za-z0-9._-]{8,140}\.(mp4|jpg)$/;
const MAX_PATHS = 4;

function reply(statusCode, obj) {
  return { statusCode, headers: { ...CORS, 'Content-Type': 'application/json' }, body: JSON.stringify(obj) };
}

function sbHeaders() {
  return { 'Authorization': 'Bearer ' + SB_KEY, 'apikey': SB_KEY, 'Content-Type': 'application/json' };
}

// 기기 비밀키 검증 — DB 의 verify_device(security definer) RPC 호출
async function verifyDevice(puuid, secret) {
  const r = await fetch(SB_URL + '/rest/v1/rpc/verify_device', {
    method: 'POST', headers: sbHeaders(),
    body: JSON.stringify({ p_puuid: puuid, p_secret: secret })
  });
  if (!r.ok) return false;
  const v = await r.json().catch(() => false);
  return v === true;
}

// 업로드 쿼터 검사 — 기기(puuid)당 시간/일 횟수·용량 제한 (스토리지 폭탄 방어)
//   통과하면 { ok:true }, 초과하면 { ok:false, reason }. 통과 시 DB 에 이벤트 기록됨.
async function checkQuota(puuid, bytes) {
  try {
    const r = await fetch(SB_URL + '/rest/v1/rpc/check_upload_quota', {
      method: 'POST', headers: sbHeaders(),
      body: JSON.stringify({ p_puuid: puuid, p_bytes: bytes || 0 })
    });
    if (!r.ok) return { ok: true };   // 쿼터 시스템 장애 시엔 업로드를 막지 않음(가용성 우선)
    return await r.json().catch(() => ({ ok: true }));
  } catch (_) { return { ok: true }; }
}

// 에러 로깅 — 함수에서 문제가 나면 DB 에 기록(admin 에서 확인). 실패해도 조용히 무시.
async function logError(source, message, meta) {
  try {
    await fetch(SB_URL + '/rest/v1/rpc/log_error', {
      method: 'POST', headers: sbHeaders(),
      body: JSON.stringify({ p_source: source, p_message: String(message || '').slice(0, 500), p_meta: meta || {} })
    });
  } catch (_) { /* 로깅 실패는 무시 */ }
}

async function signOne(path) {
  const r = await fetch(SB_URL + '/storage/v1/object/upload/sign/' + BUCKET + '/' + path, {
    method: 'POST', headers: sbHeaders(), body: '{}'
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok || !j.url) throw new Error('sign failed ' + r.status + ': ' + JSON.stringify(j).slice(0, 160));
  return {
    path,
    uploadUrl: SB_URL + '/storage/v1' + j.url,   // PUT 대상(1회용 토큰 포함)
    publicUrl: SB_URL + '/storage/v1/object/public/' + BUCKET + '/' + path
  };
}

exports.handler = async (event) => {
  if (event.httpMethod === 'OPTIONS') return { statusCode: 204, headers: CORS, body: '' };
  if (event.httpMethod !== 'POST') return reply(405, { error: 'POST only' });
  if (!SB_URL || !SB_KEY) return reply(500, { error: 'server not configured (SUPABASE_URL / SUPABASE_SERVICE_KEY)' });

  let body;
  try { body = JSON.parse(event.body || '{}'); } catch (_) { return reply(400, { error: 'bad json' }); }
  const { action, puuid, secret, paths, bytes } = body;

  // ── 매치 삭제: 로그인 토큰으로 소유 확인 후 파일(Storage API)+행 제거 ──
  //    storage.objects 직접 DELETE 가 정책상 막혀 SQL RPC 는 401 → 서버(service_role)가 Storage API 로 지운다.
  if (action === 'backfill-win-local') {
    // 과거 '미확인' 승패 소급 — 레코더가 롤 클라이언트 '로컬 매치 히스토리'에서 읽은 승패를 반영한다(Riot 키 불필요).
    // 보안: 등록된 기기(verify_device)만 + 본인(saver=신원 이름) 행만 + 현재 미확인(won/winner/win_team 전부 null)만. 덮어쓰기 불가.
    const ident = String(body.ident || '').trim().toLowerCase();
    const secret = String(body.secret || '');
    const ups = Array.isArray(body.updates) ? body.updates.slice(0, 30) : [];
    if (!ident || !secret || String(secret).length < 16 || !ups.length) return reply(400, { error: 'bad request' });
    if (!(await verifyDevice(ident, secret))) return reply(403, { error: 'device not verified' });
    const myName = ident.split('#')[0];
    // 스탯 병합 화이트리스트: 정밀값 교체 허용(근사→정확) vs 빈 곳만 채움
    const OVERWRITE = ['gold', 'cs', 'vision'];
    const FILL = ['dmg', 'dmg_taken', 'dmg_obj', 'dmg_turret', 'heal', 'cc_sec', 'gold_spent',
                  'wards', 'wards_killed', 'turrets', 'inhibs', 'spree', 'level',
                  'pentas', 'quadras', 'triples', 'doubles'];
    const nrm = (x) => String(x || '').trim().toLowerCase();
    let done = 0, skipped = 0, enriched = 0;
    for (const u of ups) {
      const rid = String(u.row_id || '');
      const winTeam = (u.win_team === 100 || u.win_team === 200) ? u.win_team : null;
      const won = (typeof u.won === 'boolean') ? u.won : null;
      const inPlayers = Array.isArray(u.players) ? u.players.slice(0, 10) : null;
      if (!rid || (winTeam == null && !inPlayers)) { skipped++; continue; }
      const rRes = await fetch(SB_URL + '/rest/v1/matches?select=id,saver,won,winner,analysis&id=eq.' + encodeURIComponent(rid), { headers: sbHeaders() });
      const rows = await rRes.json().catch(() => []);
      const r = rows && rows[0];
      if (!r) { skipped++; continue; }
      if (nrm(r.saver) !== myName) { skipped++; continue; }                                    // 본인 행만
      const a = r.analysis || {};
      let changed = false;
      // ① 승패: 미확인일 때만 (덮어쓰기 불가)
      if (winTeam != null && r.won == null && r.winner == null && a.win_team == null) {
        a.win_team = winTeam;
        for (const pl of (a.players || [])) {
          if (pl && pl.win == null && (pl.team === 100 || pl.team === 200)) pl.win = (pl.team === winTeam);
        }
        changed = true;
      }
      // ② 풀 스코어보드: Live 분석 행만 (Riot 분석 데이터는 불가침)
      if (inPlayers && a.source === 'live' && Array.isArray(a.players) && a.players.length) {
        const byName = {};
        for (const ip of inPlayers) { const k = nrm(ip && ip.name); if (k) byName[k] = ip; }
        let touched = 0;
        for (const pl of a.players) {
          const ip = byName[nrm(pl && pl.name)];
          if (!ip || (ip.team !== pl.team)) continue;                                           // 이름+팀 일치만
          for (const f of OVERWRITE) { const v = ip[f]; if (typeof v === 'number' && isFinite(v)) { pl[f] = v; } }
          for (const f of FILL) { const v = ip[f]; if (typeof v === 'number' && isFinite(v) && !pl[f]) { pl[f] = v; } }
          if (Array.isArray(ip.items) && ip.items.length && !(Array.isArray(pl.items) && pl.items.some(Boolean))) pl.items = ip.items.slice(0, 7).map(Number);
          if (Array.isArray(ip.spells) && ip.spells.length && !(Array.isArray(pl.spells) && pl.spells.length)) pl.spells = ip.spells.slice(0, 2).map(Number);
          touched++;
        }
        if (touched) {
          const dm = (a.duration || 0) / 60;                                                    // 정확 CS 반영 → 분당 CS 재계산
          if (dm > 0) for (const pl of a.players) { if (pl && pl.cs) pl.cs_per_min = Math.round(pl.cs / dm * 10) / 10; }
          changed = true; enriched++;
        }
        if (u.bans && !((a.bans || {})[100] || (a.bans || {})[200] || (a.bans || {})['100'] || (a.bans || {})['200'])) {
          const b100 = Array.isArray(u.bans[100] || u.bans['100']) ? (u.bans[100] || u.bans['100']).slice(0, 5).map(Number) : [];
          const b200 = Array.isArray(u.bans[200] || u.bans['200']) ? (u.bans[200] || u.bans['200']).slice(0, 5).map(Number) : [];
          if (b100.length || b200.length) { a.bans = { 100: b100, 200: b200 }; changed = true; }
        }
      }
      if (!changed) { skipped++; continue; }
      const patch = { analysis: a };
      if (a.win_team != null && r.winner == null) patch.winner = a.win_team;
      if (won != null && r.won == null && a.win_team != null) patch.won = won;
      await fetch(SB_URL + '/rest/v1/matches?id=eq.' + encodeURIComponent(rid), {
        method: 'PATCH',
        headers: { ...sbHeaders(), 'Prefer': 'return=minimal' },
        body: JSON.stringify(patch)
      });
      done++;
    }
    return reply(200, { ok: true, done, skipped, enriched });
  }

  if (action === 'backfill-win') {
    // 승패 '미확인' 백필: 결과 화면 전에 클라이언트가 꺼져 GameEnd 를 못 받은 경기를,
    // 서버가 직접 Riot Match API 에서 결과를 받아 DB 에 채운다(클라이언트 값은 신뢰하지 않음 → 조작 불가).
    const matchId = String(body.match_id || '');
    if (!/^[A-Za-z0-9]+_[0-9]+$/.test(matchId)) return reply(400, { error: 'not a riot match id' });
    try {
      const rRes = await fetch(SB_URL + '/rest/v1/matches?select=id,owner_puuid,saver,won,winner,analysis&match_id=eq.' + encodeURIComponent(matchId), { headers: sbHeaders() });
      const rows = await rRes.json().catch(() => []);
      if (!Array.isArray(rows) || !rows.length) return reply(404, { error: 'no rows' });
      const wtKnown = rows.map(r => r.winner != null ? r.winner : (r.analysis && r.analysis.win_team)).find(v => v != null);
      const allKnown = rows.every(r => r.won != null || r.winner != null || (r.analysis && r.analysis.win_team != null));
      if (allKnown) return reply(200, { ok: true, win_team: wtKnown != null ? wtKnown : null, skipped: true });
      const KEY = process.env.RIOT_API_KEY || '';
      if (!KEY) return reply(500, { error: 'riot key missing' });
      const plat = matchId.split('_')[0].toLowerCase();
      const REG = { kr: 'asia', jp1: 'asia', tw2: 'asia', sg2: 'asia', th2: 'asia', vn2: 'asia', ph2: 'asia', na1: 'americas', br1: 'americas', la1: 'americas', la2: 'americas', oc1: 'americas' };
      const regional = REG[plat] || 'europe';
      const mRes = await fetch('https://' + regional + '.api.riotgames.com/lol/match/v5/matches/' + encodeURIComponent(matchId), { headers: { 'X-Riot-Token': KEY } });
      if (!mRes.ok) return reply(502, { error: 'riot ' + mRes.status });
      const m = await mRes.json().catch(() => null);
      const parts = (m && m.info && m.info.participants) || [];
      const wp = parts.find(p => p.win);
      const winTeam = wp ? wp.teamId : null;
      if (winTeam == null) return reply(200, { ok: false });
      const byPuuid = {}, byName = {};
      for (const p of parts) {
        if (p.puuid) byPuuid[p.puuid] = p;
        const n = String(p.riotIdGameName || p.summonerName || '').trim();
        if (n) byName[n] = p;
      }
      for (const r of rows) {
        const a = r.analysis || {};
        if (a.win_team == null) a.win_team = winTeam;
        for (const pl of (a.players || [])) {
          const rp = (pl.puuid && byPuuid[pl.puuid]) || byName[String(pl.name || '').trim()];
          if (rp && pl.win == null) pl.win = !!rp.win;
        }
        const me = (r.owner_puuid && byPuuid[r.owner_puuid]) || byName[String(r.saver || '').trim()];
        const patch = { winner: winTeam, analysis: a };
        if (me) patch.won = !!me.win;
        await fetch(SB_URL + '/rest/v1/matches?id=eq.' + encodeURIComponent(r.id), {
          method: 'PATCH',
          headers: { ...sbHeaders(), 'Content-Type': 'application/json', 'Prefer': 'return=minimal' },
          body: JSON.stringify(patch)
        });
      }
      return reply(200, { ok: true, win_team: winTeam });
    } catch (e) { return reply(500, { error: String((e && e.message) || e) }); }
  }

  if (action === 'delete-match') {
    const token = body.token, matchId = body.match_id;
    if (!token || !matchId) return reply(400, { error: 'missing token/match_id' });
    try {
      // 1) 토큰 → puuid (세션 검증)
      const sRes = await fetch(SB_URL + '/rest/v1/sessions?select=puuid&token=eq.' + encodeURIComponent(String(token)), { headers: sbHeaders() });
      const sess = await sRes.json().catch(() => []);
      const owner = Array.isArray(sess) && sess[0] && sess[0].puuid;
      if (!owner) return reply(401, { error: 'not logged in' });
      // 2) 소유 매치의 video/thumb 조회 (본인 것만)
      const q = 'match_id=eq.' + encodeURIComponent(String(matchId)) + '&owner_puuid=eq.' + encodeURIComponent(owner);
      const mRes = await fetch(SB_URL + '/rest/v1/matches?select=video,thumb&' + q, { headers: sbHeaders() });
      const rows = await mRes.json().catch(() => []);
      if (!Array.isArray(rows) || !rows.length) return reply(404, { error: 'not found or not yours' });
      // 3) 스토리지 파일 삭제 — public URL 에서 버킷 뒤 경로만 뽑아 DELETE (허용 경로만)
      const marker = '/object/public/' + BUCKET + '/';
      const keys = [];
      for (const row of rows) {
        for (const u of [row.video, row.thumb]) {
          if (typeof u === 'string' && u.indexOf(marker) >= 0) {
            const key = u.split(marker)[1];
            if (key && PATH_RE.test(key) && keys.indexOf(key) < 0) keys.push(key);
          }
        }
      }
      for (const key of keys) {
        await fetch(SB_URL + '/storage/v1/object/' + BUCKET + '/' + key, { method: 'DELETE', headers: sbHeaders() }).catch(() => {});
      }
      // 4) 매치 행 삭제 (service_role → RLS 우회, 소유 조건 유지)
      const dRes = await fetch(SB_URL + '/rest/v1/matches?' + q, { method: 'DELETE', headers: sbHeaders() });
      if (!dRes.ok) return reply(502, { error: 'row delete failed ' + dRes.status });
      return reply(200, { ok: true, removedRows: rows.length, removedFiles: keys.length });
    } catch (e) {
      const msg = String(e && e.message || e).slice(0, 240);
      await logError('storage/delete', msg, {});
      return reply(502, { error: msg });
    }
  }

  if (action !== 'sign-upload') return reply(400, { error: 'unknown action' });
  if (!puuid || !secret || String(secret).length < 16) return reply(401, { error: 'bad identity' });
  if (!Array.isArray(paths) || paths.length < 1 || paths.length > MAX_PATHS) return reply(400, { error: 'bad paths' });
  for (const p of paths) {
    if (typeof p !== 'string' || !PATH_RE.test(p)) return reply(400, { error: 'path not allowed: ' + String(p).slice(0, 80) });
  }

  try {
    const ok = await verifyDevice(String(puuid), String(secret));
    if (!ok) return reply(401, { error: 'unauthorized' });

    // 업로드 쿼터 검사 — 기기당 과도한 업로드(스토리지 폭탄) 차단
    const q = await checkQuota(String(puuid), Number(bytes) || 0);
    if (q && q.ok === false) {
      await logError('storage/quota', 'quota exceeded: ' + (q.reason || '?'), { puuid: String(puuid).slice(0, 40), reason: q.reason });
      return reply(429, { error: 'upload limit reached', reason: q.reason || 'limit' });
    }

    const items = [];
    for (const p of paths) items.push(await signOne(p));
    return reply(200, { items });
  } catch (e) {
    const msg = String(e && e.message || e).slice(0, 240);
    await logError('storage/sign', msg, { puuid: String(puuid || '').slice(0, 40) });
    return reply(502, { error: msg });
  }
};
