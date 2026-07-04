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
