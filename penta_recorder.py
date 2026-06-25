#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PENTA — 리그 오브 레전드 자동 녹화 (한 번 실행하면 다 됨)
=====================================================
이 파일 하나만 실행하면:
  · 필요한 파이썬 패키지 자동 설치
  · ffmpeg(녹화기) 자동 다운로드 (처음 한 번)
  · 게임을 감지해 판마다 자동 녹화, Riot 공식 기록으로 전적 분석
  · 영상+전적을 Supabase에 업로드 → 웹 갤러리에 자동 등록, 브라우저 자동 오픈

그 다음부턴 리그 오브 레전드를 켜서 게임하면 → 판마다 자동 녹화 → 영상+전적이 갤러리에 자동 등록.
OBS 필요 없음. NVIDIA NVENC 하드웨어 인코딩이라 게임 성능 저하 거의 없음.

실행:  penta_recorder.exe 더블클릭
"""
import os, sys, json, time, socket, subprocess, datetime, traceback, threading

# --windowed(콘솔 없는 exe) 실행 시 sys.stdout 이 None → print 크래시 방지
class _NullIO:
    def write(self, *a): pass
    def flush(self): pass
if sys.stdout is None: sys.stdout = _NullIO()
if sys.stderr is None: sys.stderr = _NullIO()
# 윈도우 콘솔을 UTF-8 로 (한글·기호 깨짐/크래시 방지) — bat 없이 직접 실행해도 적용됨
if sys.platform == "win32":
    try: os.system("chcp 65001 >nul 2>&1")
    except Exception: pass
    for _s in (sys.stdout, sys.stderr):
        try: _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception: pass
# 콘솔 없이(pythonw / --windowed) 실행돼 stdout 이 없을 때 print 가 죽지 않도록
for _nm in ("stdout", "stderr"):
    if getattr(sys, _nm, None) is None:
        try: setattr(sys, _nm, open(os.devnull, "w", encoding="utf-8"))
        except Exception: pass
def _safe_input(prompt=""):
    try: return input(prompt)
    except Exception: return ""
def _run(args, **kw):
    kw.setdefault("creationflags", getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return subprocess.run(args, **kw)

FROZEN     = getattr(sys, "frozen", False)
APP_DIR    = os.path.dirname(sys.executable) if FROZEN else os.path.dirname(os.path.abspath(__file__))  # 쓰기 가능(exe 옆)
HERE       = APP_DIR

# ===================== 0. 의존성 자동 설치 =====================
def ensure_deps():
    if getattr(sys, "frozen", False): return   # exe(번들)면 패키지가 이미 포함됨
    need = []
    for mod, pkg in [("psutil", "psutil"), ("requests", "requests")]:
        try: __import__(mod)
        except ImportError: need.append(pkg)
    if need:
        print(f"[준비] 파이썬 패키지 설치 중: {', '.join(need)} …")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", *need])
        except Exception as e:
            print("[!] 패키지 자동 설치 실패. 수동으로 실행해 주세요:")
            print(f"    {sys.executable} -m pip install {' '.join(need)}")
            print("상세:", e); _safe_input("\n엔터를 누르면 종료..."); sys.exit(1)
ensure_deps()

import psutil
import penta_lol
import urllib.request, zipfile, io, webbrowser, shutil

# ===================== 경로 / 전역 =====================
def _data_root():
    # 업데이트(새 폴더에 압축 해제)해도 자료가 유지되도록 사용자 폴더에 고정 저장.
    # config.json 의 "data_dir" 로 바꿀 수 있음 (기본: 윈도우 %USERPROFILE%\ReplayCast).
    try:
        cfgp = os.path.join(HERE, "config.json")
        if os.path.isfile(cfgp):
            dd = (json.load(open(cfgp, encoding="utf-8")) or {}).get("data_dir")
            if dd: return os.path.expanduser(os.path.expandvars(dd))
    except Exception: pass
    if sys.platform == "win32":
        return os.path.join(os.environ.get("USERPROFILE") or HERE, "ReplayCast")
    return os.path.join(os.path.expanduser("~"), ".replaycast")
DATA_DIR   = os.path.join(_data_root(), "data")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
REC_DIR    = os.path.join(DATA_DIR, "recordings")
CONFIG_PATH= os.path.join(HERE, "config.json")
FPS        = 30
_PENTA_ICON = "iVBORw0KGgoAAAANSUhEUgAAAQAAAAEACAYAAABccqhmAAAG3klEQVR4nO3cy7HcRhIFUFAxRtESmiFjaIYsGa9mFlQHQbL7PaALn8q856xmFopoVGbeSkCklgUAAAAAAAAAAAAAAAAAAACAqfz3n7//d/dv4D5/3f0DgPsIgGCP298WkEsAQDABAMEEQKjf136vAZkEAAQTAIFe3fa2gDwCAIIJAAgmAMJ8tuZ7DcgiACCYAIBgAiDI1vXea0AOAQDBBEAItzrPCACeEhgZBAAEEwAB3Oa8IgB4SXD0JwAgmABobvQWtwX0JgAgmABozO3NZwQAnxIkfQkACCYAmnJrs4UAYBOB0pMAgGACoCG3NVsJADYTLP0IgGYMKXsIAAgmANjFhtGLAGjEcLKXAGA3QdOHAIBgAqAJtzLvEAC8ReD0IAAgmABowG3MuwQAbxM89QmA4gwhIwQABBMADLGB1CYACjN8jBIADBNEdQkACCYAinLrcgQBwCEEUk0CoCDDxlEEAAQTABzGZlKPACjGkHEkAQDBBACHsqHUIgAKMVwcTQBAMAFQRKXbv9JvTScAIJgA4BS2gBoEQAGGibMIAAgmADiNzWV+AmByhogzCQAIJgAm1uH27/AMnQkACCYAIJgAmFSn1bnTs3QjACCYAIBgAmBCHVfmjs/UgQCAYAJgMp1vys7PVpUAgGACAIIJgIkkrMgJz1iJAIBgX+7+ATNzW/Xw9dt3ff5CqYMxkFRQKXCGfqiBhPuNBM7QN4BKSQcdjc7gYQNsG4DrHHX5HvZvAWwDcI0jZ+3Qfw0oBOBcR8/Y4X8OQAjAOc6YrVOH1XcBGHfmpXrqnwS0DcCYs2fo9D8KLATgPVfMziV/F0AIwD5Xzczlg+m7ALx29WV5+d8GtA3Ac3fMxi1/HVgIwK/umonbB9ErAcnuvgxv/w+C3H0AcJcZev/2AFiWOQ4CrjRLz08RAMsyz4HA2Wbq9Wl+yJrvAnQ00+A/TLMBrM14UDBi1p6eMgCWZd4Dg71m7uVpA2BZ5j442GL2Hp76x635LkAlsw/+w9QbwFqVA4VKvVomAJal1sGSqVqPlgqAZal3wOSo2JvlfvCa7wLMoOLgP5TbANYqHzw9VO/B0gGwLPULQF0deq/8A6x5JeAKHQb/ofwGsNapMMypW4+1CoBl6Vcg5tGxt9oFwLL0LBT36tpTLR9qzXcBRnQd/IeWG8Ba9wJynoTeaR8Ay5JRSI6V0jMRAbAsOQVlXFKvxDzomu8CPJM0+A8xG8BaYqH5WGpPRAbAsuQWnD8l90Lsg695JciUPPgPsRvAmkbIo+Y/CIB/aYgcav2TAFjRGP2p8a8cxgu+C/Ri8J+zAbygYfpQy9cEwAc0Tn1q+DEB8AkNVJfafc4B7eC7QA0GfzsbwA4aa35qtI8A2EmDzUtt9hMAb9Bo81GT9zi0Qb4L3Mvgj7EBDNKA93H24wQABBMAg7wC3MfZjxMAEEwAQDABAMEEwADvoPdTgzECAIIJAAgmAN5k9ZyHWrxPAEAwAQDBBAAEEwBv8M45HzV5jwCAYAIAggmAnaya81Kb/QQABBMAEEwAQDABsIN3zPmp0T4CAIIJAAgmADayWtahVtsJAAgmACCYAIBgAmAD75T1qNk2AgCCCQAIJgA+YZWsS+0+JwAgmACAYAIAggmAD3iHrE8NP/afu38A9/n67fuXx/82KJlsAKHWw//s/5NB0V/oeiNuGfSOzy7gnrMBBNk6BIYlh28AAd4Z6Mc/03Eb4CcbQHOjt7ltoDfFfaLDrXfG4FY/F2H2JxtAQ2c1ugHqxzeARq4YUN8GerEB/KZqY199O1fcBqrW9kw2gOLuHETbQH02gMJmuYVn+R3sp3ArVW6ymQeuwhnOfH5XswEUM3vzzv77+JVvAEVUGizfBuqwARRQafjXqv7uJAr0rxlvq04DNNv5djrbETaASXVr0G7P04VvAJPpPCi+DczHBrDM05Cdh39thuecpeZ3swFMYIaBuJptYA42gJslDv9a+vPfzQZwE43/k23gPvFNeHXTGfyPqce1vAJcKL3Ztvj67fsX53QdAXABTb2f87pG9CFfsW5q5HFn1ym5RjaAk7j1j+MczyMATqBhjydQzyEADqRJz+d8jxV7mEe/V2rM6x1Zw9T62QAGufXv49zHCYABGvB+AnhM5MGNro4abk7qup8NYKfEJqnCNrCfANhIc9WhTtsJgA00VD0Ce5u4A9rznqiBelDz12wAL6Q1Qme2gdcEwG80S1/q+qeoA/lsFdQgOT7qhaQ+sAEsbv1E6v1DfABohFyCPzgAFJ+H5D6IefD1O19ywfnYo0/0SDP+k9NspVcAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAgPf8H5hWWD1n6UHFAAAAAElFTkSuQmCC"
REC_STATE  = {"rec": False, "text": "대기 중", "game": None}   # 실시간 녹화 상태(웹 표시용)
for d in (DATA_DIR, UPLOAD_DIR, REC_DIR): os.makedirs(d, exist_ok=True)
FFMPEG = None
CFG    = {}

import queue as _queue
GUI_Q = _queue.Queue(maxsize=4000)
REC_STATE = {"recording": False, "encoder": "", "ready": False}
LAST_ERR = {"msg": "", "t": 0.0}
_LOGFILE = {"p": None}
def log(m):
    line = f"[{datetime.datetime.now():%H:%M:%S}] {m}"
    try: print(line, flush=True)
    except Exception: pass
    s = str(m)
    if any(k in s for k in ("오류", "에러", "실패", "Traceback", "Error")) and ("다시 시작" not in s):
        LAST_ERR["msg"] = s[:240]; LAST_ERR["t"] = time.time()
    if "녹화 시작" in s: REC_STATE["recording"] = True
    elif ("녹화 종료" in s) or ("대기 상태" in s) or ("게임 종료" in s): REC_STATE["recording"] = False
    if "준비 완료. 리그" in s: REC_STATE["ready"] = True
    if s.startswith("인코더:"): REC_STATE["encoder"] = s.split("인코더:", 1)[1].strip()
    try: GUI_Q.put_nowait(line)
    except Exception: pass
    try:
        if _LOGFILE["p"]:
            with open(_LOGFILE["p"], "a", encoding="utf-8", errors="replace") as f: f.write(line + "\n")
    except Exception: pass

# ===================== 1. 설정 (자동 생성/탐지) =====================

def free_port(pref=8000):
    s = socket.socket()
    try:
        s.bind(("0.0.0.0", pref)); s.close(); return pref
    except OSError:
        s2 = socket.socket(); s2.bind(("0.0.0.0", 0)); p = s2.getsockname()[1]; s2.close(); return p

def open_app(url):
    """주소창·탭 없는 단독 앱 창으로 갤러리를 연다 (Edge/Chrome --app 모드).
    윈도우엔 Edge 가 항상 깔려 있어 별도 설치 불필요. 못 찾으면 일반 브라우저로 폴백."""
    try:
        cand = []
        for _n in ("msedge", "chrome"):
            _p = shutil.which(_n)
            if _p: cand.append(_p)
        for _base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                      os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
            cand.append(os.path.join(_base, "Microsoft", "Edge", "Application", "msedge.exe"))
            cand.append(os.path.join(_base, "Google", "Chrome", "Application", "chrome.exe"))
        _la = os.environ.get("LOCALAPPDATA", "")
        if _la: cand.append(os.path.join(_la, "Google", "Chrome", "Application", "chrome.exe"))
        _prof = os.path.join(DATA_DIR, "appwin")
        try: os.makedirs(_prof, exist_ok=True)
        except Exception: pass
        for _exe in cand:
            if _exe and os.path.isfile(_exe):
                subprocess.Popen([_exe, "--app=" + url, "--user-data-dir=" + _prof,
                                  "--no-first-run", "--no-default-browser-check",
                                  "--window-size=1240,840"])
                return True
    except Exception:
        pass
    try: webbrowser.open(url)
    except Exception: pass
    return False

def load_or_make_config():
    if os.path.isfile(CONFIG_PATH):
        cfg = json.load(open(CONFIG_PATH, encoding="utf-8"))
    else:
        cfg = {
            "mode": "all",
            "league_process": "League of Legends.exe",
            "proxy_url": "",
            "platform": "kr",
            "username": "",
            "supabase": {"url": "", "anon_key": "", "service_key": "", "bucket": "media"},
            "data_dir": "",
            "gallery_url": "",
            "encoder": "auto",   # auto | nvenc | x264
            "ui": "window",      # window | console  (window=보기 좋은 상태창, console=검은 cmd창)
            "scale": "auto",     # auto | source | 1080 | 720 | 480  (소프트웨어 인코딩이면 auto가 720p로 낮춰 게임 끊김 방지)
            "preset": "auto",    # auto | ultrafast | superfast | veryfast | fast ...  (libx264 속도/품질)
            "output_idx": "auto",   # auto | 0 | 1 | 2  (멀티모니터면 게임 있는 모니터 번호)
            "capture": "auto",   # auto | wgc | ddagrab | gdigrab   (wgc=OBS식, 전체화면도 잡힘)
            "port": free_port(8000),
            "fps": FPS,
            "poll_seconds": 4,
            "autostart": True, "min_game_sec": 300,
        }
        json.dump(cfg, open(CONFIG_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        log(f"설정 자동 생성됨 → {CONFIG_PATH}")
    # service_key 영구보관: 한 번 넣으면 data 폴더에 저장 → 이후 zip 통째로 덮어써도 유지
    try:
        _sk = ((cfg.get("supabase") or {}).get("service_key") or "").strip()
        _secret = os.path.join(DATA_DIR, "penta_secret.json")
        if _sk:
            json.dump({"service_key": _sk}, open(_secret, "w", encoding="utf-8"))
        elif os.path.isfile(_secret):
            _v = (json.load(open(_secret, encoding="utf-8")) or {}).get("service_key") or ""
            if _v: cfg.setdefault("supabase", {})["service_key"] = _v
    except Exception: pass
    return cfg

# ===================== ffmpeg 자동 다운로드 =====================
def ensure_audio():
    """pyaudiowpatch(WASAPI 루프백) 준비 — 없으면 자동 설치. 실패해도 무음으로 진행(영상엔 영향 없음)."""
    try:
        import pyaudiowpatch  # noqa
        return True
    except Exception:
        pass
    try:
        log("소리 엔진 준비 중(pyaudiowpatch, 처음 한 번)…")
        _run([sys.executable, "-m", "pip", "install", "-q", "pyaudiowpatch", "--break-system-packages"], timeout=300)
        import pyaudiowpatch  # noqa
        log("소리 엔진 준비 완료.")
        return True
    except Exception as e:
        log(f"  (소리) pyaudiowpatch 자동 설치 실패 → 무음 녹화. 수동: pip install pyaudiowpatch ({e})")
        return False

def ensure_ffmpeg():
    local = os.path.join(HERE, "ffmpeg.exe")
    if os.path.isfile(local): return local
    found = shutil.which("ffmpeg")
    if found: return found
    log("ffmpeg 다운로드 중… (~90MB, 처음 한 번만, 1~2분)")
    sources = [
        ("BtbN", "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"),
        ("gyan-essentials", "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"),
        ("gyan-full", "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-full.zip"),
    ]
    # BtbN 최신 릴리스에서 win64-gpl 자산을 동적으로 찾아 추가 (파일명이 또 바뀌어도 대응)
    try:
        api = urllib.request.Request("https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/latest",
                                     headers={"User-Agent": "Mozilla/5.0", "Accept": "application/vnd.github+json"})
        rel = json.loads(urllib.request.urlopen(api, timeout=30).read().decode("utf-8"))
        for a in rel.get("assets", []):
            n = a.get("name", "")
            if "win64-gpl" in n and n.endswith(".zip") and "shared" not in n and "lgpl" not in n:
                sources.append(("BtbN-api", a["browser_download_url"])); break
    except Exception:
        pass
    for label, url in sources:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            data = urllib.request.urlopen(req, timeout=180).read()
            z = zipfile.ZipFile(io.BytesIO(data))
            member = next(n for n in z.namelist() if n.lower().endswith("/bin/ffmpeg.exe"))
            with z.open(member) as src, open(local, "wb") as dst:
                shutil.copyfileobj(src, dst)
            try:
                pm = next((n for n in z.namelist() if n.lower().endswith("/bin/ffprobe.exe")), None)
                if pm:
                    with z.open(pm) as src, open(os.path.join(HERE, "ffprobe.exe"), "wb") as dst:
                        shutil.copyfileobj(src, dst)
            except Exception:
                pass
            log(f"ffmpeg 준비 완료. (출처: {label})")
            return local
        except Exception as e:
            log(f"    {label} 실패: {e} → 다음 소스 시도")
    log("[!] ffmpeg 자동 다운로드에 모두 실패했어요. 수동으로 받아주세요:")
    log("    1) https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip 다운로드")
    log("    2) 압축 풀고 그 안의  bin\\ffmpeg.exe  를 찾아")
    log(f"    3) 이 폴더에 복사:  {HERE}")
    log("    4) penta_recorder.exe 다시 실행")
    return None


# API가 죽었을 때(레이트리밋/504) 폴백할 알려진 버전들


# ===================== 인게스트 (영상 등록) =====================
_CNT = {"n": 0, "t": 0.0, "busy": False}
def _sb_count_cached():
    now = time.time()
    if (now - _CNT["t"] > 15) and not _CNT["busy"]:
        _CNT["busy"] = True
        def _refresh():
            try: _CNT["n"] = sb_count_matches()
            except Exception: pass
            finally: _CNT["t"] = time.time(); _CNT["busy"] = False
        threading.Thread(target=_refresh, daemon=True).start()
    return _CNT["n"]
def count_matches():
    return _sb_count_cached()
# ===================== 코치 리포트 (규칙 기반, API 불필요) =====================


# ===================== Supabase 클라우드 (DB + Storage) =====================
# config 의 "supabase" 를 채우면 자동으로 켜짐. 비어 있으면 전부 로컬(SQLite)로 동작.
# Supabase 공개 기본값 — anon_key 는 공개돼도 안전(RLS 가 데이터 보호). config.json 이 없거나 비어 있어도 클라우드 모드로 동작.
SB_DEFAULTS = {
    "url": "https://luljnalcnxfyxmlgoxbc.supabase.co",
    "anon_key": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imx1bGpuYWxjbnhmeXhtbGdveGJjIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODIwMDU1NDIsImV4cCI6MjA5NzU4MTU0Mn0.WhPOfWiOlokOHVZLmffIKKTDpQunhxwwwJOd6CSoC2k",
    "bucket": "media",
}
def sb_cfg():
    s = dict(CFG.get("supabase") or {})
    for _k in ("url", "anon_key", "bucket"):
        if not s.get(_k): s[_k] = SB_DEFAULTS[_k]
    return s
def sb_writable():
    """업로드(쓰기) 가능 = url + (service_role 또는 anon 키). anon은 RLS 정책 범위 내에서 쓰기."""
    s = sb_cfg(); return bool(s.get("url") and (s.get("service_key") or s.get("anon_key")))
def cloud_state():
    """('cloud'|'readonly'|'local')"""
    s = sb_cfg()
    if s.get("url") and (s.get("service_key") or s.get("anon_key")): return "cloud"
    return "local"
def _sb_base(): return (sb_cfg().get("url") or "").rstrip("/")
def _sb_key(write=False):
    s = sb_cfg()
    return (s.get("service_key") or s.get("anon_key")) if write else (s.get("anon_key") or s.get("service_key"))
def _sb_h(write=False, body_json=True):
    k = _sb_key(write); h = {"apikey": k}
    if k and k.startswith("eyJ"): h["Authorization"] = "Bearer " + k   # legacy(JWT) 키만 Authorization; 새 publishable/secret 키는 apikey만
    if body_json: h["Content-Type"] = "application/json"
    return h
def _sb_bucket(): return sb_cfg().get("bucket") or "media"
def sb_upload(local, path, ctype):
    """Supabase Storage 업로드 → 공개 URL (버킷이 public 이어야 함)."""
    import requests
    base = _sb_base(); bk = _sb_bucket(); k = _sb_key(write=True)
    _hh = _sb_h(write=True, body_json=False); _hh["Content-Type"] = ctype; _hh["x-upsert"] = "true"
    with open(local, "rb") as f:
        r = requests.post("%s/storage/v1/object/%s/%s" % (base, bk, path), data=f,
                          headers=_hh, timeout=(10, 3600))
    if r.status_code not in (200, 201):
        raise RuntimeError("storage %s: %s" % (r.status_code, r.text[:200]))
    return "%s/storage/v1/object/public/%s/%s" % (base, bk, path)
def sb_insert_match(row):
    import requests
    r = requests.post(_sb_base() + "/rest/v1/matches",
                      headers={**_sb_h(write=True), "Prefer": "resolution=merge-duplicates,return=minimal"},
                      data=json.dumps(row, ensure_ascii=False).encode("utf-8"), timeout=60)
    if r.status_code not in (200, 201, 204):
        raise RuntimeError("insert %s: %s" % (r.status_code, r.text[:200]))
def sb_count_matches():
    import requests
    r = requests.get(_sb_base() + "/rest/v1/matches?select=id",
                     headers={**_sb_h(body_json=False), "Prefer": "count=exact", "Range": "0-0"}, timeout=30)
    cr = r.headers.get("content-range", "")
    try: return int(cr.split("/")[-1])
    except Exception:
        try: return len(r.json())
        except Exception: return 0


def _trim_lead(video_path, game_len_sec, lead=6.0):
    """로비/로딩 구간을 잘라 카운트다운(게임 시작 ~6초 전)부터 시작하게. 게임은 영상 끝에서 game_len_sec 길이라 끝에서 역산(-sseof)."""
    if not (FFMPEG and video_path and game_len_sec): return
    try:
        keep = float(game_len_sec) + lead
        tmp = video_path + ".trim.mp4"
        r = _run([FFMPEG, "-y", "-loglevel", "error", "-sseof", f"-{keep:.2f}",
                  "-i", video_path, "-c", "copy", "-avoid_negative_ts", "make_zero", tmp],
                 capture_output=True)
        if r.returncode == 0 and os.path.isfile(tmp) and os.path.getsize(tmp) > 1024:
            os.replace(tmp, video_path)
            log("영상 앞 로비/로딩을 잘라 카운트다운부터 시작하도록 정리했어")
        else:
            try: os.remove(tmp)
            except OSError: pass
    except Exception as e:
        log(f"영상 트림 건너뜀(원본 유지): {e}")


# ===================== 영상 처리 =====================

def make_thumb(video, out, at=None):
    if not FFMPEG: return False
    cands = []
    if at is not None and at > 0: cands.append(f"{float(at):.2f}")
    cands += ["120", "60", "20", "5", "1", "0.5"]
    for ts in cands:
        try:
            _run([FFMPEG, "-y", "-loglevel", "error", "-ss", ts, "-i", video,
                            "-frames:v", "1", "-vf", "scale=640:-2", out], timeout=30)
            if os.path.isfile(out) and os.path.getsize(out) > 2000:
                return True
        except Exception:
            pass
    return False


# ===================== 6. 녹화기 (ffmpeg) =====================
_ENC_CACHE = None
_ENC_IS_SW = False   # 소프트웨어(libx264) 인코딩 여부 → 다운스케일 판단에 사용
def _encoder_args():
    """인코더 자동 선택. NVENC는 '실제로 인코딩 되는지'까지 테스트 — 목록엔 있어도 런타임 실패면 libx264로."""
    global _ENC_CACHE, _ENC_IS_SW
    if _ENC_CACHE is not None: return _ENC_CACHE
    pref = (CFG.get("encoder") or "auto").lower()
    have = ""
    try:
        have = _run([FFMPEG, "-hide_banner", "-encoders"],
                              capture_output=True, text=True, timeout=15).stdout or ""
    except Exception: pass
    def _nvenc_ok():
        # 256x256 같은 초소형은 NVENC가 거부할 수 있어 720p로 테스트. 실패하면 진짜 에러를 보여줌.
        try:
            r = _run([FFMPEG, "-hide_banner", "-loglevel", "error",
                                "-f", "lavfi", "-i", "color=c=black:s=1280x720:r=30:d=1",
                                "-c:v", "h264_nvenc", "-pix_fmt", "yuv420p", "-f", "null", "-"],
                               capture_output=True, text=True, timeout=30)
            if r.returncode != 0:
                errs = [l for l in (r.stderr or "").splitlines() if l.strip()]
                if errs: log("  NVENC 오류: " + "  /  ".join(errs[-2:]))
                return False
            return True
        except Exception as e:
            log(f"  NVENC 테스트 예외: {e}")
            return False
    if pref == "nvenc":
        use_nvenc = True
    elif pref in ("x264", "libx264", "software", "cpu"):
        use_nvenc = False
    else:  # auto — 실제 인코딩 테스트
        use_nvenc = ("h264_nvenc" in have) and _nvenc_ok()
        if ("h264_nvenc" in have) and not use_nvenc:
            log("  NVENC가 목록엔 있지만 실제 인코딩에 실패 → 소프트웨어(libx264)로 전환")
    if use_nvenc:
        _ENC_IS_SW = False
        _ENC_CACHE = ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", "20"]; name = "NVENC (NVIDIA 하드웨어)"
    else:
        _ENC_IS_SW = True
        preset = (CFG.get("preset") or "auto").lower()
        if preset in ("auto", ""): preset = "superfast"   # 소프트웨어는 게임 끊김 방지 위해 가벼운 프리셋
        _ENC_CACHE = ["-c:v", "libx264", "-preset", preset, "-crf", "25"]; name = f"libx264 (소프트웨어, {preset})"
    log(f"인코더: {name}")
    return _ENC_CACHE

def _target_height(src_h=0):
    """소프트웨어 인코딩이면 부하를 줄이려 다운스케일할 목표 높이. None이면 원본 유지."""
    _encoder_args()  # _ENC_IS_SW 확정
    pref = str(CFG.get("scale") or "auto").lower()
    if pref in ("source", "원본", "full", "native", "off", "0"): return None
    if pref in ("1080", "1080p"): th = 1080
    elif pref in ("720", "720p"): th = 720
    elif pref in ("480", "480p"): th = 480
    elif pref in ("1440", "1440p"): th = 1440
    else:  # auto: 소프트웨어면 720p로, 하드웨어(NVENC)면 원본
        th = 720 if _ENC_IS_SW else None
    if th is None: return None
    if src_h and src_h <= th: return None   # 업스케일 금지
    return th

def _scale_vf(src_h=0):
    """(-vf 인자 리스트, filter_complex 체인에 붙일 문자열) 반환. 다운스케일 불필요하면 둘 다 비움."""
    th = _target_height(src_h)
    if not th: return [], ""
    expr = f"scale=-2:'min({th},ih)':flags=fast_bilinear"
    return ["-vf", expr], "," + expr

class Recorder:
    # ddagrab = Desktop Duplication API. 윈10/11에선 '전체화면(독점)'도 잡힙니다.
    # gdigrab = 옛날 GDI 방식. 전체화면 독점에선 검은 화면이라 보조용.
    def __init__(self, fps):
        self.fps = fps; self.proc = None; self.path = None
        self.mode = "ddagrab"; self.output_idx = 0; self.verified = False; self.warned_black = False
        self.backend = "ffmpeg"; self.verified_backend = None
        self._wgc_control = None; self._wgc_state = None
        self._t_start = 0.0; self.last_seconds = 0.0   # 직전 녹화 길이(초) — 메뉴 클립/실제 게임 구분용
        self._aud = None; self._vt0 = None   # 오디오(WASAPI 루프백) 상태 + 영상 첫 프레임 시각
    def _cmd(self, out, mode, output_idx=0):
        enc = _encoder_args()
        vf, chain = _scale_vf(0)   # 데스크톱 높이를 모르므로 min() 식이 런타임에 처리(업스케일 안 함)
        tail = [*enc, "-pix_fmt", "yuv420p", "-movflags", "+faststart", out]
        if mode == "ddagrab":
            return [FFMPEG, "-y", "-loglevel", "error",
                    "-filter_complex", f"ddagrab=output_idx={output_idx}:framerate={self.fps},hwdownload,format=bgra{chain}", *tail]
        return [FFMPEG, "-y", "-loglevel", "error", "-f", "gdigrab",
                "-framerate", str(self.fps), "-i", "desktop", *vf, *tail]
    def _spawn(self, mode, output_idx=0):
        self.path = os.path.join(REC_DIR, f"clip_{datetime.datetime.now():%Y%m%d_%H%M%S}.mp4")
        self.proc = subprocess.Popen(self._cmd(self.path, mode, output_idx),
                      stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                      creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self._vt0 = time.time()
    def _alive(self):
        return self.proc is not None and self.proc.poll() is None
    def _capturing(self, secs=3.0, floor=40000):
        # 녹화 파일이 실제로 커지면 = 화면이 잡히는 것. 검은 화면이면 거의 안 커짐.
        try: s0 = os.path.getsize(self.path)
        except OSError: s0 = 0
        time.sleep(secs)
        try: s1 = os.path.getsize(self.path)
        except OSError: s1 = 0
        return (s1 - s0) >= floor
    def _kill(self):
        if self.proc:
            try: self.proc.terminate(); self.proc.wait(timeout=5)
            except Exception:
                try: self.proc.kill()
                except Exception: pass
        self.proc = None
        try:  # 빈(검은) 클립은 삭제
            if self.path and os.path.isfile(self.path) and os.path.getsize(self.path) < 40000:
                os.remove(self.path)
        except OSError: pass
    def _recording(self):
        if self.backend == "wgc":
            st = self._wgc_state or {}
            ft = st.get("feeder")
            return bool(ft and ft.is_alive())   # 피더 스레드가 죽으면 녹화가 끊긴 것
        return self._alive()

    def _start_audio(self):
        """시스템 사운드(게임 소리)를 WASAPI 루프백으로 WAV에 병렬 녹음.
        Windows 내장 기능이라 Stereo Mix·가상케이블 없이 어떤 PC에서도 동작.
        실패하면 무음으로 진행(영상 녹화는 영향 없음)."""
        self._stop_audio(discard=True); self._vt0 = None
        self.audio_path = os.path.join(REC_DIR, f"audio_{datetime.datetime.now():%Y%m%d_%H%M%S}.wav")
        box = {"stop": threading.Event(), "t0": None, "thread": None, "ok": False, "path": self.audio_path}
        def worker():
            try:
                import pyaudiowpatch as pa, wave
            except Exception as e:
                log(f"  (소리) pyaudiowpatch 미설치 → 무음 녹화. 설치: pip install pyaudiowpatch ({e})"); return
            p = stream = wf = None
            try:
                p = pa.PyAudio()
                try:
                    dev = p.get_default_wasapi_loopback()           # 기본 출력장치의 루프백
                except Exception:
                    wi = p.get_host_api_info_by_type(pa.paWASAPI)   # 폴백: 직접 탐색
                    spk = p.get_device_info_by_index(wi["defaultOutputDevice"]); dev = None
                    for lb in p.get_loopback_device_info_generator():
                        if spk.get("name","") in lb.get("name",""): dev = lb; break
                    if dev is None: raise RuntimeError("WASAPI 루프백 장치를 찾지 못함")
                ch = int(dev.get("maxInputChannels") or 2) or 2
                rate = int(dev.get("defaultSampleRate") or 48000) or 48000
                wf = wave.open(box["path"], "wb"); wf.setnchannels(ch); wf.setsampwidth(2); wf.setframerate(rate)
                stream = p.open(format=pa.paInt16, channels=ch, rate=rate, input=True,
                                input_device_index=dev["index"], frames_per_buffer=2048)
                box["t0"] = time.time(); box["ok"] = True
                log(f"  ♪ 소리 녹음 시작 ({str(dev.get('name','?'))[:26]} · {rate}Hz {ch}ch)")
                while not box["stop"].is_set():
                    try: wf.writeframes(stream.read(2048, exception_on_overflow=False))
                    except Exception: break
            except Exception as e:
                log(f"  (소리) 캡처 실패 → 무음 녹화: {e}")
            finally:
                for fn in (lambda: stream and stream.stop_stream(), lambda: stream and stream.close(),
                           lambda: wf and wf.close(), lambda: p and p.terminate()):
                    try: fn()
                    except Exception: pass
        t = threading.Thread(target=worker, daemon=True); box["thread"] = t; t.start()
        self._aud = box

    def _stop_audio(self, discard=False):
        box = self._aud; self._aud = None
        if not box: return (None, None)
        try: box["stop"].set()
        except Exception: pass
        th = box.get("thread")
        if th:
            try: th.join(timeout=8)
            except Exception: pass
        path = box.get("path"); t0 = box.get("t0")
        if discard:
            try:
                if path and os.path.isfile(path): os.remove(path)
            except OSError: pass
            return (None, None)
        return (path if box.get("ok") else None, t0)

    def _finalize(self):
        """영상 클립 + 병렬 녹음한 소리를 합쳐 최종 mp4. 소리 없으면 영상만 그대로."""
        vid = self.path if (self.path and os.path.isfile(self.path)) else None
        wav, at0 = self._stop_audio()
        if not vid:
            try:
                if wav and os.path.isfile(wav): os.remove(wav)
            except OSError: pass
            return None
        if not (wav and os.path.isfile(wav) and os.path.getsize(wav) > 2000):
            return vid                                  # 소리 없음 → 영상만(기존 동작)
        if not FFMPEG:
            return vid
        try:
            out = (vid[:-4] if vid.lower().endswith(".mp4") else vid) + "_av.mp4"
            voff = 0.0
            if self._vt0 and at0 and self._vt0 > at0:
                voff = min(10.0, self._vt0 - at0)       # 영상이 늦게 시작한 만큼 소리 앞부분을 잘라 싱크
            cmd = [FFMPEG, "-y", "-loglevel", "error"]
            if voff > 0.05: cmd += ["-ss", f"{voff:.3f}"]
            cmd += ["-i", wav, "-i", vid, "-map", "1:v:0", "-map", "0:a:0",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    "-movflags", "+faststart", "-shortest", out]
            _run(cmd, timeout=900)
            if os.path.isfile(out) and os.path.getsize(out) > 40000:
                for f in (vid, wav):
                    try: os.remove(f)
                    except OSError: pass
                self.path = out; log("■ 소리 합치기 완료"); return out
            log("  (소리) 합치기 결과가 비어 영상만 사용")
            try:
                if os.path.isfile(out): os.remove(out)
            except OSError: pass
            return vid
        except Exception as e:
            log(f"  (소리) 합치기 실패 → 영상만: {e}"); return vid

    def _start_wgc(self, verify=True):
        """WGC(OBS식)로 프레임을 받아 ffmpeg로 인코딩. 정지화면이어도 직전 프레임을 고정 fps로 계속 먹임(전체화면 게임도 잡힘)."""
        try:
            from windows_capture import WindowsCapture
        except ImportError:
            try:
                log("WGC 엔진 설치 중(windows-capture)…")
                _run([sys.executable, "-m", "pip", "install", "-q", "windows-capture", "--break-system-packages"], timeout=240)
                from windows_capture import WindowsCapture
            except Exception as e:
                log(f"  WGC 사용 불가(설치 실패: {e})"); return False
        try:
            import numpy as _np
        except Exception as e:
            log(f"  WGC 사용 불가(numpy 없음: {e})"); return False
        self.path = os.path.join(REC_DIR, f"clip_{datetime.datetime.now():%Y%m%d_%H%M%S}.mp4")
        enc = _encoder_args(); pathx = self.path; fps = self.fps
        shared = {"buf": None, "wh": None, "n": 0, "err": None}
        stop_ev = threading.Event(); proc_box = {"p": None}
        try:
            cap = WindowsCapture(cursor_capture=None, draw_border=None, monitor_index=1, window_name=None)
        except Exception as e:
            log(f"  WGC 초기화 실패: {e}"); return False

        @cap.event
        def on_frame_arrived(frame, capture_control):
            if stop_ev.is_set():
                try: capture_control.stop()
                except Exception: pass
                return
            try:
                shared["buf"] = frame.frame_buffer          # numpy 처리는 피더에서 (콜백은 최대한 단순하게)
                shared["wh"] = (frame.width, frame.height)
                shared["n"] = shared.get("n", 0) + 1
            except Exception as e:
                if shared.get("err") is None: shared["err"] = repr(e)

        @cap.event
        def on_closed():
            pass

        def feeder():
            t0 = time.time()
            while shared["buf"] is None and time.time() - t0 < 3.0 and not stop_ev.is_set():
                time.sleep(0.05)
            if shared["buf"] is None: return            # 프레임이 하나도 안 옴 = 캡처 실패
            w, h = shared["wh"]
            vf, _chain = _scale_vf(h)
            cmd = [FFMPEG, "-y", "-loglevel", "error",
                   "-f", "rawvideo", "-pixel_format", "bgra", "-video_size", f"{w}x{h}", "-framerate", str(fps),
                   "-i", "pipe:", *vf, *enc, "-pix_fmt", "yuv420p", "-movflags", "+faststart", pathx]
            if vf: log(f"  소프트웨어 부하↓: {h}p 캡처 → {_target_height(h)}p 로 인코딩")
            errlog = os.path.join(REC_DIR, "wgc_ffmpeg.log")
            try: _ef = open(errlog, "w", encoding="utf-8", errors="replace")
            except Exception: _ef = subprocess.DEVNULL
            try:
                p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                     stderr=_ef, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except Exception:
                return
            proc_box["p"] = p; self._vt0 = time.time()
            interval = 1.0 / max(1, fps); nxt = time.time()
            while not stop_ev.is_set():
                b = shared["buf"]
                if b is not None:
                    try:
                        if b.shape[1] != w: b = b[:, :w]            # 스트라이드 보정
                        p.stdin.write(_np.ascontiguousarray(b).tobytes())
                    except Exception: break
                nxt += interval; d = nxt - time.time()
                if d > 0: time.sleep(d)
                else: nxt = time.time()
            try: p.stdin.close()
            except Exception: pass
            try: p.wait(timeout=15)
            except Exception:
                try: p.terminate()
                except Exception: pass

        try:
            control = cap.start_free_threaded()
        except Exception as e:
            log(f"  WGC 시작 실패: {e}"); return False
        ft = threading.Thread(target=feeder, daemon=True); ft.start()
        self._wgc_control = control
        self._wgc_state = {"stop": stop_ev, "feeder": ft, "proc_box": proc_box}
        self.backend = "wgc"
        if not verify:
            log("● 녹화 시작 (WGC)"); return True
        # --- WGC 검증 ---
        # WGC는 프레임 카운터로 '화면 잡힘'을 직접 확인할 수 있다. 파일 크기는 ffmpeg가 쓰는 중인지 확인용.
        # (NVENC는 첫 키프레임을 측정 전에 쓰고 정적 화면에선 이후 증가가 작아, '델타 40KB' 방식은 오판함 → 절대 크기로 판단)
        def _fflog():
            try:
                _lp = os.path.join(REC_DIR, "wgc_ffmpeg.log")
                if os.path.isfile(_lp):
                    _ls = [l for l in open(_lp, encoding="utf-8", errors="replace").read().strip().splitlines() if l.strip()]
                    return " | ".join(_ls[-3:])
            except Exception: pass
            return ""
        def _sz():
            try: return os.path.getsize(self.path)
            except OSError: return 0
        time.sleep(3.5)   # NVENC 첫 키프레임 + 인코딩 시작 시간 확보
        n1 = shared.get("n", 0)
        pp = proc_box.get("p"); alive = (pp is not None and pp.poll() is None)
        ferr = _fflog()
        ok = (n1 >= 15) and alive and (not ferr)   # 프레임 들어옴 + ffmpeg 정상 동작
        if ok and _sz() >= 8000:
            log("● 녹화 시작 (WGC — 화면 캡처 정상 확인)"); return True
        if ok:                                       # 파일이 아직 작으면(정적 화면) 잠깐 더 대기 후 재확인
            time.sleep(2.5)
            if _sz() >= 8000:
                log("● 녹화 시작 (WGC — 화면 캡처 정상 확인)"); return True
        stop_ev.set()
        try: control.stop()
        except Exception: pass
        try: ft.join(timeout=5)
        except Exception: pass
        self.backend = "ffmpeg"; self._wgc_control = None; self._wgc_state = None
        log("  WGC 캡처 안 됨 (받은 프레임:{}개, ffmpeg:{}, 파일:{}B, 에러:{}) → 다른 방식 시도".format(
            n1, "동작중" if alive else "종료됨", _sz(), ferr or "없음"))
        return False

    def start(self):
        if self._recording(): return True
        self._t_start = time.time()   # 새 클립 시작 시각
        self._start_audio()   # 시스템 사운드 병렬 녹음(백엔드 무관, PC 안 탐)
        capmode = (CFG.get("capture") or "auto").lower()
        # 검증된 방식 빠른 재시작
        if self.verified:
            try:
                if self.verified_backend == "wgc":
                    if self._start_wgc(verify=False): return True
                else:
                    self._spawn(self.mode, self.output_idx); time.sleep(1.0)
                    if self._alive():
                        log(f"● 녹화 시작 ({'모니터 '+str(self.output_idx) if self.mode=='ddagrab' else 'gdigrab'})"); return True
            except Exception: pass
            self.verified = False
        # 1순위: WGC (auto/wgc) — 전체화면도 잡히는 OBS식 엔진
        if capmode in ("auto", "wgc"):
            try:
                if self._start_wgc(verify=True):
                    self.verified = True; self.verified_backend = "wgc"; return True
            except Exception as e:
                log(f"WGC 오류: {e}")
            if capmode == "wgc":
                log("  WGC 실패 → ddagrab/gdigrab 폴백")
        # 2순위: ddagrab(모니터 0/1/2) → gdigrab
        ci = CFG.get("output_idx", "auto")
        if isinstance(ci, int) or (isinstance(ci, str) and ci.isdigit()):
            candidates = [("ddagrab", int(ci)), ("gdigrab", 0)]
        else:
            candidates = [("ddagrab", 0), ("ddagrab", 1), ("ddagrab", 2), ("gdigrab", 0)]
        for mode, idx in candidates:
            try:
                self._spawn(mode, idx); time.sleep(2.0)
                if not self._alive():
                    continue
                if self._capturing():
                    self.mode = mode; self.output_idx = idx; self.backend = "ffmpeg"
                    self.verified = True; self.verified_backend = "ffmpeg"; self.warned_black = False
                    log(f"● 녹화 시작 ({'모니터 '+str(idx) if mode=='ddagrab' else 'gdigrab'}) — 화면 캡처 정상 확인")
                    return True
                self._kill()
            except Exception as e:
                log(f"녹화 시작 오류({mode} #{idx}): {e}"); self._kill()
        if not self.warned_black:
            self.warned_black = True
            log("[!] 화면 캡처를 확인 못 했어요(검은 화면일 수 있음). 그래도 녹화는 계속합니다.")
            log("    • 먼저 한 판 하고 녹화된 영상을 확인해 보세요 (로딩 화면 오탐일 수 있음)")
            log("    • config.json 의 \"capture\" 를 \"wgc\" 로 바꾸거나, 리그 오브 레전드를 '창 모드(전체 화면)'로 해보세요")
        try:
            self._spawn("ddagrab", 0); time.sleep(1.0); self.mode = "ddagrab"; self.output_idx = 0; self.backend = "ffmpeg"
            return self._alive()
        except Exception:
            self.proc = None; return False
    def stop(self):
        self.last_seconds = (time.time() - self._t_start) if self._t_start else 0.0
        if self.backend == "wgc":
            st = self._wgc_state or {}
            ev = st.get("stop")
            if ev: ev.set()
            try:
                if self._wgc_control: self._wgc_control.stop()
            except Exception: pass
            ft = st.get("feeder")
            if ft:
                try: ft.join(timeout=20)   # 피더가 ffmpeg stdin 닫고 마무리
                except Exception: pass
            self.backend = "ffmpeg"; self._wgc_control = None; self._wgc_state = None
            log("■ 녹화 종료")
            return self._finalize()
        if not self.proc: return None
        p = self.proc; self.proc = None
        try:
            if p.poll() is None:
                try: p.stdin.write(b"q"); p.stdin.flush()
                except Exception: pass
                try: p.wait(timeout=12)
                except subprocess.TimeoutExpired: p.terminate()
        except Exception: pass
        log("■ 녹화 종료")
        return self._finalize()

def sc_running(name):
    n = name.lower()
    for p in psutil.process_iter(["name"]):
        try:
            if (p.info["name"] or "").lower() == n: return True
        except (psutil.NoSuchProcess, psutil.AccessDenied): pass
    return False


def _sec_mmss(s):
    s = int(s or 0)
    return f"{s//60}:{s%60:02d}"

def _discard(video_path, reason):
    log(f"  저장하지 않고 버립니다 — {reason}")
    try:
        if video_path and os.path.isfile(video_path): os.remove(video_path)
    except OSError: pass

def ingest_lol(video_path, riot_id, start_ts, end_ts, proxy_url, platform="kr"):
    # 화면 녹화 + (게임 종료 후) Riot 매치를 연결해 분석·업로드한다.
    if not video_path or not os.path.isfile(video_path) or os.path.getsize(video_path) < 10000:
        log("영상이 비어있어 등록 생략."); return
    if not riot_id:
        return _discard(video_path, "내 Riot ID를 확인하지 못함(게임이 아니었을 수 있음)")
    if not proxy_url:
        log("proxy_url 미설정 — 영상은 로컬에 두고 분석은 생략합니다."); return
    match, puuid = penta_lol.resolve_match(proxy_url, riot_id, start_ts, end_ts, platform)
    if not match:
        return _discard(video_path, "녹화 시간과 일치하는 매치를 찾지 못함")
    info = match.get("info") or {}
    mid = (match.get("metadata") or {}).get("matchId") or str(info.get("gameId") or "")
    if not mid:
        return _discard(video_path, "matchId 없음")
    timeline = penta_lol.proxy_get(proxy_url, "timeline", matchId=mid, platform=platform)
    analysis = penta_lol.analyze_match(match, timeline)
    dur = analysis.get("duration") or 0
    if dur and dur > 100000: dur = dur / 1000.0    # 과거 게임은 길이가 ms일 수 있어 보정
    if dur and dur < CFG.get("min_game_sec", 300):
        return _discard(video_path, f"게임이 너무 짧음({int(dur)}초)")
    gid = mid
    row_id = gid + "__" + (puuid or "x").replace("/", "_")   # 시점별 고유 행 id(멀티 POV 충돌 방지)
    safe = row_id.replace("/", "_")
    size = os.path.getsize(video_path)
    base = os.path.join(UPLOAD_DIR, safe); os.makedirs(base, exist_ok=True)
    try:
        if dur: _trim_lead(video_path, dur)   # 로비/로딩 잘라 게임 시작부터 보이게
    except Exception: pass
    if not sb_writable():
        log("클라우드(Supabase)가 설정되지 않아 로컬 보관만 합니다."); return
    tmp_thumb = os.path.join(base, "thumb.jpg"); has_thumb = make_thumb(video_path, tmp_thumb)
    try:
        video_url = sb_upload(video_path, f"videos/{safe}.mp4", "video/mp4")
        thumb_url = sb_upload(tmp_thumb, f"thumbs/{safe}.jpg", "image/jpeg") if has_thumb else None
        players = analysis.get("players") or []
        me = next((p for p in players if p.get("puuid") == puuid), None)
        won = (me or {}).get("win")
        saver = (me or {}).get("name") or riot_id.split("#")[0]
        sb_insert_match({
            "id": row_id, "match_id": gid, "uploader": saver,
            "uploaded": datetime.datetime.now().isoformat(timespec="seconds"),
            "video": video_url, "thumb": thumb_url, "replay": None,
            "video_size": size or 0,
            "map": "Summoner's Rift", "matchup": None,
            "length": _sec_mmss(dur), "length_sec": int(dur or 0),
            "type": str(analysis.get("queue") or ""),
            "winner": analysis.get("win_team"), "saver": saver,
            "np": len(players), "players": players, "won": won,
            "analysis": analysis,
        })
        log(f"업로드 완료 — matchId {gid}")
    except Exception as e:
        log(f"업로드 실패: {e}")

def recorder_loop(cfg):
    proc = cfg.get("league_process", "League of Legends.exe")
    proxy = cfg.get("proxy_url", ""); platform = cfg.get("platform", "kr")
    poll = float(cfg.get("poll_seconds", 4)); rec = Recorder(int(cfg.get("fps", FPS)))
    was = False; active = False; riot_id = None; start_ts = None
    try: ensure_audio()
    except Exception: pass
    if not proxy:
        log("주의: config.json의 proxy_url이 비어 있습니다. Netlify 프록시 주소를 넣어야 분석이 연결됩니다.")
    log("준비 완료. 리그 오브 레전드 게임을 시작하면 자동으로 녹화됩니다. (이 창은 켜둔 채로 두세요)")
    while True:
        try:
            run = sc_running(proc)   # 게임 인스턴스(League of Legends.exe) = 인게임
            if run and not was:
                log("게임 감지됨. 내 정보 확인 중...")
                for _ in range(20):
                    if penta_lol.game_active():
                        riot_id = penta_lol.my_riot_id() or riot_id; break
                    time.sleep(1)
                start_ts = time.time(); active = rec.start()
            if run:
                if not rec._recording():
                    if active: log("녹화 스트림이 끊겨 자동으로 다시 시작합니다.")
                    active = rec.start()
                if not riot_id and penta_lol.game_active():
                    riot_id = penta_lol.my_riot_id()
            if not run and was:
                log("게임 종료 감지.")
                vid = rec.stop(); active = False; rec.verified = False
                end_ts = time.time()
                if vid and os.path.isfile(vid):
                    threading.Thread(target=ingest_lol, args=(vid, riot_id, start_ts, end_ts, proxy, platform), daemon=True).start()
                riot_id = None; start_ts = None; log("대기 상태.")
            # 웹 표시용 실시간 상태 갱신
            if run and rec._recording():
                REC_STATE.update(rec=True, text="녹화 중")
            elif run:
                REC_STATE.update(rec=False, text="게임 감지됨")
            else:
                REC_STATE.update(rec=False, text="대기 중 — 게임을 시작하면 자동 녹화")
            was = run; time.sleep(poll)
        except KeyboardInterrupt:
            log("종료합니다."); rec.stop(); break
        except Exception:
            log("오류:\n" + traceback.format_exc()); time.sleep(poll)

# ===================== main =====================

_MUTEX = None
def _single_instance():
    """이미 실행 중이면 False (자동 실행 + 수동 더블클릭 겹침 방지)."""
    global _MUTEX
    if sys.platform != "win32": return True
    try:
        import ctypes
        _MUTEX = ctypes.windll.kernel32.CreateMutexW(None, False, "PENTA_Recorder_SingleInstance")
        return ctypes.windll.kernel32.GetLastError() != 183   # 183 = ERROR_ALREADY_EXISTS
    except Exception:
        return True

def _autostart_cmd():
    """자동 실행에 등록할 명령. 빌드된 .exe(frozen)일 때만 반환 (개발 모드는 등록 안 함)."""
    if getattr(sys, "frozen", False):
        return '"%s"' % os.path.abspath(sys.executable)
    return None

def set_autostart(enable):
    """윈도우 시작 시 자동 실행 등록/해제 (HKCU Run). 실패해도 앱엔 영향 없음."""
    if sys.platform != "win32": return False
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Run",
                             0, winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE)
        if enable:
            cmd = _autostart_cmd()
            if not cmd: winreg.CloseKey(key); return False
            winreg.SetValueEx(key, "PENTA", 0, winreg.REG_SZ, cmd)
            log("윈도우 시작 시 자동 실행 등록됨 (끄려면 config.json 의 autostart 를 false 로)")
        else:
            try: winreg.DeleteValue(key, "PENTA")
            except FileNotFoundError: pass
        winreg.CloseKey(key)
        return True
    except Exception as e:
        log(f"자동 실행 설정 건너뜀: {e}")
        return False

def is_autostart():
    if sys.platform != "win32": return False
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Run",
                             0, winreg.KEY_QUERY_VALUE)
        v, _ = winreg.QueryValueEx(key, "PENTA"); winreg.CloseKey(key)
        return bool(v)
    except Exception:
        return False

def _apply_autostart(cfg):
    """frozen .exe 에서만, config 값에 맞춰 자동 실행 등록/해제."""
    if not getattr(sys, "frozen", False): return
    want = bool(cfg.get("autostart", True))
    if want != is_autostart():
        set_autostart(want)

def _hide_console():
    if sys.platform != "win32": return
    try:
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd: ctypes.windll.user32.ShowWindow(hwnd, 0)   # SW_HIDE
    except Exception: pass

def run_gui(cfg, url):
    """아주 작은 상태 표시줄. 평소엔 상태만, 문제가 있을 때만 로그가 펼쳐진다."""
    import tkinter as tk
    import tkinter.font as _tkfont
    BG="#0A1015"; SURF="#15212E"; INK="#F0E6D2"; INK2="#CDBE91"; DIM="#A09B8C"; FAINT="#62605A"
    JADE="#C8AA6E"; JADE2="#F0DCA8"; REC="#E8526A"; AMB="#C8AA6E"; LINE="#1E2D3A"; LINE2="#2C3F4F"
    W = 444
    root = tk.Tk(); root.title("PENTA"); root.configure(bg=BG)
    try: root.iconphoto(True, tk.PhotoImage(data=_PENTA_ICON))
    except Exception: pass
    try:
        _fam=set(_tkfont.families())
        def _pick(*c):
            for f in c:
                if f in _fam: return f
            return c[-1]
    except Exception:
        def _pick(*c): return c[0]
    KOR=_pick("Malgun Gothic","맑은 고딕","Segoe UI"); LAT=_pick("Segoe UI","Malgun Gothic"); MON=_pick("Consolas","Cascadia Mono","Segoe UI")
    BASE_H, SET_H, LOG_H = 200, 210, 208
    root.geometry(f"{W}x{BASE_H}"); root.resizable(False, True)
    st = {"log": False, "settings": False}

    head = tk.Frame(root, bg=BG); head.pack(fill="x", padx=14, pady=(10,0))
    mk = tk.Canvas(head, width=22, height=17, bg=BG, highlightthickness=0); mk.pack(side="left", pady=(2,0))
    mk.create_polygon(11,1, 13,6.2, 18.6,6.5, 14.2,10, 15.7,15.5, 11,12.4, 6.3,15.5, 7.8,10, 3.4,6.5, 9,6.2, fill=JADE2, outline="")
    tk.Label(head, text="PENTA", bg=BG, fg=INK, font=(LAT,13,"bold")).pack(side="left", padx=(7,0))
    games_lbl = tk.Label(head, text="", bg=BG, fg=DIM, font=(MON,9)); games_lbl.pack(side="right")
    _cs = cloud_state()
    _cmap = {"cloud": (JADE2, "☁ 클라우드"), "readonly": (AMB, "⚠ 키 필요"), "local": (DIM, "● 로컬")}
    _cc, _ct = _cmap[_cs]
    tk.Label(head, text=_ct, bg=SURF, fg=_cc, font=(KOR,9,"bold"), padx=8, pady=2).pack(side="right", padx=(0,9))

    midf = tk.Frame(root, bg=BG); midf.pack(fill="x", padx=14, pady=(6,0))
    dot = tk.Canvas(midf, width=12, height=12, bg=BG, highlightthickness=0); dot.pack(side="left", pady=(5,0))
    did = dot.create_oval(1,1,11,11, fill=FAINT, outline="")
    stx = tk.Frame(midf, bg=BG); stx.pack(side="left", padx=(9,0))
    status_lbl = tk.Label(stx, text="시작 중…", bg=BG, fg=INK, font=(KOR,16,"bold"), anchor="w"); status_lbl.pack(anchor="w")
    sub_lbl = tk.Label(stx, text="", bg=BG, fg=DIM, font=(KOR,9), anchor="w"); sub_lbl.pack(anchor="w")

    logwrap = tk.Frame(root, bg=BG)
    errbar = tk.Label(logwrap, text="", bg="#3A1E18", fg="#ffb4a6", font=(KOR,9), anchor="w",
                      padx=10, pady=6, justify="left", wraplength=W-40)
    logtxt = tk.Text(logwrap, bg="#0C0D10", fg=DIM, font=(MON,9), bd=0, padx=10, pady=8,
                     height=8, wrap="word", state="disabled")

    # === 콜백 ===
    def open_gallery():
        try: open_app(url)
        except Exception: pass
    def open_folder():
        try:
            if sys.platform == "win32": os.startfile(REC_DIR)
        except Exception: pass
    def do_quit():
        try: root.destroy()
        except Exception: pass
        os._exit(0)
    def _save_cfg():
        try: json.dump(cfg, open(CONFIG_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        except Exception as e: log(f"설정 저장 실패: {e}")

    # === 녹화 설정 패널 (접이식) ===
    PANEL = "#0B0C0F"
    optwrap = tk.Frame(root, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
    tk.Label(optwrap, text="녹화 설정", bg=PANEL, fg=INK2, font=(KOR,9,"bold")).pack(anchor="w", padx=14, pady=(11,5))
    SCALE_OPTS=[("자동 (최상)","auto"),("원본 해상도","source"),("1080p","1080"),("720p","720"),("480p","480")]
    ENC_OPTS=[("자동 (GPU 우선)","auto"),("GPU · NVENC","nvenc"),("CPU · x264","x264")]
    CAP_OPTS=[("자동","auto"),("WGC (전체화면 OK)","wgc"),("DDA","ddagrab"),("GDI","gdigrab")]
    MON_OPTS=[("자동","auto"),("모니터 1","0"),("모니터 2","1"),("모니터 3","2")]
    def opt_row(label, opts, key):
        row = tk.Frame(optwrap, bg=PANEL); row.pack(fill="x", padx=14, pady=3)
        tk.Label(row, text=label, bg=PANEL, fg=INK2, font=(KOR,9), width=6, anchor="w").pack(side="left")
        cur = str(cfg.get(key, "auto")); m = {l: v for l, v in opts}
        curlbl = next((l for l, v in opts if v == cur), opts[0][0])
        var = tk.StringVar(value=curlbl)
        def on_sel(lbl, k=key, mp=m, lb=label):
            cfg[k] = mp[lbl]; _save_cfg(); log(f"설정: {lb} → {lbl} (다음 녹화부터 적용)")
        om = tk.OptionMenu(row, var, *[l for l, _ in opts], command=on_sel)
        om.config(bg="#181B21", fg=INK, font=(KOR,9), activebackground="#23272F", activeforeground=INK,
                  relief="flat", bd=0, highlightthickness=1, highlightbackground=LINE2, anchor="w", padx=10, pady=4, cursor="hand2")
        try: om["menu"].config(bg=SURF, fg=INK, activebackground=JADE, activeforeground="#fff", font=(KOR,9), bd=0, activeborderwidth=0)
        except Exception: pass
        om.pack(side="left", fill="x", expand=True)
    opt_row("화질", SCALE_OPTS, "scale")
    opt_row("인코더", ENC_OPTS, "encoder")
    opt_row("캡처", CAP_OPTS, "capture")
    opt_row("모니터", MON_OPTS, "output_idx")
    tk.Label(optwrap, text="기본값(자동)이 최상 화질 — GPU로 게임 끊김 없이 녹화합니다", bg=PANEL, fg=DIM,
             font=(KOR,8), wraplength=W-48, justify="left").pack(anchor="w", padx=14, pady=(5,11))

    # === 패널 토글 + 리사이즈 ===
    def _resize():
        h = BASE_H + (SET_H if st["settings"] else 0) + (LOG_H if st["log"] else 0)
        root.geometry(f"{W}x{h}")
    def set_log(open_):
        if open_ and st["settings"]: set_settings(False)
        st["log"] = open_
        if open_:
            logwrap.pack(fill="both", expand=True, padx=11, pady=(0,7))
            if LAST_ERR.get("msg"): errbar.config(text="\u26a0 " + LAST_ERR["msg"]); errbar.pack(fill="x", pady=(0,5))
            else: errbar.pack_forget()
            logtxt.pack(fill="both", expand=True); logtog.config(text="로그 \u25b4")
        else:
            logwrap.pack_forget(); logtog.config(text="로그 \u25be")
        _resize()
    def set_settings(open_):
        if open_ and st["log"]: set_log(False)
        st["settings"] = open_
        if open_: optwrap.pack(fill="x", padx=12, pady=(2,2)); settog.config(text="\u2699 설정 \u25b4", fg=JADE)
        else: optwrap.pack_forget(); settog.config(text="\u2699 설정", fg=DIM)
        _resize()
    def toggle_log(): set_log(not st["log"])
    def toggle_settings(): set_settings(not st["settings"])

    # === 버튼 헬퍼 ===
    def btn(parent, text, cmd, primary=False):
        base = JADE if primary else "#181B21"; hov = JADE2 if primary else "#23272F"; fg = "#FFFFFF" if primary else INK
        bord = JADE if primary else LINE2
        b = tk.Label(parent, text=text, bg=base, fg=fg, font=(KOR,10,"bold"), padx=15, pady=9, cursor="hand2",
                     highlightthickness=1, highlightbackground=bord, highlightcolor=bord)
        b.bind("<Button-1>", lambda e: cmd())
        b.bind("<Enter>", lambda e: b.config(bg=hov)); b.bind("<Leave>", lambda e: b.config(bg=base))
        return b
    def link(parent, text, cmd, color=DIM):
        l = tk.Label(parent, text=text, bg=BG, fg=color, font=(KOR,9,"bold"), cursor="hand2")
        l.bind("<Button-1>", lambda e: cmd())
        l.bind("<Enter>", lambda e: l.config(fg=INK)); l.bind("<Leave>", lambda e: l.config(fg=color))
        return l

    # === 액션 버튼 행 ===
    tk.Frame(root, bg=LINE, height=1).pack(fill="x", padx=14, pady=(11,0))
    acts = tk.Frame(root, bg=BG); acts.pack(fill="x", padx=13, pady=(10,0))
    btn(acts, "갤러리", open_gallery, primary=True).pack(side="left")
    btn(acts, "폴더 열기", open_folder).pack(side="left", padx=(7,0))

    # === 푸터 (토글 + 종료) ===
    foot = tk.Frame(root, bg=BG); foot.pack(side="bottom", fill="x", padx=15, pady=(8,10))
    settog = link(foot, "\u2699 설정", toggle_settings, DIM); settog.pack(side="left")
    logtog = link(foot, "로그 \u25be", toggle_log, DIM); logtog.pack(side="left", padx=(16,0))
    link(foot, "종료", do_quit, DIM).pack(side="right")
    root.protocol("WM_DELETE_WINDOW", do_quit)

    def _prep_and_run():
        global FFMPEG
        try:
            if not FFMPEG: FFMPEG = ensure_ffmpeg()
        except Exception as e:
            log(f"도구 준비 중 문제: {e}")
        if not FFMPEG:
            log("\u26a0 ffmpeg 준비 실패 — 인터넷 연결 확인 후 다시 실행해 주세요."); return
        recorder_loop(cfg)
    threading.Thread(target=_prep_and_run, daemon=True).start()

    def poll():
        appended = False
        for _ in range(150):
            try: line = GUI_Q.get_nowait()
            except Exception: break
            if st["log"]:
                logtxt.config(state="normal"); logtxt.insert("end", line + "\n"); appended = True
        if appended:
            n = int(logtxt.index("end-1c").split(".")[0])
            if n > 300: logtxt.delete("1.0", f"{n-300}.0")
            logtxt.see("end"); logtxt.config(state="disabled")
        if REC_STATE.get("recording"):
            dot.itemconfig(did, fill=REC); status_lbl.config(text="녹화 중", fg=REC); sub_lbl.config(text="게임 화면 녹화 중")
        elif REC_STATE.get("ready"):
            dot.itemconfig(did, fill=JADE); status_lbl.config(text="대기 중", fg=INK); sub_lbl.config(text="게임 켜면 자동 녹화")
        else:
            dot.itemconfig(did, fill=AMB); status_lbl.config(text="준비 중…", fg=INK); sub_lbl.config(text="최초 실행 — 도구 준비 중 (1~2분)")
        try:
            n = count_matches(); e = (REC_STATE.get("encoder") or "").split()
            games_lbl.config(text=(f"경기 {n} · {e[0]}" if e else f"경기 {n}"))
        except Exception: pass
        if LAST_ERR.get("msg") and (time.time() - LAST_ERR.get("t", 0) < 8):
            if not st["log"]: set_log(True)
            else: errbar.config(text="\u26a0 " + LAST_ERR["msg"])
        root.after(500, poll)

    try: root.update()
    except Exception: pass
    if sys.platform == "win32": _hide_console()   # py.exe 로 돌려도 콘솔창 숨김
    poll()
    try: root.mainloop()
    except Exception as ex: log(f"GUI 창 종료: {ex}")

def _print_status():
    s = sb_cfg(); st = cloud_state()
    print("\n" + "=" * 50)
    print("  PENTA 상태 점검")
    print("=" * 50)
    print(f"  데이터 폴더 : {DATA_DIR}")
    print("-" * 50)
    print(f"  Supabase URL : {s.get('url') or '(없음)'}")
    print(f"  anon_key     : {'있음' if s.get('anon_key') else '없음'}")
    print(f"  service_key  : {'있음' if s.get('service_key') else '없음  ← 업로드하려면 필요'}")
    print(f"  bucket       : {s.get('bucket') or 'media'}")
    verdict = {"cloud": "☁ 클라우드 ON (업로드 가능)",
               "readonly": "⚠ 읽기전용 (service_key 입력 필요)",
               "local": "● 로컬 전용"}[st]
    print(f"\n  → {verdict}")
    if s.get("url") and (s.get("service_key") or s.get("anon_key")):
        print("\n  Supabase 연결 테스트 중...")
        try:
            import requests
            r = requests.get(_sb_base() + "/rest/v1/matches?select=id&limit=1", headers=_sb_h(), timeout=12)
            if r.status_code < 300:
                print("  ✓ 연결 OK — matches 테이블 읽기 성공")
                try:
                    r2 = requests.get(_sb_base() + "/rest/v1/matches?select=id",
                                      headers={**_sb_h(), "Prefer": "count=exact", "Range": "0-0"}, timeout=12)
                    cr = r2.headers.get("content-range", "")
                    if "/" in cr: print(f"    ☁ 클라우드 저장된 경기: {cr.split('/')[-1]}개")
                except Exception: pass
                if s.get("service_key"):
                    try:
                        rb = requests.get(_sb_base() + "/storage/v1/bucket/" + (_sb_bucket()),
                                          headers=_sb_h(write=True), timeout=12)
                        if rb.status_code < 300: print(f"  ✓ Storage 버킷 '{_sb_bucket()}' 접근 OK (업로드 준비됨)")
                        else: print(f"  ✗ 버킷 접근 실패: HTTP {rb.status_code} — 버킷 이름/키 확인")
                    except Exception as e: print(f"  ✗ 버킷 테스트 오류: {e}")
            else:
                print(f"  ✗ 연결 실패: HTTP {r.status_code} — {r.text[:140]}")
                print("    (키가 틀렸거나 테이블이 없을 수 있어요. schema.sql 실행했는지 확인)")
        except Exception as e:
            print(f"  ✗ 연결 테스트 오류: {e}")
    print("=" * 50)

def main():
    global FFMPEG, CFG
    cfg = load_or_make_config(); CFG = cfg
    try: _apply_autostart(cfg)
    except Exception: pass
    if "--status" in sys.argv or "--check" in sys.argv:
        _print_status()
        try: input("\n엔터로 종료...")
        except Exception: pass
        return
    # 이미 실행 중이면(자동 실행 + 수동 실행 겹침) 갤러리만 열고 종료
    if not _single_instance():
        try: open_app((cfg.get("gallery_url") or "https://mypenta.netlify.app/").rstrip("/"))
        except Exception: pass
        return
    try: _LOGFILE["p"] = os.path.join(DATA_DIR, "recorder.log")
    except Exception: pass
    mode = cfg.get("mode", "all")
    use_gui = (mode == "all" and sys.platform == "win32" and cfg.get("ui", "window") != "console")
    print("=" * 56); print(f"  PENTA — 리그 오브 레전드 자동 녹화 — 모드: {mode}"); print("=" * 56)
    _cst = cloud_state()
    if _cst == "cloud":
        log(f"☁ 클라우드 ON — Supabase({_sb_base()}) 에 저장·공유됩니다.")
    elif _cst == "readonly":
        log("⚠ 클라우드 읽기전용 — config.json 의 supabase.service_key 가 비어있어요. 채우고 재시작하면 업로드가 켜져요.")
    else:
        log("● 로컬 모드 — 이 PC에만 저장됩니다. (config.json 의 supabase 를 채우면 클라우드 ON)")
    if mode in ("all", "recorder"):
        if not use_gui:               # GUI면 창부터 띄우고 백그라운드에서 받음(첫 실행이 멈춘 듯 안 보이게)
            FFMPEG = ensure_ffmpeg()
            if not FFMPEG:
                _safe_input("\nffmpeg가 없어 녹화를 할 수 없어요. 엔터로 종료..."); return
    if mode in ("all", "server") and not use_gui:
        if not FFMPEG: FFMPEG = ensure_ffmpeg()
    url = (cfg.get("gallery_url") or "https://mypenta.netlify.app/").rstrip("/")
    if mode == "all":
        log(f"갤러리 → {url}")
        try: open_app(url)
        except Exception: pass
        # 보기 좋은 상태창(GUI). 윈도우 + tkinter 가능하면 GUI로, 아니면 콘솔로.
        if sys.platform == "win32" and (cfg.get("ui", "window") != "console"):
            try:
                import tkinter  # noqa: F401  (가용성 확인)
                run_gui(cfg, url); return
            except Exception as e:
                log(f"GUI 사용 불가({e}) → 콘솔 모드로 계속")
    if mode in ("all", "recorder"):
        if not FFMPEG: FFMPEG = ensure_ffmpeg()
        print("-" * 56); recorder_loop(cfg)

if __name__ == "__main__":
    main()
