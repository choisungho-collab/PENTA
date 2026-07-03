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
  const { action, puuid, secret, paths } = body;

  if (action !== 'sign-upload') return reply(400, { error: 'unknown action' });
  if (!puuid || !secret || String(secret).length < 16) return reply(401, { error: 'bad identity' });
  if (!Array.isArray(paths) || paths.length < 1 || paths.length > MAX_PATHS) return reply(400, { error: 'bad paths' });
  for (const p of paths) {
    if (typeof p !== 'string' || !PATH_RE.test(p)) return reply(400, { error: 'path not allowed: ' + String(p).slice(0, 80) });
  }

  try {
    const ok = await verifyDevice(String(puuid), String(secret));
    if (!ok) return reply(401, { error: 'unauthorized' });
    const items = [];
    for (const p of paths) items.push(await signOne(p));
    return reply(200, { items });
  } catch (e) {
    return reply(502, { error: String(e && e.message || e).slice(0, 240) });
  }
};
