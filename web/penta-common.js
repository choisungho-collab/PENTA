/* PENTA 공통 모듈
 * - Supabase 읽기(공개 anon 키, RLS는 select/insert만 허용)
 * - Data Dragon 자산 URL(챔피언/아이템/소환사 주문 아이콘)
 * - matchId 기반 멀티 시점(POV) 그룹핑
 * index.html / match.html 양쪽에서 공유한다.
 */
(function (global) {
  'use strict';

  // ───────────────────────── Supabase ─────────────────────────
  // anon 키는 공개되어도 되는 읽기용 키. 수정/삭제는 녹화기(서버 키)만 가능.
  var SB_URL = 'https://bsrvmesrygbfeqicquvq.supabase.co';
  var SB_ANON = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImJzcnZtZXNyeWdiZmVxaWNxdXZxIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODIzNjA2NjQsImV4cCI6MjA5NzkzNjY2NH0.PBnGgLxvMDOK_yUQxTH11EwizEz5oJ1OWp-9I5nG8Ug';
  var SB_REST = SB_URL + '/rest/v1';

  function sbHeaders(extra) {
    var h = { apikey: SB_ANON, Authorization: 'Bearer ' + SB_ANON };
    if (extra) for (var k in extra) h[k] = extra[k];
    return h;
  }
  async function sbSelect(table, query) {
    var url = SB_REST + '/' + table + (query ? ('?' + query) : '');
    var r = await fetch(url, { headers: sbHeaders() });
    if (!r.ok) throw new Error('supabase select ' + r.status);
    return r.json();
  }
  async function sbInsert(table, row) {
    var r = await fetch(SB_REST + '/' + table, {
      method: 'POST',
      headers: sbHeaders({ 'Content-Type': 'application/json', Prefer: 'return=representation' }),
      body: JSON.stringify(row)
    });
    if (!r.ok) throw new Error('supabase insert ' + r.status);
    return r.json();
  }
  async function sbRpc(fn, body) {
    var r = await fetch(SB_REST + '/rpc/' + fn, {
      method: 'POST',
      headers: sbHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(body || {})
    });
    var t = await r.text();
    if (!r.ok) {
      var msg = 'supabase rpc ' + fn + ' ' + r.status;
      try { var j = JSON.parse(t); if (j && (j.message || j.hint)) msg += ': ' + (j.message || j.hint); }
      catch (e) { if (t) msg += ': ' + t.slice(0, 180); }
      throw new Error(msg);
    }
    try { return JSON.parse(t); } catch (e) { return t; }
  }

  // ──────────────────────── Data Dragon ───────────────────────
  var _ver = null;
  // localStorage 영구 캐시: 페이지를 이동해도 DataDragon 재요청 안 함(딜레이 제거).
  //  - 버전: 24시간마다 갱신  - 챔피언맵: 버전이 바뀔 때만 갱신
  function _lsGet(k){ try{ return localStorage.getItem(k); }catch(_){ return null; } }
  function _lsSet(k,v){ try{ localStorage.setItem(k,v); }catch(_){} }
  async function ddVersion() {
    if (_ver) return _ver;
    try {
      var cached = JSON.parse(_lsGet('penta_dd_ver') || 'null');
      if (cached && cached.v && (Date.now() - cached.t) < 86400000) { _ver = cached.v; return _ver; }
    } catch (_) {}
    try {
      var r = await fetch('https://ddragon.leagueoflegends.com/api/versions.json');
      var v = await r.json();
      _ver = (Array.isArray(v) && v[0]) || '15.1.1';
      _lsSet('penta_dd_ver', JSON.stringify({ v: _ver, t: Date.now() }));
    } catch (e) {
      var stale = null; try { stale = JSON.parse(_lsGet('penta_dd_ver') || 'null'); } catch (_) {}
      _ver = (stale && stale.v) || '15.1.1';   // 오프라인이어도 마지막 값 재사용
    }
    return _ver;
  }
  // Match-V5의 championName은 대부분 DDragon 파일명과 같다. 알려진 예외만 보정.
  var CHAMP_FIX = { FiddleSticks: 'Fiddlesticks' };
  // 한국 클라 Live Client는 한글 챔피언명("케일")을 주므로, ko_KR DDragon 데이터로 한글명→영문키 맵을 만든다.
  var _champMap = null;
  async function ddChampMap(ver) {
    if (_champMap) return _champMap;
    // 버전별 캐시: 같은 버전이면 champion.json(수백 KB) 재요청 안 함
    var CKEY = 'penta_dd_champ_' + (ver || '');
    try {
      var cached = JSON.parse(_lsGet(CKEY) || 'null');
      if (cached && typeof cached === 'object' && Object.keys(cached).length) { _champMap = cached; return _champMap; }
    } catch (_) {}
    _champMap = {};
    try {
      var r = await fetch('https://ddragon.leagueoflegends.com/cdn/' + ver + '/data/ko_KR/champion.json');
      var j = await r.json();
      var d = (j && j.data) || {};
      for (var key in d) { if (d[key] && d[key].name) _champMap[d[key].name] = d[key].id || key; }
      if (Object.keys(_champMap).length) {
        _lsSet(CKEY, JSON.stringify(_champMap));
        try {   // 옛 버전 캐시는 정리(용량 누적 방지)
          for (var i = localStorage.length - 1; i >= 0; i--) {
            var k = localStorage.key(i);
            if (k && k.indexOf('penta_dd_champ_') === 0 && k !== CKEY) localStorage.removeItem(k);
          }
        } catch (_) {}
      }
    } catch (e) {}
    return _champMap;
  }
  function champKey(name) {
    if (_champMap && _champMap[name]) return _champMap[name];   // 한글명 → 영문키
    return CHAMP_FIX[name] || String(name || '').replace(/[^A-Za-z0-9]/g, '');
  }
  function ddBase(ver) { return 'https://ddragon.leagueoflegends.com/cdn/' + ver; }
  function champIcon(ver, name) { return ddBase(ver) + '/img/champion/' + champKey(name) + '.png'; }
  function champSplash(name) { return 'https://ddragon.leagueoflegends.com/cdn/img/champion/splash/' + champKey(name) + '_0.jpg'; }
  function champLoading(name) { return 'https://ddragon.leagueoflegends.com/cdn/img/champion/loading/' + champKey(name) + '_0.jpg'; }
  function itemIcon(ver, id) { return id ? (ddBase(ver) + '/img/item/' + id + '.png') : null; }

  // 소환사 주문 id → DDragon 파일명
  var SPELL = {
    1: 'SummonerBoost', 3: 'SummonerExhaust', 4: 'SummonerFlash', 6: 'SummonerHaste',
    7: 'SummonerHeal', 11: 'SummonerSmite', 12: 'SummonerTeleport', 13: 'SummonerMana',
    14: 'SummonerDot', 21: 'SummonerBarrier', 30: 'SummonerPoroRecall', 31: 'SummonerPoroThrow',
    32: 'SummonerSnowball', 39: 'SummonerSnowURFSnowball_Mark', 54: 'Summoner_UltBookPlaceholder'
  };
  function spellIcon(ver, id) { var f = SPELL[id]; return f ? (ddBase(ver) + '/img/spell/' + f + '.png') : null; }

  // 포지션 표기
  var POS_KO = { TOP: '탑', JUNGLE: '정글', MIDDLE: '미드', BOTTOM: '원딜', UTILITY: '서폿' };
  function posKo(p) { return POS_KO[p] || ''; }
  var POS_ORDER = { TOP: 0, JUNGLE: 1, MIDDLE: 2, BOTTOM: 3, UTILITY: 4 };
  var POS_ALIAS = { TOP:0, JUNGLE:1, JG:1, JUNG:1, JGL:1, MIDDLE:2, MID:2, BOTTOM:3, BOT:3, ADC:3, CARRY:3, BOTCARRY:3, UTILITY:4, SUPPORT:4, SUP:4, SUPP:4 };
  function posRank(p) { if (p == null) return 9; var k = String(p).toUpperCase().replace(/[^A-Z]/g, ''); return POS_ALIAS[k] != null ? POS_ALIAS[k] : 9; }

  // ───────────────────────── 큐 이름 ──────────────────────────
  var QUEUE = {
    400: '일반', 420: '솔로 랭크', 430: '일반', 440: '자유 랭크', 450: '칼바람 나락',
    490: '빠른 대전', 700: '격전', 720: '칼바람 격전', 830: 'AI 대전', 840: 'AI 대전',
    850: 'AI 대전', 900: '우르프', 1020: '단일 챔피언', 1300: '돌격 넥서스',
    1700: '아레나', 1900: '우르프'
  };
  function queueName(q) { q = parseInt(q, 10); return QUEUE[q] || '소환사의 협곡'; }

  // ───────────────────────── 포맷 ─────────────────────────────
  function mmss(sec) {
    sec = Math.max(0, Math.round(sec || 0));
    var m = Math.floor(sec / 60), s = sec % 60;
    return m + ':' + String(s).padStart(2, '0');
  }
  function kdaRatio(k, d, a) {
    d = d || 0;
    return d === 0 ? 'Perfect' : (((( k || 0) + (a || 0)) / d).toFixed(2));
  }
  function compact(n) {
    n = n || 0;
    if (n >= 1000) return (n / 1000).toFixed(1) + 'k';
    return String(n);
  }
  // "n분 전" 류 상대 시각
  function ago(iso) {
    if (!iso) return '';
    var t = Date.parse(iso); if (isNaN(t)) return '';
    var s = Math.max(0, (Date.now() - t) / 1000);
    if (s < 60) return '방금 전';
    if (s < 3600) return Math.floor(s / 60) + '분 전';
    if (s < 86400) return Math.floor(s / 3600) + '시간 전';
    if (s < 2592000) return Math.floor(s / 86400) + '일 전';
    return Math.floor(s / 2592000) + '개월 전';
  }

  // ─────────────────── 멀티 시점(POV) 그룹핑 ───────────────────
  // matchId(= row.id)가 곧 그룹키. 같은 게임을 여러 명이 녹화하면 id가 동일하다.
  function groupKeyOf(row) { return row && (row.match_id != null ? String(row.match_id) : (row.id != null ? String(row.id) : null)); }
  function clusterByMatch(rows) {
    var map = new Map(), order = [];
    (rows || []).forEach(function (r) {
      var k = groupKeyOf(r) || ('_' + Math.random());
      if (!map.has(k)) { map.set(k, []); order.push(k); }
      map.get(k).push(r);
    });
    return order.map(function (k) { return map.get(k); });
  }
  // 그룹 대표(영상 있는 것 우선, 그중 최신 업로드)
  function pickPrimary(group) {
    var withVid = group.filter(function (r) { return r.video; });
    var pool = withVid.length ? withVid : group;
    // 로그인한 본인이 올린 시점이 이 게임에 있으면 그걸 대표로(예: innocentsword 로그인 → 본인 갈리오 시점).
    // 없으면(비로그인/내 시점 없음) 기존대로 영상 있는 시점 중 최신 업로드.
    var myId = (typeof sessionPuuid === 'function') ? sessionPuuid() : null;
    if (myId) {
      var mine = pool.filter(function (r) { return r.owner_puuid && r.owner_puuid === myId; });
      if (mine.length) pool = mine;
    }
    return pool.slice().sort(function (a, b) {
      return String(b.uploaded || '').localeCompare(String(a.uploaded || ''));
    })[0];
  }
  // 녹화자(saver)의 카드
  function saverCard(row) {
    var ps = row.players || [];
    return ps.find(function (p) { return p && p.name === row.saver; }) || null;
  }
  // 카드의 대표 선수(녹화자 → 없으면 첫 번째)
  function heroCard(row) { return saverCard(row) || (row.players || [])[0] || {}; }

  // 가장 높은 멀티킬 한 줄(없으면 null)
  function bestMulti(p) {
    if (!p) return null;
    if (p.pentas > 0) return { label: 'PENTAKILL', n: p.pentas, rank: 5 };
    if (p.quadras > 0) return { label: 'QUADRA KILL', n: p.quadras, rank: 4 };
    if (p.triples > 0) return { label: 'TRIPLE KILL', n: p.triples, rank: 3 };
    return null;
  }

  // ─────────────── 그룹(게임) 단위 좋아요/조회 ───────────────
  async function likeGroup(mid, delta) { return sbRpc('like_group', { mid: mid, delta: delta }); }
  async function viewGroup(mid) { return sbRpc('view_group', { mid: mid }); }
  async function statsAll() {
    try {
      var rows = await sbSelect('group_stats', 'select=*&limit=2000');
      var m = {};
      (rows || []).forEach(function (r) { m[String(r.match_id)] = { likes: r.likes || 0, views: r.views || 0 }; });
      return m;
    } catch (e) { return {}; }
  }
  async function statsOne(mid) {
    try {
      var rows = await sbSelect('group_stats', 'select=*&match_id=eq.' + encodeURIComponent(mid));
      var r = (rows || [])[0];
      return r ? { likes: r.likes || 0, views: r.views || 0 } : { likes: 0, views: 0 };
    } catch (e) { return { likes: 0, views: 0 }; }
  }

  // 측정 지표 종합 등급 (매치 코칭 카드와 동일 기준)
  function grade(me, durSec) {
    if (!me) return null;
    var pos = me.position || '', lane = me.lane || {};
    var isJg = pos === 'JUNGLE', isSup = pos === 'UTILITY', isLane = !isJg && !isSup;
    durSec = +durSec || 0; if (durSec > 10000) durSec = durSec / 1000;
    var durMin = durSec > 0 ? durSec / 60 : 0;
    var vspm = (durMin && me.vision != null) ? (me.vision / durMin) : null;
    var csFloor = isJg ? 4 : 5, csGood = isJg ? 5.5 : 7;
    var visFloor = isSup ? 0.9 : (isJg ? 0.8 : 0.5), visGood = isSup ? 1.8 : (isJg ? 1.3 : 1.0);
    var kpB = pos === 'TOP' ? 0.35 : ((isSup || isJg) ? 0.55 : (pos === 'MIDDLE' ? 0.50 : 0.48));
    function p3(val, lo, hi) { return val == null ? null : (val >= hi ? 2 : (val < lo ? 0 : 1)); }
    var gp = [];
    if (!isSup) gp.push([isJg ? 1 : (pos === 'BOTTOM' ? 3 : 2), p3(me.cs_per_min, csFloor, csGood)]);
    if (isLane && lane.cs10 != null) gp.push([1, p3(lane.cs10, -10, 10)]);
    if (me.kda != null) gp.push([pos === 'BOTTOM' ? 3 : 2, p3(me.kda, 2, 3)]);
    if (me.kp != null) gp.push([(isJg || isSup) ? 3 : (pos === 'TOP' ? 1 : 2), p3(me.kp, kpB - 0.1, kpB + 0.1)]);
    if (vspm != null) gp.push([isSup ? 3 : (isJg ? 2 : 1), p3(vspm, visFloor, visGood)]);
    var gws = 0, gss = 0;
    gp.forEach(function (x) { if (x[1] != null) { gws += x[0] * 2; gss += x[0] * x[1]; } });
    if (gws <= 0) return null;
    var score = Math.round(gss / gws * 100);
    var letter = score >= 85 ? 'S' : (score >= 70 ? 'A' : (score >= 55 ? 'B' : (score >= 40 ? 'C' : 'D')));
    return { score: score, letter: letter };
  }

  // ===================== 세션 / 로그인 =====================
  // 토큰은 localStorage 보관. #code(레코더 Archive가 붙여줌) → exchange_login_code → 토큰.
  var SESS_KEY = 'penta_session';
  function _sessRead() { try { return JSON.parse(localStorage.getItem(SESS_KEY) || 'null'); } catch (e) { return null; } }
  function _sessWrite(s) { try { if (s) localStorage.setItem(SESS_KEY, JSON.stringify(s)); else localStorage.removeItem(SESS_KEY); } catch (e) {} }
  function session() { return _sessRead(); }                 // {token,puuid,name,icon} | null (로컬 캐시)
  function sessionPuuid() { var s = _sessRead(); return s && s.puuid; }

  async function loginWithCode(code) {
    var r = await sbRpc('exchange_login_code', { p_code: code });   // {token,puuid,name,icon}
    if (r && r.token) { _sessWrite(r); return r; }
    return null;
  }
  async function whoami() {
    var s = _sessRead(); if (!s || !s.token) return null;
    try {
      var r = await sbRpc('session_whoami', { p_token: s.token });
      if (r && r.puuid) { var ns = { token: s.token, puuid: r.puuid, name: r.name, icon: r.icon }; _sessWrite(ns); return ns; }
      _sessWrite(null); return null;                          // 만료/무효 → 정리
    } catch (e) { return s; }                                 // 네트워크 오류면 캐시 유지
  }
  async function logout() {
    var s = _sessRead();
    if (s && s.token) { try { await sbRpc('end_session', { p_token: s.token }); } catch (e) {} }
    _sessWrite(null);
  }
  // 페이지 로드시: #code 있으면 소비(→토큰, URL에서 제거), 그 뒤 토큰 검증. 세션 반환.
  var _loginErr = null;
  function lastLoginError() { return _loginErr; }
  async function initAuth() {
    _loginErr = null;
    try {
      var m = (location.hash || '').match(/[#&]code=([^&]+)/);
      if (m) {
        var code = decodeURIComponent(m[1]);
        try { history.replaceState(null, '', location.pathname + location.search); } catch (e) { location.hash = ''; }
        try { await loginWithCode(code); } catch (e) { _loginErr = String((e && e.message) || e); }
      }
    } catch (e) {}
    return await whoami();
  }
  // [이 PC의 레코더로 로그인] — 레코더의 127.0.0.1 브리지에서 코드 받아 즉시 로그인
  async function loginViaRecorder() {
    var ports = [47821, 47822, 47823], lastErr = null;
    for (var i = 0; i < ports.length; i++) {
      try {
        var r = await fetch('http://127.0.0.1:' + ports[i] + '/login', { cache: 'no-store' });
        if (!r.ok) { lastErr = new Error('bridge http ' + r.status); continue; }
        var j = await r.json();
        if (j && j.code) return await loginWithCode(j.code);
        if (j && j.error) throw new Error(j.error);
      } catch (e) { lastErr = e; }
    }
    throw (lastErr || new Error('recorder not running'));
  }
  async function updateMatchMeta(mid, title) { var s = _sessRead(); if (!s || !s.token) throw new Error('not logged in'); return sbRpc('update_match_meta', { p_token: s.token, p_match_id: mid, p_title: title }); }
  async function deleteMatch(mid) { var s = _sessRead(); if (!s || !s.token) throw new Error('not logged in'); return sbRpc('delete_match', { p_token: s.token, p_match_id: mid }); }

  global.PENTA = {
    SB_URL: SB_URL, SB_ANON: SB_ANON,
    sbSelect: sbSelect, sbInsert: sbInsert, sbRpc: sbRpc,
    ddVersion: ddVersion, ddChampMap: ddChampMap, champKey: champKey, champIcon: champIcon,
    champSplash: champSplash, champLoading: champLoading,
    itemIcon: itemIcon, spellIcon: spellIcon,
    posKo: posKo, posRank: posRank,
    queueName: queueName, mmss: mmss, kdaRatio: kdaRatio, compact: compact, ago: ago,
    groupKeyOf: groupKeyOf, clusterByMatch: clusterByMatch, pickPrimary: pickPrimary,
    saverCard: saverCard, heroCard: heroCard, bestMulti: bestMulti, grade: grade,
    likeGroup: likeGroup, viewGroup: viewGroup, statsAll: statsAll, statsOne: statsOne,
    session: session, sessionPuuid: sessionPuuid, loginWithCode: loginWithCode, lastLoginError: lastLoginError, loginViaRecorder: loginViaRecorder,
    whoami: whoami, logout: logout, initAuth: initAuth,
    updateMatchMeta: updateMatchMeta, deleteMatch: deleteMatch
  };
})(typeof window !== 'undefined' ? window : globalThis);
