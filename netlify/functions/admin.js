// PENTA — 관리자 API (운영자 전용)
// 인증: ID/PW 로그인(action:'login') → 12시간 HMAC 세션 토큰 발급 → 이후 요청은 x-admin-token 헤더
//  - 브라우저에는 만료되는 세션만 남고, 원본 비밀번호(전권)는 저장되지 않음
//  - 비밀번호·세션 서명키는 Netlify 환경변수에만 존재 (ADMIN_ID / ADMIN_PW)
//  - 정직 고지: Netlify 함수는 무상태라 IP 기반 잠금은 없음. 실패 시 지연(650ms)으로 무차별 대입만 늦춤
//
// actions (POST /api/admin):
//   { action:'login', id, pw }                  → { token, exp }  (12시간 세션)
//   { action:'stats' }                          → 매치/유저/세션 수, 영상 용량 합, 최근 7일 업로드
//   { action:'matches', q?, limit?, before? }   → 최근 매치 목록(검색: uploader/match_id)
//   { action:'delete-match', id }               → 행 + 스토리지 파일(video/thumb) 삭제
//   { action:'orphan-scan' }                    → matches 가 참조하지 않는 스토리지 파일 목록
//   { action:'orphan-clean', paths:[...] }      → 고아 파일 일괄 삭제 (회당 최대 200개)
//
// 필요한 Netlify 환경변수: SUPABASE_URL, SUPABASE_SERVICE_KEY, ADMIN_TOKEN, (선택) SUPABASE_BUCKET

const crypto = require('crypto');

const SB_URL = (process.env.SUPABASE_URL || '').replace(/\/+$/, '');
const SB_KEY = process.env.SUPABASE_SERVICE_KEY || '';
const BUCKET = process.env.SUPABASE_BUCKET || 'media';
const ADMIN_ID = process.env.ADMIN_ID || '';
const ADMIN_PW = process.env.ADMIN_PW || '';
const SESS_SECRET = process.env.ADMIN_SESSION_SECRET || ('penta.' + ADMIN_PW);   // 서명키(미지정 시 PW 파생)
const SESS_TTL_MS = 12 * 3600 * 1000;

const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type, X-Admin-Token'
};
const PATH_RE = /^(videos|thumbs)\/[A-Za-z0-9._-]{1,160}\.(mp4|jpg)$/;

function reply(statusCode, obj) {
  return { statusCode, headers: { ...CORS, 'Content-Type': 'application/json' }, body: JSON.stringify(obj) };
}
function sbH(extra) {
  return { 'Authorization': 'Bearer ' + SB_KEY, 'apikey': SB_KEY, 'Content-Type': 'application/json', ...(extra || {}) };
}
function safeEq(x, y) {   // 길이 무관 타이밍 안전 비교
  const a = crypto.createHash('sha256').update(String(x)).digest();
  const b = crypto.createHash('sha256').update(String(y)).digest();
  return crypto.timingSafeEqual(a, b);
}
function signSession(exp) {
  const mac = crypto.createHmac('sha256', SESS_SECRET).update('adm.' + exp).digest('base64url');
  return exp + '.' + mac;
}
function sessionOk(tok) {
  const parts = String(tok || '').split('.');
  if (parts.length !== 2) return false;
  const exp = parseInt(parts[0], 10);
  if (!isFinite(exp) || Date.now() > exp) return false;
  return safeEq(signSession(exp), parts[0] + '.' + parts[1]);
}
const sleep = ms => new Promise(res => setTimeout(res, ms));
function keyFromUrl(u) {   // 공개 URL → 버킷 내 경로
  const mark = '/object/public/' + BUCKET + '/';
  const i = (u || '').indexOf(mark);
  return i < 0 ? null : u.slice(i + mark.length);
}

async function countOf(table, filter) {   // Prefer count=exact 로 행 수만
  const r = await fetch(SB_URL + '/rest/v1/' + table + '?select=id' + (filter || ''), {
    headers: sbH({ 'Prefer': 'count=exact', 'Range': '0-0' })
  });
  const cr = r.headers.get('content-range') || '';
  const n = parseInt(cr.split('/')[1], 10);
  return isFinite(n) ? n : 0;
}

async function listStorage(prefix) {   // 스토리지 전체 나열 (1000개씩 페이지)
  const out = [];
  for (let page = 0; page < 20; page++) {
    const r = await fetch(SB_URL + '/storage/v1/object/list/' + BUCKET, {
      method: 'POST', headers: sbH(),
      body: JSON.stringify({ prefix: prefix, limit: 1000, offset: page * 1000,
                             sortBy: { column: 'name', order: 'asc' } })
    });
    if (!r.ok) throw new Error('storage list ' + r.status);
    const j = await r.json();
    for (const o of (j || [])) {
      if (o && o.id) out.push({ path: prefix + '/' + o.name, size: (o.metadata && o.metadata.size) || 0, created: o.created_at || '' });
    }
    if (!j || j.length < 1000) break;
  }
  return out;
}

async function allMatchRefs() {   // 모든 매치의 video/thumb 참조 경로 집합
  const refs = new Set();
  for (let page = 0; page < 40; page++) {
    const from = page * 1000, to = from + 999;
    const r = await fetch(SB_URL + '/rest/v1/matches?select=video,thumb', {
      headers: sbH({ 'Range': from + '-' + to })
    });
    if (!r.ok) throw new Error('matches read ' + r.status);
    const rows = await r.json();
    for (const row of rows) {
      const v = keyFromUrl(row.video); if (v) refs.add(v);
      const t = keyFromUrl(row.thumb); if (t) refs.add(t);
    }
    if (rows.length < 1000) break;
  }
  return refs;
}

async function storageDelete(paths) {   // 일괄 삭제(실제 blob 제거)
  const r = await fetch(SB_URL + '/storage/v1/object/' + BUCKET, {
    method: 'DELETE', headers: sbH(), body: JSON.stringify({ prefixes: paths })
  });
  if (!r.ok) throw new Error('storage delete ' + r.status + ': ' + (await r.text()).slice(0, 160));
}

exports.handler = async (event) => {
  if (event.httpMethod === 'OPTIONS') return { statusCode: 204, headers: CORS, body: '' };
  if (event.httpMethod !== 'POST') return reply(405, { error: 'POST only' });
  if (!SB_URL || !SB_KEY) return reply(500, { error: 'server not configured (SUPABASE_URL / SUPABASE_SERVICE_KEY)' });
  if (!ADMIN_ID || !ADMIN_PW) return reply(500, { error: 'ADMIN_ID / ADMIN_PW not set on server' });

  let body;
  try { body = JSON.parse(event.body || '{}'); } catch (_) { return reply(400, { error: 'bad json' }); }

  // ── 로그인: ID/PW → 12시간 세션 발급 ──────────────────────────────
  if (body.action === 'login') {
    const okId = safeEq(body.id || '', ADMIN_ID);
    const okPw = safeEq(body.pw || '', ADMIN_PW);
    if (!(okId && okPw)) { await sleep(650); return reply(401, { error: 'wrong id or password' }); }
    const exp = Date.now() + SESS_TTL_MS;
    return reply(200, { token: signSession(exp), exp });
  }

  if (!sessionOk(event.headers['x-admin-token'] || event.headers['X-Admin-Token'])) {
    return reply(401, { error: 'session expired or invalid' });
  }

  try {
    // ── 대시보드 통계 ──────────────────────────────────────────────
    if (body.action === 'stats') {
      const weekAgo = new Date(Date.now() - 7 * 86400000).toISOString();
      const [nMatch, nIdent, nSess, nWeek] = await Promise.all([
        countOf('matches'), countOf('identities'), countOf('sessions'),
        countOf('matches', '&uploaded=gte.' + encodeURIComponent(weekAgo))
      ]);
      let vidBytes = 0, vidRows = 0;
      for (let page = 0; page < 40; page++) {
        const from = page * 1000, to = from + 999;
        const r = await fetch(SB_URL + '/rest/v1/matches?select=video_size', { headers: sbH({ 'Range': from + '-' + to }) });
        const rows = r.ok ? await r.json() : [];
        for (const row of rows) { vidBytes += (row.video_size || 0); vidRows++; }
        if (rows.length < 1000) break;
      }
      return reply(200, { matches: nMatch, identities: nIdent, sessions: nSess,
                          uploads7d: nWeek, videoBytes: vidBytes, videoRows: vidRows });
    }

    // ── 매치 목록/검색 ─────────────────────────────────────────────
    if (body.action === 'matches') {
      const limit = Math.min(Math.max(parseInt(body.limit, 10) || 60, 1), 200);
      // 개별 시점 행을 넉넉히 가져와 match_id 로 그룹화(같은 게임을 여러 명이 녹화한 멀티 POV 를 한 줄로).
      let url = SB_URL + '/rest/v1/matches?select=id,match_id,uploader,uploaded,video_size,owner_puuid,title,length,won'
              + '&order=uploaded.desc&limit=' + (limit * 4);
      const q = String(body.q || '').slice(0, 60).replace(/[%,()]/g, '');
      if (q) url += '&or=(uploader.ilike.*' + encodeURIComponent(q) + '*,match_id.ilike.*' + encodeURIComponent(q) + '*)';
      if (body.before) url += '&uploaded=lt.' + encodeURIComponent(String(body.before).slice(0, 40));
      const r = await fetch(url, { headers: sbH() });
      if (!r.ok) throw new Error('matches ' + r.status);
      const rows = await r.json();

      const groups = new Map();   // match_id -> 그룹(대표 정보 + 시점 목록)
      for (const row of rows) {
        const key = row.match_id || row.id;
        let g = groups.get(key);
        if (!g) {
          g = { match_id: key, uploaded: row.uploaded, title: row.title || '',
                length: row.length || '', totalBytes: 0, povs: [] };
          groups.set(key, g);
        }
        g.povs.push({ id: row.id, uploader: row.uploader || '', owner: !!row.owner_puuid,
                      bytes: row.video_size || 0, won: row.won });
        g.totalBytes += (row.video_size || 0);
        if (row.title && !g.title) g.title = row.title;
        if (row.uploaded > g.uploaded) g.uploaded = row.uploaded;   // 그룹 대표 시각 = 최신
      }
      // 최신순 정렬 후 limit 개 그룹만
      const out = Array.from(groups.values())
        .sort((a, b) => (a.uploaded < b.uploaded ? 1 : -1))
        .slice(0, limit);
      // 페이지네이션 커서: 마지막 그룹의 대표 시각
      const cursor = out.length ? out[out.length - 1].uploaded : null;
      return reply(200, { groups: out, cursor: cursor, hasMore: rows.length >= limit * 4 });
    }

    // ── 삭제: 단일 시점(id) 또는 게임 전체(match_id) ─────────────────
    //    { action:'delete-match', id }        → 그 시점 1개만
    //    { action:'delete-match', matchId }   → 같은 게임의 모든 시점(멀티 POV 통째로)
    if (body.action === 'delete-match') {
      let filter, label;
      if (body.matchId) {
        const mid = String(body.matchId);
        if (!/^[A-Za-z0-9._-]{4,160}$/.test(mid)) return reply(400, { error: 'bad matchId' });
        filter = 'match_id=eq.' + encodeURIComponent(mid); label = mid;
      } else {
        const id = String(body.id || '');
        if (!/^[A-Za-z0-9._-]{8,140}$/.test(id)) return reply(400, { error: 'bad id' });
        filter = 'id=eq.' + encodeURIComponent(id); label = id;
      }
      const r = await fetch(SB_URL + '/rest/v1/matches?select=video,thumb&' + filter, { headers: sbH() });
      const rows = r.ok ? await r.json() : [];
      if (!rows.length) return reply(404, { error: 'not found' });
      const paths = [];
      for (const row of rows) {
        const v = keyFromUrl(row.video); if (v) paths.push(v);
        const t = keyFromUrl(row.thumb); if (t) paths.push(t);
      }
      if (paths.length) await storageDelete(paths);
      const d = await fetch(SB_URL + '/rest/v1/matches?' + filter, { method: 'DELETE', headers: sbH() });
      if (!d.ok) throw new Error('row delete ' + d.status);
      return reply(200, { ok: true, removedRows: rows.length, removedFiles: paths });
    }

    // ── 고아 파일 스캔 ─────────────────────────────────────────────
    if (body.action === 'orphan-scan') {
      const [vids, thumbs, refs] = await Promise.all([listStorage('videos'), listStorage('thumbs'), allMatchRefs()]);
      const orphans = vids.concat(thumbs).filter(function (o) { return !refs.has(o.path) && !o.path.startsWith('_selftest'); });
      const bytes = orphans.reduce(function (a, o) { return a + (o.size || 0); }, 0);
      return reply(200, { orphans: orphans.slice(0, 2000), totalBytes: bytes, scanned: vids.length + thumbs.length });
    }

    // ── 고아 파일 정리 ─────────────────────────────────────────────
    if (body.action === 'orphan-clean') {
      const paths = Array.isArray(body.paths) ? body.paths.slice(0, 200) : [];
      if (!paths.length) return reply(400, { error: 'no paths' });
      for (const p of paths) {
        if (typeof p !== 'string' || !PATH_RE.test(p)) return reply(400, { error: 'path not allowed: ' + String(p).slice(0, 80) });
      }
      const refs = await allMatchRefs();   // 안전핀: 참조 중 파일은 요청에 있어도 지우지 않음
      const safe = paths.filter(function (p) { return !refs.has(p); });
      if (safe.length) await storageDelete(safe);
      return reply(200, { ok: true, removed: safe.length, skipped: paths.length - safe.length });
    }

    return reply(400, { error: 'unknown action' });
  } catch (e) {
    return reply(502, { error: String((e && e.message) || e).slice(0, 240) });
  }
};
