# PENTA — LoL 데이터 레이어
# 게임 감지(Live Client Data API) + Riot API 프록시 호출 + 매치 매핑 + 분석 변환.
# 녹화/업로드/GUI는 메인 녹화기(penta_recorder.py)가 담당하고, 이 모듈은 "무슨 게임이고 결과가 무엇인지"만 책임진다.

import json
import ssl
import time
import urllib.request
import urllib.parse

# ===================== Live Client Data API =====================
# 게임 클라이언트가 게임 중에만 로컬에 띄우는 REST. 자기 게임 데이터만 제공(스펙테이터 아님).
# self-signed 인증서라 검증을 끈다.

LIVE = "https://127.0.0.1:2999/liveclientdata"
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


def live_get(path, timeout=2):
    try:
        req = urllib.request.Request(LIVE + path)
        with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def game_active():
    """게임이 진행 중이면 True (Live Client가 응답하면 인게임)."""
    return live_get("/gamestats") is not None


def game_time():
    """현재 게임 경과 시간(초). 게임 중이 아니면 None."""
    s = live_get("/gamestats")
    return (s or {}).get("gameTime")


def my_riot_id():
    """인게임 활성 플레이어(나)의 Riot ID. 형식 '이름#태그'. 게임 중에만 유효."""
    p = live_get("/activeplayer")
    rid = (p or {}).get("riotId")
    return rid


# ===================== Riot API 프록시 =====================
# 키는 프록시(Netlify Function)에만 있다. 녹화기는 키를 모른다.

def proxy_get(proxy_url, action, timeout=12, **params):
    if not proxy_url:
        return None
    qs = "&".join(
        "%s=%s" % (k, urllib.parse.quote(str(v)))
        for k, v in params.items() if v is not None
    )
    url = proxy_url.rstrip("/") + "/api/riot?action=" + action + (("&" + qs) if qs else "")
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def _overlaps(a0, a1, b0, b1, tol=180):
    """두 시간 구간이 (tol초 여유 안에서) 겹치는지."""
    return not (a1 < b0 - tol or a0 > b1 + tol)


def resolve_match(proxy_url, riot_id, start_ts, end_ts, platform="kr"):
    """
    게임이 끝난 뒤, 내 최근 매치들 중 녹화 시간대와 일치하는 매치를 찾는다.
    반환: (match_json, puuid) 또는 (None, None).
    LoL 리플레이는 자동 저장되지 않으므로, 화면 녹화 시각을 Riot 매치의 시작/종료 시각과 맞춰 연결한다.
    """
    acc = proxy_get(proxy_url, "account", riotId=riot_id, platform=platform)
    puuid = (acc or {}).get("puuid")
    if not puuid:
        return None, None
    ids = proxy_get(proxy_url, "matches", puuid=puuid, count=5, platform=platform)
    if not isinstance(ids, list) or not ids:
        return None, puuid
    for mid in ids:
        m = proxy_get(proxy_url, "match", matchId=mid, platform=platform)
        info = (m or {}).get("info") or {}
        gstart = info.get("gameStartTimestamp")
        gend = info.get("gameEndTimestamp")
        if gstart:
            g0 = gstart / 1000.0
            g1 = (gend / 1000.0) if gend else g0
            if _overlaps(g0, g1, start_ts, end_ts):
                return m, puuid
    return None, puuid  # 시간 일치 매치 없음 — 오연결 방지를 위해 폴백하지 않음


# ===================== Match-V5 → 갤러리 분석 =====================
# 필드명은 Match-V5 스키마 기준. 실제 응답으로 한 번 검증 후 미세 조정 필요할 수 있음.

def _cs(p):
    return (p.get("totalMinionsKilled") or 0) + (p.get("neutralMinionsKilled") or 0)


def analyze_match(match, timeline=None):
    """Match-V5(+Timeline) → 웹 갤러리가 쓰는 분석 구조."""
    info = match.get("info") or {}
    parts = info.get("participants") or []

    players = []
    for p in parts:
        players.append({
            "name": p.get("riotIdGameName") or p.get("summonerName"),
            "tag": p.get("riotIdTagline"),
            "champion": p.get("championName"),
            "champ_id": p.get("championId"),
            "team": 100 if p.get("teamId") == 100 else 200,
            "kills": p.get("kills"), "deaths": p.get("deaths"), "assists": p.get("assists"),
            "cs": _cs(p),
            "gold": p.get("goldEarned"),
            "level": p.get("champLevel"),
            "dmg": p.get("totalDamageDealtToChampions"),
            "vision": p.get("visionScore"),
            "items": [p.get("item%d" % i) for i in range(7)],
            "spells": [p.get("summoner1Id"), p.get("summoner2Id")],
            "position": p.get("teamPosition") or p.get("individualPosition"),
            "win": bool(p.get("win")),
            "puuid": p.get("puuid"),
            # 멀티킬(PENTA 하이라이트). 0이면 표시 안 함.
            "pentas": p.get("pentaKills") or 0,
            "quadras": p.get("quadraKills") or 0,
            "triples": p.get("tripleKills") or 0,
            "doubles": p.get("doubleKills") or 0,
            "multi": p.get("largestMultiKill") or 0,
        })

    # 승리 팀
    win_team = None
    for tm in (info.get("teams") or []):
        if tm.get("win"):
            win_team = tm.get("teamId")
            break
    if win_team is None and parts:
        win_team = 100 if any(p.get("teamId") == 100 and p.get("win") for p in parts) else 200

    # 오브젝트(드래곤/바론/전령/타워) + 밴
    objectives = {}
    bans = {}
    for tm in (info.get("teams") or []):
        tid = tm.get("teamId")
        objectives[tid] = tm.get("objectives")
        bans[tid] = [b.get("championId") for b in (tm.get("bans") or []) if b.get("championId", -1) > 0]

    return {
        "players": players,
        "win_team": win_team,
        "duration": info.get("gameDuration"),   # 초 단위(과거 일부 게임은 ms일 수 있어 메인에서 보정)
        "queue": info.get("queueId"),
        "patch": info.get("gameVersion"),
        "objectives": objectives,
        "bans": bans,
        "series": _timeline_series(timeline) if timeline else None,
    }


def _timeline_series(timeline):
    """Timeline의 분당 프레임 → 팀별 골드 추이(역전 시점 시각화용)."""
    frames = ((timeline.get("info") or {}).get("frames")) or []
    pts = []
    for f in frames:
        t = (f.get("timestamp") or 0) // 1000
        pf = f.get("participantFrames") or {}
        g100 = g200 = 0
        for k, v in pf.items():
            try:
                pid = int(k)
            except (TypeError, ValueError):
                continue
            gold = v.get("totalGold") or 0
            if pid <= 5:
                g100 += gold
            else:
                g200 += gold
        pts.append({"t": t, "g100": g100, "g200": g200})
    return pts


def saver_won(analysis, puuid):
    """녹화한 사람(puuid)이 이겼는지."""
    for p in (analysis.get("players") or []):
        if p.get("puuid") == puuid:
            return p.get("win")
    return None
