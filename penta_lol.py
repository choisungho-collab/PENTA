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

    dur = info.get("gameDuration") or 0
    dur_sec = dur / 1000.0 if dur > 10000 else float(dur)
    dur_min = dur_sec / 60.0 if dur_sec else 0
    team_kills = {100: 0, 200: 0}
    for _p in parts:
        team_kills[100 if _p.get("teamId") == 100 else 200] += _p.get("kills") or 0

    players = []
    for p in parts:
        _k = p.get("kills") or 0; _d = p.get("deaths") or 0; _a = p.get("assists") or 0
        _tm = 100 if p.get("teamId") == 100 else 200
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
            # 효율 지표(판정·조언용)
            "cs_per_min": round(_cs(p) / dur_min, 1) if dur_min else 0,
            "kda": round((_k + _a) / max(1, _d), 2),
            "kp": round((_k + _a) / max(1, team_kills[_tm]), 2) if team_kills.get(_tm) else 0,
            "dpg": round((p.get("totalDamageDealtToChampions") or 0) / max(1, p.get("goldEarned") or 1), 2),
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

    # 라인전 격차(상대 라이너 대비)를 각 선수에 merge
    if timeline:
        _lanes = _lane_diffs(timeline, parts)
        for _i, _pl in enumerate(players):
            _pl["lane"] = _lanes.get(_i + 1, {})

    return {
        "players": players,
        "win_team": win_team,
        "duration": info.get("gameDuration"),   # 초 단위(과거 일부 게임은 ms일 수 있어 메인에서 보정)
        "queue": info.get("queueId"),
        "patch": info.get("gameVersion"),
        "objectives": objectives,
        "bans": bans,
        "series": _timeline_series(timeline) if timeline else None,
        "kills": _kill_events(timeline) if timeline else [],
        "objs": _obj_events(timeline) if timeline else [],
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


def _lane_diffs(timeline, parts):
    """각 선수의 10/15분 CS·골드를 상대 라이너(같은 포지션 반대팀)와 비교한 격차."""
    frames = ((timeline.get("info") or {}).get("frames")) or []
    def _frame_at(ms):
        best = None
        for f in frames:
            if (f.get("timestamp") or 0) <= ms:
                best = f
            else:
                break
        return best
    pos_team = {}
    for i, p in enumerate(parts):
        pos = (p.get("teamPosition") or "").upper()
        tm = 100 if p.get("teamId") == 100 else 200
        if pos:
            pos_team[(pos, tm)] = i + 1
    out = {}
    for i, p in enumerate(parts):
        pid = i + 1
        pos = (p.get("teamPosition") or "").upper()
        tm = 100 if p.get("teamId") == 100 else 200
        opp = pos_team.get((pos, 200 if tm == 100 else 100))
        d = {}
        for lbl, ms in (("10", 600000), ("15", 900000)):
            fr = _frame_at(ms)
            if not fr:
                continue
            pf = fr.get("participantFrames") or {}
            me = pf.get(str(pid)) or {}
            mcs = (me.get("minionsKilled") or 0) + (me.get("jungleMinionsKilled") or 0)
            mg = me.get("totalGold") or 0
            d["mycs" + lbl] = mcs
            if opp:
                op = pf.get(str(opp)) or {}
                ocs = (op.get("minionsKilled") or 0) + (op.get("jungleMinionsKilled") or 0)
                d["cs" + lbl] = mcs - ocs
                d["gold" + lbl] = mg - (op.get("totalGold") or 0)
        out[pid] = d
    return out


def _kill_events(timeline):
    """킬/데스 이벤트(시각·위치·관련자) — 영상 점프 + 데스 분석용."""
    frames = ((timeline.get("info") or {}).get("frames")) or []
    out = []
    for f in frames:
        for e in (f.get("events") or []):
            if e.get("type") == "CHAMPION_KILL":
                out.append({
                    "t": (e.get("timestamp") or 0) // 1000,
                    "killer": e.get("killerId"),
                    "victim": e.get("victimId"),
                    "assists": e.get("assistingParticipantIds") or [],
                    "pos": e.get("position"),
                    "bounty": e.get("shutdownBounty") or e.get("bounty") or 0,
                })
    return out


def _obj_events(timeline):
    """오브젝트(드래곤·바론·전령·타워) 처치 이벤트."""
    frames = ((timeline.get("info") or {}).get("frames")) or []
    out = []
    for f in frames:
        for e in (f.get("events") or []):
            t = e.get("type")
            if t == "ELITE_MONSTER_KILL":
                out.append({
                    "t": (e.get("timestamp") or 0) // 1000,
                    "kind": e.get("monsterType"),
                    "sub": e.get("monsterSubType"),
                    "killer": e.get("killerId"),
                    "team": e.get("killerTeamId"),
                })
            elif t == "BUILDING_KILL":
                out.append({
                    "t": (e.get("timestamp") or 0) // 1000,
                    "kind": "TOWER" if e.get("buildingType") == "TOWER_BUILDING" else "BUILDING",
                    "lane": e.get("laneType"),
                    "killer": e.get("killerId"),
                    "team": e.get("teamId"),
                })
    return out


# ===================== Live Client 기반 자체 분석 (Riot API 불필요) =====================
# 게임 중 Live Client Data API로 모은 스냅샷으로 분석을 만든다. Riot 개발자 키가 없어도 동작한다.
# 골드/딜량은 Live Client에 없어 비우고(웹이 자동 생략), KDA·CS·킬관여·라인 CS격차·이벤트·승패는 채운다.

def live_snapshot():
    """게임 중 한 시점의 스냅샷 {t, mode, players, my_gold?}. 게임 중이 아니면 None.
    주의: Live Client의 creepScore는 10 단위로만 갱신된다(정밀도 한계).
    my_gold: 활성 플레이어(나)의 현재 보유 골드 — 내 골드 추정 보정용(본인만 제공된다)."""
    gs = live_get("/gamestats")
    if not gs:
        return None
    pl = live_get("/playerlist") or []
    snap = {"t": gs.get("gameTime") or 0, "mode": gs.get("gameMode") or "", "players": pl}
    ap = live_get("/activeplayer")
    if ap and ap.get("currentGold") is not None:
        snap["my_gold"] = ap.get("currentGold")
    return snap


def live_events():
    """게임 이벤트 목록(누적). 게임이 끝나기 전에 받아둬야 한다."""
    return (live_get("/eventdata") or {}).get("Events") or []


def _pname(p):
    """playerlist 항목의 표시 이름 — riotIdGameName 우선, 없으면 riotId 앞부분/summonerName."""
    return p.get("riotIdGameName") or (p.get("riotId") or "").split("#")[0] or p.get("summonerName") or ""


def _item_gold(items):
    """playerlist items[]의 price를 합산 → 산 아이템 가치(골드 근사).
    Live Client는 items 각 항목에 price·count를 준다(완성/부품/소비템 모두).
    보유(미사용) 골드는 빠지므로 약간 과소하지만, 게임 종료 시점이면 대부분 아이템화돼 근사로 충분하다."""
    g = 0
    for it in (items or []):
        if isinstance(it, dict):
            g += int(it.get("price") or 0) * int(it.get("count") or 1)
    return g


def analyze_live(snaps, events, my_name):
    """게임 중 모은 Live Client 스냅샷 → 웹 갤러리 분석 구조(부분).
    채움: players(KDA/CS/레벨/와드/포지션/킬관여), 라인 CS격차(10분), 킬/오브젝트 이벤트, 승패.
    비움: 골드/딜량/딜골드비(Live Client 미제공) → 웹이 해당 항목을 자동으로 생략."""
    snaps = snaps or []
    events = events or []
    if not snaps:
        return {}
    last = snaps[-1]
    pl = last.get("players") or []
    if not pl:
        return {}

    def _team(p):
        return 100 if (p.get("team") == "ORDER") else 200

    def _sc(p):
        return p.get("scores") or {}

    dur_sec = float(last.get("t") or 0)
    dur_min = dur_sec / 60.0 if dur_sec else 0

    team_kills = {100: 0, 200: 0}
    for p in pl:
        team_kills[_team(p)] += (_sc(p).get("kills") or 0)

    my_team = None
    for p in pl:
        if _pname(p) == my_name:
            my_team = _team(p)
            break

    # 승패: GameEnd 이벤트의 Result(활성 플레이어=나 기준). 못 받으면 None(미확인).
    win_team = None
    for e in events:
        if e.get("EventName") == "GameEnd":
            res = e.get("Result")
            if res and my_team:
                win_team = my_team if res == "Win" else (200 if my_team == 100 else 100)
            break

    # 큐: ARAM이면 칼바람(450), 그 외는 None → 웹에서 '소환사의 협곡'
    mode = (last.get("mode") or "").upper()
    queue = 450 if mode == "ARAM" else None

    # 10분 시점 CS(라인전 격차용) — 600초에 가장 가까운 스냅샷(±75초 이내일 때만)
    cs10 = {}
    s10 = min(snaps, key=lambda s: abs(float(s.get("t") or 0) - 600))
    if abs(float(s10.get("t") or 0) - 600) <= 75:
        for p in (s10.get("players") or []):
            cs10[_pname(p)] = (_sc(p).get("creepScore") or 0)

    players = []
    for p in pl:
        s = _sc(p)
        _k = s.get("kills") or 0
        _d = s.get("deaths") or 0
        _a = s.get("assists") or 0
        tm = _team(p)
        nm = _pname(p)
        cs = s.get("creepScore") or 0
        gold = _item_gold(p.get("items"))
        if nm == my_name and last.get("my_gold"):
            gold += int(last.get("my_gold") or 0)  # 내 보유(미사용) 골드까지 더해 총획득에 근접
        win = (win_team == tm) if win_team else None
        players.append({
            "name": nm, "tag": p.get("riotIdTagLine"),
            "champion": p.get("championName"), "champ_id": None,
            "team": tm,
            "kills": _k, "deaths": _d, "assists": _a,
            "cs": cs, "gold": gold, "level": p.get("level"),
            "dmg": None, "vision": s.get("wardScore"),
            "items": [(it.get("itemID") if isinstance(it, dict) else it) for it in (p.get("items") or [])][:7],
            "spells": [], "position": p.get("position") or "",
            "win": win, "puuid": None,
            "pentas": 0, "quadras": 0, "triples": 0, "doubles": 0, "multi": 0,
            "cs_per_min": round(cs / dur_min, 1) if dur_min else 0,
            "kda": round((_k + _a) / max(1, _d), 2),
            "kp": round((_k + _a) / max(1, team_kills[tm]), 2) if team_kills.get(tm) else 0,
            "dpg": None,
        })

    # 라인전 CS 격차(같은 포지션 반대팀 vs 나) — 10분 CS 기준
    pos_team = {}
    for i, p in enumerate(players):
        pos = (p.get("position") or "").upper()
        if pos:
            pos_team[(pos, p["team"])] = i
    for p in players:
        pos = (p.get("position") or "").upper()
        if not pos:
            continue
        my_cs10 = cs10.get(p["name"])
        if my_cs10 is None:
            continue
        d = {"mycs10": int(my_cs10)}
        opp_i = pos_team.get((pos, 200 if p["team"] == 100 else 100))
        if opp_i is not None:
            opp_cs10 = cs10.get(players[opp_i]["name"])
            if opp_cs10 is not None:
                d["cs10"] = int(my_cs10 - opp_cs10)
        p["lane"] = d

    # 킬/오브젝트 이벤트 (killer/victim은 players 순서 기반 participant 번호 i+1로 변환)
    name_to_pid = {p["name"]: i + 1 for i, p in enumerate(players)}
    kills, objs = [], []
    _OBJ = {"DragonKill": "DRAGON", "BaronKill": "BARON_NASHOR",
            "HeraldKill": "RIFTHERALD", "TurretKilled": "TOWER"}
    for e in events:
        en = e.get("EventName") or ""
        t = int(float(e.get("EventTime") or 0))
        if en == "ChampionKill":
            kills.append({
                "t": t,
                "killer": name_to_pid.get(e.get("KillerName")),
                "victim": name_to_pid.get(e.get("VictimName")),
                "assists": [name_to_pid[a] for a in (e.get("Assisters") or []) if a in name_to_pid],
            })
        elif en in _OBJ:
            objs.append({"t": t, "kind": _OBJ[en]})

    return {
        "players": players, "win_team": win_team,
        "duration": int(dur_sec), "queue": queue,
        "patch": None, "objectives": {}, "bans": {},
        "series": None, "kills": kills, "objs": objs,
        "source": "live",
    }
