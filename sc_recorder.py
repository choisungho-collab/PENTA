#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
스타크래프트 자동 녹화 — 올인원 (한 번 실행하면 다 됨)
=====================================================
이 파일 하나만 실행하면:
  · 필요한 파이썬 패키지 자동 설치
  · ffmpeg(녹화기) 자동 다운로드 (처음 한 번)
  · screp(메타데이터 파서) 자동 다운로드 시도 (선택)
  · 리플레이 자동저장 폴더 자동 탐지
  · 갤러리 사이트 + 녹화기를 한 프로세스로 같이 실행, 브라우저 자동 오픈

그 다음부턴 스타 켜서 게임하면 → 판마다 자동 녹화 → 영상+리플레이가 갤러리에 자동 등록.
OBS 필요 없음. NVIDIA NVENC 하드웨어 인코딩이라 게임 성능 저하 거의 없음.

실행:  START.bat 더블클릭   (또는  python sc_recorder.py)
"""
import os, sys, json, time, glob, socket, subprocess, datetime, traceback, threading
import sqlite3, secrets
from collections import Counter, defaultdict
from urllib.parse import quote

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
BUNDLE_DIR = getattr(sys, "_MEIPASS", APP_DIR)                                                          # 번들 읽기전용(web/)
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

import psutil, requests
import urllib.request, zipfile, io, webbrowser, re, html, shutil

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
INDEX_PATH = os.path.join(DATA_DIR, "index.json")
DB_PATH    = os.path.join(DATA_DIR, "matches.db")
CONFIG_PATH= os.path.join(HERE, "config.json")
WEB_DIR    = os.path.join(BUNDLE_DIR, "web")
FPS        = 30
_ENCORE_ICON = "iVBORw0KGgoAAAANSUhEUgAAAQAAAAEACAYAAABccqhmAAAG6klEQVR4nO3dv67URhjG4SHiIpCQqChPQ82NcQncGDXNKamQkLgLUq2yMfvH3vV4Pvt9nipRInmc5Pt5PJiT1gAAAAAAgGN6M3oBPbx8+vxn9Bo4ptfv3w41M7u/GcPOaHuOwu4WbuCpbk9B2MVClw79r58/ei2FcO8/fFz091ePQenFzRl8w85oc6JQNQQlF3Vv8A09Vd2LQbUQlFrMrcE39OzNrRhUCUGJRVwbfEPPUVyLwegQDL24wSdNtRAMC8Cl4Tf4pLgUghER+GfrC7Zm+OHSf+8jvnHZtDgGH/42cjew2Q7A8MNlI3cDm1RmejMGHy6b7gZ67wS67wAMP8w3nY/eO4GuATD8sNyWEegWAMMPj9sqAl3eL84Xa/DhOefnAmufCay+AzD8sK7zOVp7J7BqAPywDuhvzTlbLQDe+aGfXmcCqwTA8EN/PSKw+hmA4Yd+1p6vpwPg0A+2teah4FMBcOgH4z0zhw8HwHs/jLPWecAqZwCGH7a3xtw9FABbf6jnkbl8++xFPf3Zo5cvv7tf4/Xru+7X+PXzx+L/Wcm5xd8VO/Vnz7YY/KktQvDo7xcY8jMBYYQRwz/yunMs2gF4+rNHlQaw527gkV2AHQAEmx0AT3/2qNLTv7W+63nkC0E7AA6r2vCfVFrXrAD4dX/Ynzlzu3gHYPvPHlR6yl7Sa31L59MrAAS7GwDbf9ive/O7aAdg+w/1LZlTrwAQTAAg2M0A+PgH9mnuR0F2ABBMACCYAEAwAYBgVwPgABD2bc5BoB0ABBMACCYAEEwAIJgAQDABgGACAMEEAIIJAAQTAAgmABBMACCYAEAwAYBgAgDBBACCCQAEEwAIJgAQTAAgmABAMAGAYAIAwQQAgr0dvQDGePnyu/s1Xr++634NniMAYbYY/Om1hKAurwBBthz+CtflPjuAABUG0G6gJjsACCYAB1fh6X+u2nrSCcCBVR22qutKJAAQTAAOqvpTtvr6UggABBMACCYAEEwAIJgAQDABgGACAMEEAIIJAAQTAAgmABBMACCYAEAwAYBgAgDBBACCCQAEEwAIJgAQTAAgmABAMAGAYAIAwQQAggkABBMACCYAEEwAIJgAQDABgGACAMEEAIIJAAQTAAgmABDs7egFjPLy5Xf3a7x+fdf9GvCMuABsMfjTawkBVUW9Amw5/BWuC/dE7AAqDKDdABVF7QCA/zt8ACo8/c9VWw/ZDh2AqsNWdV3kOXQAgNsOG4DqT9nq6yPDYQMA3CcAEEwAIJgAQDABgGACAMEEAIIJAAQTAAgmABBMACCYAEAwAYBgAgDBBACCCQAEEwAIJgAQTAAgmABAMAGAYAIAwQQAggkABBMACCYAEEwAIJgAQDABgGACAMEEAIIJAAQTAAgmABBMACCYAEAwAYBgAgDBBACCCQAEEwAIJgAQTAAgmABAMAGAYAIAwQQAggkABBMACCYAEEwAIJgAQDABgGACAMEEAIIJAAQ7bABev74bvYSbeq/P/Wff/1yHDQBw36EDUKWyU1uty/1n3/8chw5Aa7X+Ybe2/Xrcf/b933P4AADXvbn2F14+ff5z+uNfP39ss5rOXr78HnbtCuV3/3n3//7Dx//W8P3bX/MetQMY9S+hwn/8rbn/9Pu/JGoHcG6Lp0Hlf/HuP+P+7+0AYgMACbwCAFcJAAQTAAgmABBMACCYAEAwAYBgAgDBrgbg/KOB848JgH249xFQa3YAEE0AIJgAQDABgGA3A+AgEPZpzgFga3YAEE0AINiiAHgNgPqWzOndANx6fwBquze/XgEg2OIAeA2AupbO56wAeA2A/Zkzt14BINjsAPgoCGqb+/HPOTsACLYoAHYBUNMjT//W7AAg2uIA2AVALY8+/VtbYQcgAjDOs/P3UAB8FwD1PDKXq5wB2AXA9taYu4cDMK2NCMB2pvP26K78qR2AVwEY75k5fPoVwK8KwLaeOfWfWv07ABGAftaer1UC4DwA+lvrvf/cajsAEYB+egx/ayu/AjgUhP7WnLPVzwAcCsK61jz0m+r2xH759PnP+Z//+vmj16XgkHpt+891+92AzgTgcVsMf2udfzuwCMByWw1/axv8PAARgPm2HP7WOp4BTE3PBFpzLgAnlx6MW/yq2mY/EejSzdgNwLjhb23DHcA5uwEYO/gnQ34moN0A6SoMf2uDdgAnl3YCrdkNcFzXHnSjvqIt8emuEHB01Qb/pEQATq6FoDUxYH9uvdaOHvyTEouYuhWC1sSAuu6dZVUZ/JNSi5m6F4LWxIDx5hxgVxv8k5KLmpoTgnOiQC9Lf7Wq6uCflF7cJUtjAFurPvTndrPQawSB0fY08FO7XfgtokAvex52AAAAACDQv7L4RJ6TjL6nAAAAAElFTkSuQmCC"
FPS_GAME   = 23.81
REC_STATE  = {"rec": False, "text": "대기 중", "game": None}   # 실시간 녹화 상태(웹 표시용)
for d in (DATA_DIR, UPLOAD_DIR, REC_DIR): os.makedirs(d, exist_ok=True)
# 레거시 이전: 예전엔 프로그램 폴더 안(./data)에 저장 → 같은 폴더에 덮어쓴 경우 자동 이전
try:
    _legacy = os.path.join(HERE, "data")
    if os.path.abspath(_legacy) != os.path.abspath(DATA_DIR) \
       and os.path.isfile(os.path.join(_legacy, "matches.db")) and not os.path.isfile(DB_PATH):
        import shutil as _sh
        for _it in os.listdir(_legacy):
            _s = os.path.join(_legacy, _it); _dn = os.path.join(DATA_DIR, _it)
            if not os.path.exists(_dn):
                _sh.copytree(_s, _dn) if os.path.isdir(_s) else _sh.copy2(_s, _dn)
        print(f"[이전] 예전 자료를 {DATA_DIR} 로 옮겼어요.")
except Exception: pass
FFMPEG = None
SCREP  = None
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
    elif ("녹화 종료" in s) or ("대기 상태" in s) or ("스타크래프트 종료" in s): REC_STATE["recording"] = False
    if "준비 완료. 스타" in s: REC_STATE["ready"] = True
    if s.startswith("인코더:"): REC_STATE["encoder"] = s.split("인코더:", 1)[1].strip()
    try: GUI_Q.put_nowait(line)
    except Exception: pass
    try:
        if _LOGFILE["p"]:
            with open(_LOGFILE["p"], "a", encoding="utf-8", errors="replace") as f: f.write(line + "\n")
    except Exception: pass

# ===================== 1. 설정 (자동 생성/탐지) =====================
def detect_replay_dir():
    up = os.environ.get("USERPROFILE", os.path.expanduser("~"))
    cands = [
        os.path.join(up, "Documents", "StarCraft", "Maps", "Replays", "AutoSave"),
        os.path.join(up, "OneDrive", "Documents", "StarCraft", "Maps", "Replays", "AutoSave"),
        os.path.join(up, "OneDrive", "문서", "StarCraft", "Maps", "Replays", "AutoSave"),
        os.path.join(up, "문서", "StarCraft", "Maps", "Replays", "AutoSave"),
        os.path.join(up, "Documents", "StarCraft", "Maps", "Replays"),
    ]
    # .rep 이 실제로 있는 폴더 우선
    for c in cands:
        if os.path.isdir(c) and glob.glob(os.path.join(c, "**", "*.rep"), recursive=True):
            return c
    for c in cands:
        if os.path.isdir(c):
            return c
    return cands[0]

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
        cfg["replay_autosave_dir"] = os.path.expandvars(cfg.get("replay_autosave_dir", ""))
    else:
        cfg = {
            "mode": "all",
            "starcraft_process": "StarCraft.exe",
            "replay_autosave_dir": detect_replay_dir(),
            "username": "",
            "server": {"url": "http://localhost:8000", "api_key": ""},
            "upload_key": secrets.token_hex(8),
            "r2": {"account_id": "", "bucket": "", "access_key_id": "", "secret_access_key": "", "public_base_url": ""},
            "cloud": {"function_url": "", "upload_key": ""},
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
            "autostart": True, "min_game_sec": 120,
        }
        json.dump(cfg, open(CONFIG_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        log(f"설정 자동 생성됨 → {CONFIG_PATH}")
    # service_key 영구보관: 한 번 넣으면 data 폴더에 저장 → 이후 zip 통째로 덮어써도 유지
    try:
        _sk = ((cfg.get("supabase") or {}).get("service_key") or "").strip()
        _secret = os.path.join(DATA_DIR, "encore_secret.json")
        if _sk:
            json.dump({"service_key": _sk}, open(_secret, "w", encoding="utf-8"))
        elif os.path.isfile(_secret):
            _v = (json.load(open(_secret, encoding="utf-8")) or {}).get("service_key") or ""
            if _v: cfg.setdefault("supabase", {})["service_key"] = _v
    except Exception: pass
    # 리플레이 폴더가 비었거나 없으면 자동 재탐지
    try:
        _rd = cfg.get("replay_autosave_dir") or ""
        if not _rd or not os.path.isdir(_rd):
            _nd = detect_replay_dir()
            if _nd: cfg["replay_autosave_dir"] = _nd
    except Exception: pass
    return cfg

# ===================== 2. ffmpeg / screp 자동 다운로드 =====================
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
    log("    4) START.bat 다시 실행")
    return None

def _dl(url, timeout, tries=3):
    """간단 재시도 다운로드 — 504/일시적 게이트웨이 오류·끊김 대응."""
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            return urllib.request.urlopen(req, timeout=timeout).read()
        except Exception as e:
            last = e
            if i < tries - 1: time.sleep(1.5 * (i + 1))
    raise last

def _extract_screp(blob, name, dst):
    if name.lower().endswith(".zip"):
        z = zipfile.ZipFile(io.BytesIO(blob))
        m = next(n for n in z.namelist() if n.lower().endswith("screp.exe"))
        with z.open(m) as s, open(dst, "wb") as d: shutil.copyfileobj(s, d)
    else:
        import tarfile
        t = tarfile.open(fileobj=io.BytesIO(blob))
        m = next(n for n in t.getnames() if n.lower().endswith("screp.exe"))
        with t.extractfile(m) as s, open(dst, "wb") as d: shutil.copyfileobj(s, d)

# API가 죽었을 때(레이트리밋/504) 폴백할 알려진 버전들
_SCREP_FALLBACK = [("v1.13.2", "screp_v1.13.2_windows_amd64.zip"),
                   ("v1.13.1", "screp_v1.13.1_windows_amd64.zip"),
                   ("v1.12.18", "screp_v1.12.18_windows_amd64.zip")]

def ensure_screp():
    # 1) 빌드 때 번들된 screp — 런타임 다운로드 자체가 없으니 504가 날 일이 없음
    bundled = os.path.join(BUNDLE_DIR, "screp.exe")
    if os.path.isfile(bundled): return bundled
    # 2) exe 옆에 이미 받아둔 것 / PATH
    local = os.path.join(HERE, "screp.exe")
    if os.path.isfile(local): return local
    found = shutil.which("screp")
    if found: return found
    # 3) 다운로드: GitHub API(재시도) → 실패 시 고정 URL 폴백(재시도)
    try:
        try:
            rel = json.loads(_dl("https://api.github.com/repos/icza/screp/releases/latest", 30, tries=3))
            asset = next(a for a in rel.get("assets", [])
                         if "windows" in a["name"].lower() and ("amd64" in a["name"].lower() or "x86_64" in a["name"].lower()))
            _extract_screp(_dl(asset["browser_download_url"], 120, tries=3), asset["name"], local)
        except Exception:
            for tag, fn in _SCREP_FALLBACK:
                try:
                    _extract_screp(_dl(f"https://github.com/icza/screp/releases/download/{tag}/{fn}", 120, tries=2), fn, local)
                    break
                except Exception:
                    continue
        if os.path.isfile(local):
            log("screp 준비 완료 (갤러리에 맵/종족/APM/승패 표시됨).")
            return local
        raise RuntimeError("다운로드 실패(네트워크/GitHub 일시 오류) — 잠시 후 재실행하면 자동 재시도됩니다")
    except Exception as e:
        log(f"(screp 자동 설치 생략 — 영상은 정상, 메타데이터만 비표시: {e})")
        return None

# ===================== 3. 리플레이 파싱 =====================
def clean(s): return re.sub(r"[\x00-\x1f]", "", s).strip() if s else s

def parse_rep(path):
    meta = {"map": None, "length": None, "type": None, "matchup": None,
            "winner": None, "saver": None, "players": []}
    if not SCREP or not os.path.isfile(path): return meta
    try:
        out = _run([SCREP, path], capture_output=True, timeout=60).stdout
        d = json.loads(out)
    except Exception: return meta
    h = d.get("Header", {}) or {}; comp = d.get("Computed", {}) or {}
    pdescs = {p["PlayerID"]: p for p in (comp.get("PlayerDescs") or [])}
    players = []
    for p in (h.get("Players") or []):
        pd = pdescs.get(p.get("ID"), {})
        _lt = (p.get("Race") or {}).get("Letter")
        players.append({"name": p.get("Name"), "race": (p.get("Race") or {}).get("ShortName"),
                        "rl": (chr(_lt) if isinstance(_lt, int) and 65 <= _lt <= 90 else "?"),
                        "team": p.get("Team"), "apm": pd.get("APM"),
                        "color": "#%06x" % ((p.get("Color") or {}).get("RGB", 8421504))})
    frames = h.get("Frames", 0) or 0; secs = frames / FPS_GAME
    t1 = "".join(pl["rl"] for pl in players if pl["team"] == 1)
    t2 = "".join(pl["rl"] for pl in players if pl["team"] == 2)
    meta.update({"map": clean(h.get("Map")), "length": "%d:%02d" % (secs // 60, secs % 60),
                 "type": (h.get("Type") or {}).get("Name"), "winner": comp.get("WinnerTeam"),
                 "saver": next((p.get("Name") for p in (h.get("Players") or [])
                               if p.get("ID") == comp.get("RepSaverPlayerID")), None),
                 "players": players,
                 "matchup": (f"{t1} vs {t2}" if t1 and t2 else None)})
    return meta

def mmss(fr): sx = max(0, fr)/FPS_GAME; return f"{int(sx//60)}:{int(sx%60):02d}"
TOWN_HALLS = {"Command Center", "Nexus", "Hatchery"}
# 스타크래프트 데이터용 — 유닛 표시 보급값(인구). 전사 미반영 누계 추정에 사용.
UNIT_SUPPLY = {
 "Probe":1,"Zealot":2,"Dragoon":2,"High Templar":2,"Dark Templar":2,"Archon":4,"Dark Archon":4,
 "Reaver":4,"Shuttle":2,"Observer":1,"Scout":3,"Corsair":2,"Carrier":6,"Arbiter":4,
 "SCV":1,"Marine":1,"Firebat":1,"Medic":1,"Ghost":1,"Vulture":2,"Siege Tank":2,"Goliath":2,
 "Wraith":2,"Valkyrie":2,"Dropship":2,"Science Vessel":2,"Battlecruiser":6,
 "Drone":1,"Zergling":1,"Hydralisk":1,"Lurker":2,"Mutalisk":2,"Scourge":1,"Queen":2,
 "Guardian":2,"Devourer":2,"Ultralisk":4,"Defiler":2,"Infested Terran":1,"Overlord":0,
}
# 기존 유닛에서 전환되는 모프(이미 카운트됨 → 보급 중복 방지)
MORPH_FROM_UNIT = {"Lurker","Guardian","Devourer","Archon","Dark Archon"}
# === 자원 비용 테이블 (BW 표준값) — 명령당 (미네랄, 가스). 저글링/스커지=쌍 비용, 변태유닛=추가비용만 ===
UNIT_MG = {
 "Probe":(50,0),"Zealot":(100,0),"Dragoon":(125,50),"High Templar":(50,150),"Dark Templar":(125,100),
 "Archon":(0,0),"Dark Archon":(0,0),"Reaver":(200,100),"Shuttle":(200,0),"Observer":(25,75),
 "Scout":(275,125),"Corsair":(150,100),"Carrier":(350,250),"Arbiter":(100,350),"Interceptor":(25,0),"Scarab":(15,0),
 "SCV":(50,0),"Marine":(50,0),"Firebat":(50,25),"Medic":(50,25),"Ghost":(25,75),
 "Vulture":(75,0),"Siege Tank":(150,100),"Goliath":(100,50),"Wraith":(150,100),"Valkyrie":(250,125),
 "Dropship":(100,100),"Science Vessel":(100,225),"Battlecruiser":(400,300),"Nuclear Missile":(200,200),
 "Drone":(50,0),"Zergling":(50,0),"Hydralisk":(75,25),"Mutalisk":(100,100),"Scourge":(25,75),
 "Queen":(100,100),"Ultralisk":(200,200),"Defiler":(50,150),"Infested Terran":(100,50),"Overlord":(100,0),
 "Lurker":(50,100),"Guardian":(50,100),"Devourer":(150,50),
}
MORPH_SUP_DELTA = {"Lurker":1,"Guardian":0,"Devourer":0,"Archon":0,"Dark Archon":0}
BUILD_MG = {
 "Nexus":(400,0),"Pylon":(100,0),"Gateway":(150,0),"Assimilator":(100,0),"Forge":(150,0),
 "Cybernetics Core":(200,0),"Photon Cannon":(150,0),"Shield Battery":(100,0),"Citadel of Adun":(150,100),
 "Templar Archives":(150,200),"Robotics Facility":(200,200),"Observatory":(50,100),"Robotics Support Bay":(150,100),
 "Stargate":(150,150),"Fleet Beacon":(300,200),"Arbiter Tribunal":(200,150),
 "Command Center":(400,0),"Supply Depot":(100,0),"Refinery":(100,0),"Barracks":(150,0),"Engineering Bay":(125,0),
 "Bunker":(100,0),"Academy":(150,0),"Missile Turret":(75,0),"Factory":(200,100),"Starport":(150,100),
 "Armory":(100,50),"Science Facility":(100,150),"Comsat Station":(50,50),"Nuclear Silo":(100,100),
 "Machine Shop":(50,50),"Control Tower":(50,50),"Covert Ops":(50,50),"Physics Lab":(50,50),
 "Hatchery":(300,0),"Creep Colony":(75,0),"Spawning Pool":(200,0),"Evolution Chamber":(75,0),
 "Hydralisk Den":(100,50),"Extractor":(50,0),"Spire":(200,150),"Queens Nest":(150,100),
 "Nydus Canal":(150,0),"Defiler Mound":(100,100),"Ultralisk Cavern":(150,200),
 "Lair":(150,100),"Hive":(200,150),"Sunken Colony":(50,0),"Spore Colony":(50,0),"Greater Spire":(100,150),
}
UPGRADE_MG = {
 "Protoss Ground Weapons":(100,100),"Protoss Ground Armor":(100,100),"Protoss Plasma Shields":(200,200),
 "Protoss Air Weapons":(100,100),"Protoss Air Armor":(100,100),"Singularity Charge (Dragoon Range)":(150,150),
 "Leg Enhancement (Zealot Speed)":(150,150),"Gravitic Drive (Shuttle Speed)":(200,200),"Scarab Damage":(200,200),
 "Reaver Capacity":(200,200),"Gravitic Boosters (Observer Speed)":(150,150),"Sensor Array (Observer Sight)":(150,150),
 "Khaydarin Amulet (Templar Energy)":(150,150),"Apial Sensors (Scout Sight)":(100,100),"Carrier Capacity":(100,100),
 "Gravitic Thrusters (Scout Speed)":(200,200),"Khaydarin Core (Arbiter Energy)":(150,150),
 "Terran Infantry Weapons":(100,100),"Terran Infantry Armor":(100,100),"Terran Vehicle Weapons":(100,100),
 "Terran Vehicle Plating":(100,100),"Terran Ship Weapons":(100,100),"Terran Ship Plating":(100,100),
 "U-238 Shells (Marine Range)":(150,150),"Caduceus Reactor (Medic Energy)":(150,150),"Ion Thrusters (Vulture Speed)":(100,100),
 "Charon Boosters (Goliath Range)":(100,100),"Apollo Reactor (Wraith Energy)":(200,200),"Yamato Gun":(100,100),
 "Colossus Reactor (Battlecruiser Energy)":(200,200),"Titan Reactor (Science Vessel Energy)":(150,150),
 "Moebius Reactor (Ghost Energy)":(150,150),"Ocular Implants (Ghost Sight)":(100,100),
 "Zerg Carapace":(150,150),"Zerg Melee Attacks":(100,100),"Zerg Missile Attacks":(100,100),
 "Zerg Flyer Carapace":(150,150),"Zerg Flyer Attacks":(100,100),"Muscular Augments (Hydralisk Speed)":(150,150),
 "Grooved Spines (Hydralisk Range)":(150,150),"Pneumatized Carapace (Overlord Speed)":(150,150),
 "Ventral Sacs (Overlord Transport)":(200,200),"Metabolic Boost (Zergling Speed)":(100,100),
 "Adrenal Glands (Zergling Attack)":(200,200),"Anabolic Synthesis (Ultralisk Speed)":(150,150),
 "Chitinous Plating (Ultralisk Armor)":(150,150),"Antennae (Overlord Sight)":(150,150),
}
TECH_MG = {
 "Psionic Storm":(200,200),"Hallucination":(150,150),"Recall":(150,150),"Stasis Field":(150,150),
 "Disruption Web":(200,200),"Mind Control":(200,200),"Maelstrom":(100,100),"Stim Packs":(100,100),
 "Lockdown":(200,200),"EMP Shockwave":(200,200),"Irradiate":(200,200),"Yamato Gun":(100,100),
 "Cloaking Field":(150,150),"Personnel Cloaking":(100,100),"Restoration":(100,100),"Optical Flare":(100,100),
 "Spider Mines":(100,100),"Tank Siege Mode":(150,150),"Lurker Aspect":(200,200),"Burrowing":(100,100),
 "Plague":(150,150),"Consume":(100,100),"Ensnare":(100,100),"Spawn Broodlings":(100,100),
}
PROD_BUILDINGS = {"Gateway","Robotics Facility","Stargate","Barracks","Factory","Starport","Hatchery"}
# 서플(보급) 건물 — 추가로 지을수록 인구 한도가 뚫림. Z는 오버로드(유닛)로 따로 셈.
SUPPLY_BLD = {"Pylon","Supply Depot"}
# 종족 지상 공격/방어 업그레이드 이름(screp Upgrade.Name). 같은 업글을 여러 번 = 그게 레벨(몇업).
GND_ATK = {"P":["Protoss Ground Weapons"], "T":["Terran Infantry Weapons","Terran Vehicle Weapons"], "Z":["Zerg Melee Attacks","Zerg Missile Attacks"]}
GND_ARM = {"P":["Protoss Ground Armor"],   "T":["Terran Infantry Armor","Terran Vehicle Plating"],   "Z":["Zerg Carapace"]}
# 종족별 주력 생산건물 — 물량의 핵심 (개수 = 한방 후 remax 속도)
MAIN_PROD = {"P":("Gateway","게이트웨이"), "T":("Barracks","배럭"), "Z":("Hatchery","해처리")}
SUPPLY_KO = {"P":("Pylon","파일런"), "T":("Supply Depot","서플라이 디팟"), "Z":("Overlord","오버로드")}
WORKER_NAME = {"P":"Probe","T":"SCV","Z":"Drone"}
WORKER_KO   = {"P":"프로브","T":"SCV","Z":"드론"}
# 공방(공격/방어) 업그레이드: screp명 → 한글 라벨 (선수가 실제 연구한 것만 표시)
COMBAT_UP = {
 "P":[("Protoss Ground Weapons","지상 공격"),("Protoss Ground Armor","지상 방어"),("Protoss Plasma Shields","실드"),("Protoss Air Weapons","공중 공격"),("Protoss Air Armor","공중 방어")],
 "T":[("Terran Infantry Weapons","보병 공격"),("Terran Infantry Armor","보병 방어"),("Terran Vehicle Weapons","기계 공격"),("Terran Vehicle Plating","기계 방어"),("Terran Ship Weapons","함선 공격"),("Terran Ship Plating","함선 방어")],
 "Z":[("Zerg Melee Attacks","근접 공격"),("Zerg Missile Attacks","원거리 공격"),("Zerg Carapace","지상 방어"),("Zerg Flyer Attacks","공중 공격"),("Zerg Flyer Carapace","공중 방어")],
}
def _up_level_times(frames, gap=2400, cap=3):
    """업글 커맨드 프레임들 → 레벨별 시작 시각. 연구시간보다 가까운 재클릭(연타)은 한 레벨로 묶음(_upgrade_level과 동일 기준)."""
    if not frames: return []
    fs = sorted(frames); out = [mmss(fs[0])]; last = fs[0]
    for fr in fs[1:]:
        if fr - last >= gap:
            out.append(mmss(fr)); last = fr
            if len(out) >= cap: break
    return out[:cap]
def _worker_ms(cmd_fr, th_fr, rl, total_fr):
    """일꾼 N기 도달 시각 — 생산 명령(무한맵에선 돈이 많아 미리 연타·예약됨)을 실제 생산 능력으로 상한 처리.
    베이스(초기 1곳 + 확장) 1곳당 ~빌드타임마다 1기. 게임 종료까지 물리적으로 도달 못한 마일스톤은 생략."""
    start = 4
    bt = 342.0 if rl == "Z" else 300.0   # 일꾼 빌드 프레임 (P/T ~12.6s, Z 라바 제한 ~14.4s @ Fastest)
    cf = sorted(cmd_fr); th = sorted(th_fr)
    def earliest(n):
        need = n - start
        if need <= 0: return 0.0
        cap = 0.0; t = 0.0; bases = 1
        for ev in th + [float(total_fr or 0) + 1e9]:
            span = ev - t; rate = bases / bt
            if span > 0 and cap + rate * span >= need: return t + (need - cap) / rate
            cap += max(0.0, rate * span); t = ev; bases += 1
        return None
    out = {}
    for n in (10, 20, 30, 40, 50):
        if len(cf) < n: continue
        e = earliest(n)
        if e is None: continue
        fr = max(cf[n - 1], e)
        if total_fr and fr > total_fr: continue
        out[str(n)] = mmss(fr)
    return out
def _upgrade_level(frames, gap=2400, cap=3):
    """업글 커맨드 프레임들 → 실제 레벨 추정. 연구시간(~gap프레임)보다 가까운 재클릭(연타)은 한 레벨로 묶음."""
    if not frames: return 0
    fs = sorted(frames); lv = 1; last = fs[0]
    for fr in fs[1:]:
        if fr - last >= gap: lv += 1; last = fr
    return min(lv, cap)
def _cum_at_bins(events, total_sec, step):
    """(frame,value) 이벤트 → 시간 구간마다 누적값 리스트."""
    if not events or total_sec <= 0: return []
    ev = sorted((f/FPS_GAME, v) for f, v in events)
    out = []; i = 0; c = 0.0; b = 1; nb = int(total_sec/step) + 1
    while b <= nb:
        bt = b*step
        while i < len(ev) and ev[i][0] <= bt: c += ev[i][1]; i += 1
        out.append(c); b += 1
    return out
def extract_analysis(rep_path):
    out = _run([SCREP, "-cmds", rep_path], capture_output=True, timeout=120).stdout
    d = json.loads(out); h = d["Header"]; comp = d.get("Computed", {}) or {}
    pdescs = {p["PlayerID"]: p for p in (comp.get("PlayerDescs") or [])}
    frames = h.get("Frames", 0) or 0; nbins = max(1, int(frames/FPS_GAME//60) + 1)
    CF_STEP = 4.0                                       # 정밀 교전 빈(초) — 클립 시각 정확도용
    cf_n = max(1, int((frames/FPS_GAME)//CF_STEP) + 1)
    players = {}; order = []; seen_up = defaultdict(set); leaves = []
    for p in (h.get("Players") or []):
        pid = p.get("ID"); pd = pdescs.get(pid, {})
        _lt = (p.get("Race") or {}).get("Letter")
        _rl = chr(_lt) if isinstance(_lt, int) and 65 <= _lt <= 90 else None
        players[pid] = {"id": pid, "name": p.get("Name"), "race": (p.get("Race") or {}).get("ShortName"), "rl": _rl,
            "team": p.get("Team"), "color": "#%06x" % ((p.get("Color") or {}).get("RGB", 8421504)),
            "apm": pd.get("APM"), "eapm": pd.get("EAPM"), "build": [], "units": Counter(), "up_fr": defaultdict(list),
            "unit_first": {}, "townhalls": [], "apm_series": [0]*nbins, "supply_events": [], "cost_events": [],
            "cmd_mix": Counter(), "hotkey_n": 0, "groups": set(), "drops": 0, "pings": 0,
            "scout_bases": set(), "scout_first_fr": None, "atk_first_fr": None, "drop_first_fr": None,
            "aggr_series": [0]*nbins, "train_frames": [], "combat_fine": [0]*cf_n,
            "start": ((pd.get("StartLocation") or {}).get("X"), (pd.get("StartLocation") or {}).get("Y"))}
        order.append(pid)
    NEAR2 = 800*800   # 적 본진 반경^2 (정찰/공격 판정)
    enemy_starts = {}
    for _pid in players:
        _tm = players[_pid]["team"]
        enemy_starts[_pid] = [players[o]["start"] for o in players
                              if players[o]["team"] != _tm and players[o]["start"][0] is not None]
    for c in d.get("Commands", {}).get("Cmds", []):
        pid = c.get("PlayerID"); pl = players.get(pid)
        if pl is None: continue
        f = c.get("Frame", 0); tn = (c.get("Type") or {}).get("Name")
        b = min(nbins-1, int(f/FPS_GAME//60)); pl["apm_series"][b] += 1
        pl["cmd_mix"][tn] += 1
        if tn in ("Right Click", "Targeted Order"):
            pl["combat_fine"][min(cf_n-1, int(f/FPS_GAME//CF_STEP))] += 1
            _ps = c.get("Pos") or {}; _x = _ps.get("X"); _y = _ps.get("Y")
            if _x is not None:
                for (_ex, _ey) in enemy_starts.get(pid, []):
                    if _ex is not None and (_x-_ex)**2 + (_y-_ey)**2 <= NEAR2:
                        _mf = f/FPS_GAME/60
                        if _mf < 5:
                            pl["scout_bases"].add((_ex, _ey))
                            if pl["scout_first_fr"] is None: pl["scout_first_fr"] = f
                        if _mf >= 4:
                            pl["aggr_series"][b] += 1
                            if pl["atk_first_fr"] is None: pl["atk_first_fr"] = f
                        break
        elif tn == "Hotkey":
            pl["hotkey_n"] += 1; _g = c.get("Group")
            if (c.get("HotkeyType") or {}).get("Name") == "Assign" and _g is not None: pl["groups"].add(_g)
        elif tn == "Unload":
            pl["drops"] += 1; pl.setdefault("drop_frames", []).append(f)
            if pl["drop_first_fr"] is None: pl["drop_first_fr"] = f
        elif tn == "Minimap Ping": pl["pings"] += 1
        uname = (c.get("Unit") or {}).get("Name")
        if tn == "Build":
            _ps = c.get("Pos") or {}; _bx = _ps.get("X"); _by = _ps.get("Y")
            _bk = (uname, _bx, _by) if _bx is not None else (uname, "nopos", f)  # 같은 건물+같은 좌표=연타(1개로), 좌표 없으면 합치지 않음
            _bs = pl.setdefault("_bseen", set())
            if _bk not in _bs:
                _bs.add(_bk)
                pl["build"].append({"t": mmss(f), "name": uname, "cat": "building"})
                pl["cost_events"].append((f,)+BUILD_MG.get(uname,(0,0)))
                if uname in TOWN_HALLS: pl["townhalls"].append({"t": mmss(f), "name": uname})
        elif tn == "Building Morph":
            pl["build"].append({"t": mmss(f), "name": uname, "cat": "morph"})
            pl["cost_events"].append((f,)+BUILD_MG.get(uname,(0,0)))
        elif tn == "Upgrade":
            up = (c.get("Upgrade") or {}).get("Name") or uname or "Upgrade"
            pl["up_fr"][up].append(f)
            if up not in seen_up[pid]: seen_up[pid].add(up); pl["build"].append({"t": mmss(f), "name": up, "cat": "upgrade"}); pl["cost_events"].append((f,)+UPGRADE_MG.get(up,(0,0)))
        elif tn == "Leave Game":
            leaves.append((f, pid))
        elif tn == "Tech":
            tech = (c.get("Tech") or {}).get("Name") or uname or "Tech"
            if tech not in seen_up[pid]: seen_up[pid].add(tech); pl["build"].append({"t": mmss(f), "name": tech, "cat": "tech"}); pl["cost_events"].append((f,)+TECH_MG.get(tech,(0,0)))
        elif tn in ("Train", "Train Fighter", "Unit Morph"):
            if uname:
                pl["units"][uname] += 1
                if uname in ("Probe","SCV","Drone"): pl.setdefault("worker_fr", []).append(f)
                pl["cost_events"].append((f,)+UNIT_MG.get(uname,(0,0)))
                if uname not in pl["unit_first"]: pl["unit_first"][uname] = mmss(f)
                if tn == "Train" or (tn == "Unit Morph" and uname not in MORPH_FROM_UNIT):
                    pl["supply_events"].append((f, UNIT_SUPPLY.get(uname, 1)))
                    pl["train_frames"].append(f)
    res = []
    for pid in order:
        pl = players[pid]; us = sorted(pl["units"].items(), key=lambda kv: -kv[1])
        ev = sorted(pl["supply_events"]); cum = 0; t200 = None
        for fr, sup in ev:
            cum += sup
            if t200 is None and cum >= 200: t200 = mmss(fr)
        prodn = sum(1 for b in pl["build"] if b["cat"] in ("building", "morph") and b["name"] in PROD_BUILDINGS)
        rl = pl.get("rl") if pl.get("rl") in ("P","T","Z") else _coach_race(pl["race"], list(pl["units"]))
        atk_lv = max([_upgrade_level(pl["up_fr"].get(n, [])) for n in GND_ATK.get(rl, [])] or [0])
        arm_lv = max([_upgrade_level(pl["up_fr"].get(n, [])) for n in GND_ARM.get(rl, [])] or [0])
        _ut = [{"ko": ko, "lv": _up_level_times(pl["up_fr"].get(nm, []))} for (nm, ko) in COMBAT_UP.get(rl, []) if pl["up_fr"].get(nm)]
        _wf = sorted(pl.get("worker_fr", []))
        _th_fr = sorted(round(_mmss_to_sec(t["t"]) * FPS_GAME) for t in pl["townhalls"])
        _wms = _worker_ms(_wf, _th_fr, rl, frames)
        _tot_sec = frames/FPS_GAME if frames else 0
        _step = max(5.0, (_tot_sec or 60)/80.0)
        _supc = _cum_at_bins([(fr,sp) for fr,sp in pl["supply_events"]], _tot_sec, _step)
        _minc = _cum_at_bins([(fr,m) for fr,m,g in pl["cost_events"]], _tot_sec, _step)
        _gasc = _cum_at_bins([(fr,g) for fr,m,g in pl["cost_events"]], _tot_sec, _step)
        resource_series = [{"t":round((i+1)*_step),"sup":round(_supc[i]),"min":round(_minc[i]),"gas":round(_gasc[i])} for i in range(len(_supc))]
        sup_name, sup_ko = SUPPLY_KO.get(rl, ("Pylon", "서플"))
        sup_bld = (pl["units"].get("Overlord", 0) if rl == "Z" else sum(1 for b in pl["build"] if b["name"] == sup_name))
        sup_cap = sup_bld * 8 + 9   # 대략적 인구 한도 (본진 보급 + 서플건물/오버로드 ×8)
        mp_name, mp_ko = MAIN_PROD.get(rl, ("Gateway", "생산건물"))
        mp_n = sum(1 for b in pl["build"] if b["name"] == mp_name)
        _drf = sorted(pl.get("drop_frames", [])); _dsec = []
        for _fr in _drf:
            _s = int(max(0, _fr)/FPS_GAME)
            if not _dsec or _s - _dsec[-1] >= 12: _dsec.append(_s)   # ~12초 내 연속 언로드 = 한 번의 드랍
        res.append({"id": pl["id"], "name": pl["name"], "race": pl["race"], "rl": rl, "team": pl["team"],
            "color": pl["color"], "apm": pl["apm"], "eapm": pl["eapm"], "build": pl["build"],
            "units": [{"name": k, "n": v, "first": pl["unit_first"].get(k)} for k, v in us],
            "townhalls": pl["townhalls"], "apm_series": pl["apm_series"], "aggr_series": pl["aggr_series"],
            "scout_first": (mmss(pl["scout_first_fr"]) if pl["scout_first_fr"] is not None else None),
            "scouted": len(pl["scout_bases"]),
            "atk_first": (mmss(pl["atk_first_fr"]) if pl["atk_first_fr"] is not None else None),
            "hotkey": pl["hotkey_n"], "groups": len(pl["groups"]), "drops": pl["drops"], "pings": pl["pings"],
            "drop_first": (mmss(pl["drop_first_fr"]) if pl["drop_first_fr"] is not None else None), "drop_secs": _dsec,
            "prod_max_gap": (round(max([(tf[i]-tf[i-1])/FPS_GAME for i in range(1,len(tf))] or [0])) if (tf:=sorted(pl["train_frames"])) else 0),
            "prod_active": (round(100*len(set(int(x/FPS_GAME//60) for x in tf))/max(1,(max(set(int(x/FPS_GAME//60) for x in tf))-min(set(int(x/FPS_GAME//60) for x in tf))+1))) if tf else 0),
            "cmd_mix": dict(pl["cmd_mix"]),
            "max_supply": min(cum, 200), "total_supply": cum, "supply200": t200, "prod": prodn, "resource_series": resource_series,
            "up_timed": _ut, "worker_ms": _wms, "worker_ko": WORKER_KO.get(rl, "일꾼"),
            "atk_lv": atk_lv, "arm_lv": arm_lv, "supply_bld": sup_bld, "supply_cap": sup_cap, "supply_ko": sup_ko,
            "main_prod_n": mp_n, "main_prod_ko": mp_ko,
            "summary": {"buildings": sum(1 for b in pl["build"] if b["cat"] in ("building", "morph")),
                        "units": sum(pl["units"].values()),
                        "upgrades": sum(1 for b in pl["build"] if b["cat"] in ("upgrade", "tech")),
                        "townhalls": len(pl["townhalls"]), "prod": prodn,
                        "atk_lv": atk_lv, "arm_lv": arm_lv, "supply_bld": sup_bld, "supply_cap": sup_cap, "supply_ko": sup_ko,
                        "main_prod_n": mp_n, "main_prod_ko": mp_ko,
                        "max_supply": min(cum, 200), "supply200": t200}})
    secs = frames / FPS_GAME
    meta = {"map": clean(h.get("Map")), "length": f"{int(secs//60)}:{int(secs%60):02d}",
            "winner": comp.get("WinnerTeam"),
            "saver": next((p.get("Name") for p in (h.get("Players") or []) if p.get("ID") == comp.get("RepSaverPlayerID")), None)}
    leave_list = sorted([{"sec": int(max(0, fr)/FPS_GAME), "t": mmss(fr), "name": (players.get(pid) or {}).get("name")}
                         for fr, pid in leaves], key=lambda x: x["sec"])
    team_fine = {}
    for pid in order:
        _t = players[pid]["team"]; _cf = players[pid]["combat_fine"]
        _tf = team_fine.setdefault(_t, [0]*cf_n)
        for _k in range(cf_n): _tf[_k] += _cf[_k]
    combat_fine = {"step": CF_STEP, "n": cf_n, "teams": {str(_t): _v for _t, _v in team_fine.items()}}
    return {"meta": meta, "players": res, "leaves": leave_list, "combat_fine": combat_fine}

# 임팩트 유닛(테크 마일스톤용) → 한글
TECH_UNITS = {
 "Lurker":"러커","Mutalisk":"뮤탈","Guardian":"가디언","Devourer":"디바우러","Defiler":"디파일러","Ultralisk":"울트라","Queen":"퀸","Scourge":"스컬지",
 "Reaver":"리버","Dark Templar":"다크템플러","High Templar":"하이템플러","Carrier":"캐리어","Arbiter":"아비터","Archon":"아콘","Corsair":"커세어","Scout":"스카웃",
 "Siege Tank":"시즈탱크","Tank":"탱크","Battlecruiser":"배틀크루저","Wraith":"레이스","Science Vessel":"사이언스베슬","Valkyrie":"발키리","Ghost":"고스트","Goliath":"골리앗","Dropship":"드랍십",
}
def _mmss_to_sec(t):
    try: m, s = str(t).split(":"); return int(m)*60 + int(s)
    except Exception: return 0
def compute_highlights(a):
    """리플레이 명령 기반 하이라이트. 교전은 분 단위로 후보를 고른 뒤
    정밀 교전 빈(combat_fine)으로 양 팀이 동시에 가장 활발한 '실제 클래시 초'를 짚는다."""
    players = a.get("players") or []
    out = []
    def _ts(s):
        s = int(max(0, s)); return f"{s//60}:{s%60:02d}"

    # --- 정밀 교전 빈(팀별) ---
    cf = a.get("combat_fine") or {}
    cf_step = float(cf.get("step") or 4.0)
    cf_teams = [v for v in (cf.get("teams") or {}).values() if v]
    cf_n = max((len(v) for v in cf_teams), default=0)

    # --- 교전: 양 팀이 동시에 폭증하는 '상호 교전' 피크를 정밀 빈에서 직접 탐지 ---
    # (한 팀만 활발한 드랍/견제, 양 팀 다 한가한 베이스라인은 자동 배제)
    if len(cf_teams) >= 2 and cf_n >= 3:
        W = 1                                          # 평활 반경 ±1빈(≈±4초)
        def _sm(s, k): return sum((s[j] if 0 <= j < len(s) else 0) for j in range(k-W, k+W+1))
        g = [0]*cf_n; tot = [0]*cf_n
        for k in range(cf_n):
            vals = sorted((_sm(s, k) for s in cf_teams), reverse=True)
            a1 = vals[0]; a2 = vals[1] if len(vals) > 1 else 0
            g[k] = a2; tot[k] = a1 + a2                # a2 = 둘째로 활발한 팀 = 상호 교전 강도
        gmax = max(g) if g else 0
        if gmax > 0:
            posv = sorted(x for x in g if x > 0)
            base = posv[len(posv)//2] if posv else 0   # 양 팀 동시 활동의 평상 수준
            thr = max(0.3*gmax, 2.5*base, 6)           # 상대(최대 대비)·평상 대비·절대 바닥 동시 충족
            peaks = []
            for k in range(cf_n):
                if g[k] >= thr and g[k] >= (g[k-1] if k > 0 else 0) and g[k] >= (g[k+1] if k+1 < cf_n else 0):
                    peaks.append((g[k]*tot[k], k))     # 교전 규모(상호강도×총량)로 정렬
            peaks.sort(reverse=True)
            keep = []
            for sc, k in peaks:
                sec = int(k*cf_step + cf_step/2)
                if all(abs(sec - s2) >= 40 for _, s2 in keep): keep.append((sc, sec))
                if len(keep) >= 3: break
            kmax = keep[0][0] if keep else 0
            for sc, sec in sorted(keep, key=lambda x: x[1]):
                out.append({"sec": sec, "t": _ts(sec),
                            "label": ("최대 교전" if sc == kmax else "주요 교전"), "kind": "battle"})

    # 게임체인저 테크 — 임팩트 유닛 첫 등장 (프레임 기반, 이미 정밀)
    firsts = {}
    for p in players:
        for u in (p.get("units") or []):
            nm = u.get("name"); ft = u.get("first")
            if nm in TECH_UNITS and ft:
                sec = _mmss_to_sec(ft)
                if nm not in firsts or sec < firsts[nm][0]: firsts[nm] = (sec, ft, p.get("name"))
    for nm, (sec, ft, who) in sorted(firsts.items(), key=lambda kv: kv[1][0])[:4]:
        out.append({"sec": sec, "t": ft, "label": f"첫 {TECH_UNITS[nm]}", "who": who, "kind": "tech"})
    # 첫 확장
    exp = None
    for p in players:
        ths = p.get("townhalls") or []
        if len(ths) >= 2:
            sec = _mmss_to_sec(ths[1].get("t"))
            if exp is None or sec < exp[0]: exp = (sec, ths[1].get("t"), p.get("name"))
    if exp: out.append({"sec": exp[0], "t": exp[1], "label": "첫 확장", "who": exp[2], "kind": "expand"})
    # 드랍 견제 (정밀 — 선수별 클러스터된 드랍, 시간순 최대 2개)
    drop_ev = []
    for p in players:
        for s in (p.get("drop_secs") or []):
            if s >= 180: drop_ev.append((s, p.get("name")))
    if not drop_ev:                                   # 폴백: 예전 단일 drop_first 데이터
        for p in players:
            df = p.get("drop_first")
            if df:
                s = _mmss_to_sec(df)
                if s >= 180: drop_ev.append((s, p.get("name")))
    drop_ev.sort()
    picked_d = []
    for s, who in drop_ev:
        if all(abs(s - ps) >= 45 for ps, _ in picked_d): picked_d.append((s, who))
        if len(picked_d) >= 2: break
    for s, who in picked_d:
        out.append({"sec": s, "t": _ts(s), "label": "드랍 견제", "who": who, "kind": "drop"})
    # GG / 퇴장 — 연쇄 퇴장(팀게임 일괄 GG)은 간격 기준으로 묶어 한 이벤트당 하나만
    leaves = a.get("leaves") or []
    clusters = []
    for L in sorted(leaves, key=lambda x: x.get("sec", 0)):
        s = L.get("sec", 0)
        if clusters and (s - clusters[-1][-1].get("sec", 0)) <= 8: clusters[-1].append(L)
        else: clusters.append([L])
    for ci, cl in enumerate(clusters):
        rep = cl[0]; nm = rep.get("name") or "선수"        # 대표 = 첫 퇴장(=GG 콜 시점)
        if ci == len(clusters) - 1: lbl = "GG — 경기 종료"
        else: lbl = (f"{nm} 등 퇴장" if len(cl) > 1 else f"{nm} GG·퇴장")
        out.append({"sec": rep.get("sec", 0), "t": rep.get("t", ""), "label": lbl, "who": nm, "kind": "gg"})
    out.sort(key=lambda hh: hh["sec"])
    return out


# ===================== 4. 인게스트 (영상+리플레이 등록) =====================
def db():
    c = sqlite3.connect(DB_PATH, timeout=15); c.row_factory = sqlite3.Row; return c
def init_db():
    c = db()
    c.execute("""CREATE TABLE IF NOT EXISTS matches(
        id TEXT PRIMARY KEY, uploader TEXT, uploaded TEXT, video TEXT, replay TEXT,
        thumb TEXT, video_size INTEGER, map TEXT, matchup TEXT, length TEXT, length_sec INTEGER,
        type TEXT, winner INTEGER, saver TEXT, np INTEGER, players TEXT, won INTEGER, analysis TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS comments(
        id INTEGER PRIMARY KEY AUTOINCREMENT, match_id TEXT, author TEXT, body TEXT, created TEXT)""")
    for col in ("likes", "views"):
        try: c.execute(f"ALTER TABLE matches ADD COLUMN {col} INTEGER DEFAULT 0")
        except Exception: pass
    c.commit(); c.close()
def _row(r):
    d = dict(r)
    try: d["players"] = json.loads(d.get("players") or "[]")
    except Exception: d["players"] = []
    return d
def get_matches(limit=24, offset=0):
    if sb_enabled(): return sb_get_matches(limit, offset)
    c = db(); rows = c.execute("SELECT * FROM matches ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall(); c.close()
    return [_row(r) for r in rows]
def get_match(mid):
    if sb_enabled(): return sb_get_match(mid)
    c = db(); r = c.execute("SELECT * FROM matches WHERE id=?", (mid,)).fetchone(); c.close()
    return _row(r) if r else None
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
    if sb_enabled(): return _sb_count_cached()
    c = db(); n = c.execute("SELECT COUNT(*) FROM matches").fetchone()[0]; c.close(); return n
def stats_global():
    if sb_enabled(): return sb_stats()
    c = db(); r = c.execute("SELECT COUNT(*), COALESCE(SUM(length_sec),0), COALESCE(SUM(won),0), "
                            "SUM(CASE WHEN won IS NOT NULL THEN 1 ELSE 0 END) FROM matches").fetchone(); c.close()
    n, tsec, w, rated = r[0] or 0, r[1] or 0, r[2] or 0, r[3] or 0
    return n, tsec, (f"{round(100*w/rated)}%" if rated else "—")
def set_analysis(mid, js):
    if sb_enabled(): return sb_set_analysis(mid, js)
    c = db(); c.execute("UPDATE matches SET analysis=? WHERE id=?", (js, mid)); c.commit(); c.close()
# ===================== 코치 리포트 (규칙 기반, API 불필요) =====================

def _len_sec(l):
    try: m, s = l.split(":"); return int(m)*60+int(s)
    except Exception: return 0

RACE_KO = {"ran": "테란", "zerg": "저그", "toss": "프로토스"}

def add_comment(mid, author, body):
    if sb_enabled(): return sb_add_comment(mid, author, body)
    ts = datetime.datetime.now().isoformat(timespec="seconds")
    c = db(); cur = c.execute("INSERT INTO comments(match_id,author,body,created) VALUES(?,?,?,?)",
                              (mid, author, body, ts)); c.commit()
    cid = cur.lastrowid; c.close()
    return {"id": cid, "author": author, "body": body, "created": ts}
def get_comments(mid):
    if sb_enabled(): return sb_get_comments(mid)
    c = db(); rows = c.execute("SELECT id,author,body,created FROM comments WHERE match_id=? ORDER BY id ASC",
                               (mid,)).fetchall(); c.close()
    return [dict(r) for r in rows]
def comment_counts(ids):
    if sb_enabled(): return sb_comment_counts(ids)
    if not ids: return {}
    c = db(); q = ",".join("?" * len(ids))
    out = dict(c.execute(f"SELECT match_id,COUNT(*) FROM comments WHERE match_id IN ({q}) GROUP BY match_id",
                         ids).fetchall()); c.close()
    return out
def bump_like(mid, delta):
    if sb_enabled(): return sb_like(mid, delta)
    c = db(); c.execute("UPDATE matches SET likes=MAX(0,COALESCE(likes,0)+?) WHERE id=?", (delta, mid)); c.commit()
    n = c.execute("SELECT COALESCE(likes,0) FROM matches WHERE id=?", (mid,)).fetchone(); c.close()
    return n[0] if n else 0
def bump_view(mid):
    if sb_enabled(): return sb_view(mid)
    c = db(); c.execute("UPDATE matches SET views=COALESCE(views,0)+1 WHERE id=?", (mid,)); c.commit(); c.close()

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
def sb_enabled():
    s = sb_cfg(); return bool(s.get("url") and (s.get("service_key") or s.get("anon_key")))
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
    k = _sb_key(write); h = {"apikey": k, "Authorization": "Bearer " + (k or "")}
    if body_json: h["Content-Type"] = "application/json"
    return h
def _sb_bucket(): return sb_cfg().get("bucket") or "media"
def sb_upload(local, path, ctype):
    """Supabase Storage 업로드 → 공개 URL (버킷이 public 이어야 함)."""
    import requests
    base = _sb_base(); bk = _sb_bucket(); k = _sb_key(write=True)
    with open(local, "rb") as f:
        r = requests.post("%s/storage/v1/object/%s/%s" % (base, bk, path), data=f,
                          headers={"apikey": k, "Authorization": "Bearer " + k,
                                   "Content-Type": ctype, "x-upsert": "true"}, timeout=(10, 3600))
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
def _sb_get(path):
    import requests
    r = requests.get(_sb_base() + "/rest/v1/" + path, headers=_sb_h(), timeout=30)
    r.raise_for_status(); return r
def _sb_norm(d):
    if isinstance(d.get("analysis"), (dict, list)): d["analysis"] = json.dumps(d["analysis"], ensure_ascii=False)
    if not isinstance(d.get("players"), list):
        try: d["players"] = json.loads(d.get("players") or "[]")
        except Exception: d["players"] = []
    return d
def sb_get_matches(limit=24, offset=0):
    return [_sb_norm(x) for x in _sb_get("matches?select=*&order=uploaded.desc&limit=%d&offset=%d" % (limit, offset)).json()]
def sb_get_match(mid):
    rows = _sb_get("matches?id=eq.%s&select=*&limit=1" % mid).json()
    return _sb_norm(rows[0]) if rows else None
def sb_count_matches():
    import requests
    r = requests.get(_sb_base() + "/rest/v1/matches?select=id",
                     headers={**_sb_h(body_json=False), "Prefer": "count=exact", "Range": "0-0"}, timeout=30)
    cr = r.headers.get("content-range", "")
    try: return int(cr.split("/")[-1])
    except Exception:
        try: return len(r.json())
        except Exception: return 0
def sb_stats():
    rows = _sb_get("matches?select=length_sec,won").json()
    n = len(rows); tsec = sum(int(x.get("length_sec") or 0) for x in rows)
    rated = [x for x in rows if x.get("won") is not None]; w = sum(1 for x in rated if x.get("won"))
    return n, tsec, ("%d%%" % round(100*w/len(rated)) if rated else "—")
def sb_set_analysis(mid, js):
    import requests
    val = None
    if js:
        try: val = json.loads(js) if isinstance(js, str) else js
        except Exception: val = None
    requests.patch(_sb_base() + "/rest/v1/matches?id=eq.%s" % mid,
                   headers={**_sb_h(write=True), "Prefer": "return=minimal"},
                   data=json.dumps({"analysis": val}, ensure_ascii=False).encode("utf-8"), timeout=30)
def sb_patch_match(mid, fields):
    import requests
    r = requests.patch(_sb_base() + "/rest/v1/matches?id=eq.%s" % mid,
                   headers={**_sb_h(write=True), "Prefer": "return=minimal"},
                   data=json.dumps(fields, ensure_ascii=False, default=str).encode("utf-8"), timeout=30)
    if r.status_code not in (200, 204):
        raise RuntimeError("PATCH %s: %s" % (r.status_code, (r.text or "")[:150]))
def sb_get_comments(mid):
    return _sb_get("comments?match_id=eq.%s&select=id,author,body,created&order=created.asc" % mid).json()
def sb_add_comment(mid, author, body):
    import requests
    r = requests.post(_sb_base() + "/rest/v1/comments",
                      headers={**_sb_h(write=False), "Prefer": "return=representation"},
                      data=json.dumps({"match_id": mid, "author": author, "body": body}, ensure_ascii=False).encode("utf-8"), timeout=30)
    try: return r.json()[0]
    except Exception:
        return {"author": author, "body": body, "created": datetime.datetime.now().isoformat(timespec="seconds")}
def sb_comment_counts(ids):
    if not ids: return {}
    rows = _sb_get("comments?match_id=in.(%s)&select=match_id" % ",".join(ids)).json()
    out = {}
    for r in rows: out[r["match_id"]] = out.get(r["match_id"], 0) + 1
    return out
def sb_like(mid, delta):
    import requests
    r = requests.post(_sb_base() + "/rest/v1/rpc/like_match", headers=_sb_h(),
                      data=json.dumps({"mid": mid, "delta": delta}), timeout=30)
    try: return int(r.json())
    except Exception: return 0
def sb_view(mid):
    import requests
    try: requests.post(_sb_base() + "/rest/v1/rpc/bump_view", headers=_sb_h(), data=json.dumps({"mid": mid}), timeout=15)
    except Exception: pass
def sb_player_games(name):
    rows = sb_get_matches(limit=300, offset=0)
    return [r for r in rows if any((p.get("name") == name) for p in (r.get("players") or []))]

def sync_existing_to_cloud(log_fn=None):
    """로컬(SQLite)에 쌓인 기존 경기들을 Supabase 로 업로드. 이미 올라간 건 건너뜀."""
    lg = log_fn or log
    if not sb_writable():
        if sb_cfg().get("url") and sb_cfg().get("anon_key"):
            lg("⚠ Supabase service_role 키가 비어있어요 → config.json 의 supabase.service_key 에 넣고 재시작하세요.")
        else:
            lg("Supabase 설정이 없어요. config.json 의 supabase 를 먼저 채워주세요.")
        return (0, 0, 0)
    recover_orphan_clips(lg)         # 게임 직후 종료 등으로 ingest 전에 멈춘 평면 영상 먼저 복구
    rebuild_db_from_recordings(lg)   # 폴더엔 있는데 DB엔 없는 경기 먼저 복구
    c = db()
    try: rows = c.execute("SELECT * FROM matches ORDER BY id ASC").fetchall()
    finally: c.close()
    lg(f"기존 경기 {len(rows)}개 확인 — Supabase 로 업로드 시작…")
    done = skipped = failed = 0
    for r in rows:
        d = _row(r); mid = d.get("id")
        if not mid: continue
        v = d.get("video") or ""
        if v.startswith("http"): skipped += 1; continue           # 이미 클라우드 URL
        try:
            if sb_get_match(mid): skipped += 1; continue           # 이미 등록됨
        except Exception: pass
        vlocal = os.path.join(UPLOAD_DIR, v) if v else None
        if not (vlocal and os.path.isfile(vlocal)):
            lg(f"  · 건너뜀(영상 파일 없음): {d.get('map') or mid}"); skipped += 1; continue
        tlocal = os.path.join(UPLOAD_DIR, d.get("thumb")) if d.get("thumb") else None
        rlocal = os.path.join(UPLOAD_DIR, d.get("replay")) if d.get("replay") else None
        try:
            lg(f"  · 업로드 중: {d.get('map') or mid} ({(d.get('video_size') or 0)/1048576:.0f}MB)…")
            video_url = sb_upload(vlocal, f"videos/{mid}.mp4", "video/mp4")
            thumb_url = sb_upload(tlocal, f"thumbs/{mid}.jpg", "image/jpeg") if (tlocal and os.path.isfile(tlocal)) else None
            replay_url = sb_upload(rlocal, f"replays/{mid}.rep", "application/octet-stream") if (rlocal and os.path.isfile(rlocal)) else None
            analysis = None
            if d.get("analysis"):
                try: analysis = json.loads(d["analysis"])
                except Exception: analysis = None
            if analysis is None and rlocal and os.path.isfile(rlocal):
                try:
                    analysis = extract_analysis(rlocal)
                    try: analysis["highlights"] = compute_highlights(analysis)
                    except Exception: pass
                except Exception: pass
            sb_insert_match({
                "id": mid, "uploader": d.get("uploader"),
                "uploaded": d.get("uploaded") or datetime.datetime.now().isoformat(timespec="seconds"),
                "video": video_url, "thumb": thumb_url, "replay": replay_url,
                "video_size": d.get("video_size") or 0, "map": d.get("map"), "matchup": d.get("matchup"),
                "length": d.get("length"), "length_sec": d.get("length_sec") or 0,
                "type": d.get("type"), "winner": d.get("winner"), "saver": d.get("saver"),
                "np": d.get("np") or len(d.get("players") or []), "players": d.get("players") or [],
                "won": (bool(d["won"]) if d.get("won") is not None else None), "analysis": analysis})
            done += 1; lg(f"    ✓ 완료: {d.get('map') or mid}")
        except Exception as e:
            failed += 1; lg(f"    ✗ 실패({mid}): {e}")
    lg(f"기존 경기 업로드 끝 — 완료 {done} · 건너뜀 {skipped} · 실패 {failed}")
    return (done, skipped, failed)


def _gid_time(gid):
    try:
        return datetime.datetime.strptime((gid or "")[:15], "%Y%m%d-%H%M%S").isoformat(timespec="seconds")
    except Exception:
        return datetime.datetime.now().isoformat(timespec="seconds")

def reanalyze_all(log_fn=None):
    """기존 경기를 새 분석으로 다시 분석해 Supabase 갱신(영상 재업로드 X). 로컬 .rep 우선, 없으면 클라우드에서 받음."""
    lg = log_fn or log
    if not SCREP:
        lg("✗ screp가 없어 재분석할 수 없어요."); return 0
    if not sb_writable():
        lg("✗ 클라우드 쓰기 권한이 없어요 (service_key 확인)."); return 0
    if not sb_cfg().get("service_key"):
        lg("⚠ service_key가 없어요 — 기존 경기 갱신은 RLS 때문에 막힐 수 있어요. config.json 의 supabase.service_key 를 채우면 확실합니다.")
    try:
        matches = sb_get_matches(limit=100000)
    except Exception as e:
        lg(f"✗ 경기 목록을 못 불러왔어요: {e}"); return 0
    lg(f"기존 경기 {len(matches)}개 재분석 시작…")
    done = failed = skipped = 0
    for m in matches:
        mid = m.get("id")
        if not mid: continue
        rep = os.path.join(UPLOAD_DIR, mid, "replay.rep")
        tmp = None
        if not os.path.isfile(rep):
            rurl = _media_url(m.get("replay")) if m.get("replay") else None
            if not rurl:
                skipped += 1; lg(f"  · 건너뜀(리플레이 없음): {m.get('map') or mid}"); continue
            try:
                import requests, tempfile
                rr = requests.get(rurl, timeout=120); rr.raise_for_status()
                tmp = tempfile.mktemp(suffix=".rep")
                with open(tmp, "wb") as f: f.write(rr.content)
                rep = tmp
            except Exception as e:
                failed += 1; lg(f"  · .rep 받기 실패({mid}): {e}"); continue
        try:
            meta = parse_rep(rep); a = extract_analysis(rep)
            try: a["highlights"] = compute_highlights(a)
            except Exception: pass
            players = meta.get("players") or []; saver = meta.get("saver"); winner = meta.get("winner")
            sp = next((p for p in players if p.get("name") == saver), None)
            won = (sp.get("team") == winner) if (sp and winner is not None) else None
            sb_patch_match(mid, {
                "map": meta.get("map"), "matchup": meta.get("matchup"),
                "length": meta.get("length"), "length_sec": _len_sec(meta.get("length") or ""),
                "type": meta.get("type"), "winner": winner, "saver": saver,
                "np": len(players), "players": players, "won": won, "analysis": a})
            done += 1; lg(f"  · 재분석 ✓ {meta.get('map') or mid}")
        except Exception as e:
            failed += 1; lg(f"  · 재분석 실패({mid}): {e}")
        finally:
            if tmp:
                try: os.remove(tmp)
                except OSError: pass
    lg(f"✓ 재분석 완료 — 갱신 {done} · 건너뜀 {skipped} · 실패 {failed}")
    return done


def rebuild_db_from_recordings(log_fn=None):
    """recordings/ 또는 uploads/ 폴더에 영상은 있는데 DB에 없는 경기를 스캔해 복구(+옛 위치는 uploads로 정규화)."""
    lg = log_fn or log
    try:
        c = db()
        try: have = {row[0] for row in c.execute("SELECT id FROM matches").fetchall()}
        finally: c.close()
    except Exception:
        have = set()
    found = added = moved = 0; seen = set()
    for srcdir in (REC_DIR, UPLOAD_DIR):
        if not os.path.isdir(srcdir): continue
        for name in sorted(os.listdir(srcdir)):
            d = os.path.join(srcdir, name)
            if not os.path.isdir(d) or not os.path.isfile(os.path.join(d, "game.mp4")): continue
            gid = name
            if gid in seen: continue
            seen.add(gid); found += 1
            if gid in have: continue
            target = os.path.join(UPLOAD_DIR, gid)
            if os.path.abspath(d) != os.path.abspath(target):
                if os.path.exists(target):
                    if not os.path.isfile(os.path.join(target, "game.mp4")): continue
                    d = target
                else:
                    try: shutil.move(d, target); d = target; moved += 1
                    except Exception as e:
                        lg(f"  · 폴더 이동 실패({gid}): {e}"); continue
            video = os.path.join(d, "game.mp4"); rep = os.path.join(d, "replay.rep"); thumb = os.path.join(d, "thumb.jpg")
            try: size = os.path.getsize(video)
            except Exception: size = 0
            meta = {}
            if os.path.isfile(rep) and SCREP:
                try: meta = parse_rep(rep)
                except Exception as e: lg(f"  · 리플레이 분석 실패({gid}): {e}")
            if not os.path.isfile(thumb):
                try: make_thumb(video, thumb)
                except Exception: pass
            players = meta.get("players") or []; saver = meta.get("saver"); winner = meta.get("winner")
            sp = next((p for p in players if p.get("name") == saver), None)
            won = (1 if sp.get("team") == winner else 0) if (sp and winner) else None
            try:
                con = db()
                con.execute("INSERT OR REPLACE INTO matches (id,uploader,uploaded,video,replay,thumb,video_size,map,matchup,length,length_sec,type,winner,saver,np,players,won,analysis) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (gid, saver, _gid_time(gid), gid + "/game.mp4",
                     (gid + "/replay.rep" if os.path.isfile(rep) else None),
                     (gid + "/thumb.jpg" if os.path.isfile(thumb) else None),
                     size, meta.get("map"), meta.get("matchup"), meta.get("length"),
                     _len_sec(meta.get("length") or ""), meta.get("type"), winner, saver,
                     len(players), json.dumps(players, ensure_ascii=False), won, None))
                con.commit(); con.close()
                have.add(gid); added += 1
                lg(f"  · 복구: {meta.get('map') or gid} ({size/1048576:.0f}MB)")
            except Exception as e:
                lg(f"  · DB 복구 실패({gid}): {e}")
    if found:
        lg(f"폴더 복구 — 발견 {found} · 새로 추가 {added} · 이동 {moved}")
    return added


def recover_orphan_clips(log_fn=None):
    """게임 직후 PC를 바로 꺼서 ingest 전에 멈춘 평면 clip_*.mp4 를,
    AutoSave 리플레이와 (저장시각≈녹화종료 + 게임길이≤영상길이) 기준으로 짝지어 복구한다."""
    lg = log_fn or log
    if not os.path.isdir(REC_DIR): return 0
    cand = {}   # stamp -> (path, is_av)
    for p in sorted(glob.glob(os.path.join(REC_DIR, "clip_*.mp4"))):
        m = re.match(r"clip_(\d{8}_\d{6})(_av)?\.mp4$", os.path.basename(p))
        if not m: continue
        stamp, is_av = m.group(1), bool(m.group(2))
        cur = cand.get(stamp)
        if cur is None or (is_av and not cur[1]):     # 같은 게임이면 소리 합쳐진 _av 우선
            cand[stamp] = (p, is_av)
    if not cand: return 0
    repdir = CFG.get("replay_autosave_dir") or detect_replay_dir()
    reps = []
    if repdir and os.path.isdir(repdir):
        for rp in glob.glob(os.path.join(repdir, "**", "*.rep"), recursive=True):
            try: reps.append((rp, os.path.getmtime(rp)))
            except OSError: pass
    if not reps:
        lg("미처리 영상이 있지만 AutoSave 리플레이 폴더를 못 찾았어요 — config.json 의 replay_autosave_dir 를 확인하세요.")
        return 0
    lg(f"미처리 영상 {len(cand)}개 발견 — 리플레이와 짝짓는 중…")
    used = set(); recovered = 0
    for stamp, (vpath, is_av) in sorted(cand.items()):
        try: tv = datetime.datetime.strptime(stamp, "%Y%m%d_%H%M%S").timestamp()
        except Exception: continue
        lv = _ffprobe_dur(vpath) or 0
        tend = (tv + lv) if lv else tv                # 녹화 종료 ≈ 게임 종료 ≈ 리플레이 저장 시각
        best = None; bestd = None
        for rp, mt in reps:
            if rp in used: continue
            if mt < tv - 120: continue                # 영상보다 너무 이른 리플레이 제외
            try: rmeta = parse_rep(rp) if SCREP else {}
            except Exception: rmeta = {}
            if SCREP and not (rmeta or {}).get("players"): continue   # 실제 게임만
            lr = _len_sec((rmeta or {}).get("length") or "")
            if lv and lr and lr > lv * 1.15 + 30: continue            # 게임이 영상보다 길 수 없음
            d = abs(mt - tend)
            if bestd is None or d < bestd: best, bestd = rp, d
        if best is None or (lv and bestd is not None and bestd > 180):  # 시각이 3분 넘게 어긋나면 신뢰 불가 → 보류
            lg(f"  · 보류(맞는 리플레이 못 찾음): clip_{stamp}"); continue
        used.add(best)
        lg(f"  · 복구: clip_{stamp}  ←  {os.path.basename(best)}")
        try:
            ingest(vpath, best, uploader=CFG.get("username") or None)
            recovered += 1
        except Exception as e:
            lg(f"  · 복구 실패(clip_{stamp}): {e}")
    if recovered: lg(f"✓ 미처리 영상 복구 완료 — {recovered}건")
    return recovered


def player_games(name):
    if sb_enabled(): return sb_player_games(name)
    c = db(); rows = c.execute("SELECT * FROM matches ORDER BY id DESC").fetchall(); c.close()
    out = []
    for r in rows:
        d = _row(r)
        if any(p.get("name") == name for p in (d.get("players") or [])): out.append(d)
    return out

# ----- R2 (Cloudflare, S3 호환) : 큰 영상은 여기로 직접 -----
def _boto3():
    try:
        import boto3; return boto3
    except ImportError:
        log("boto3 설치 중…")
        _run([sys.executable, "-m", "pip", "install", "-q", "boto3", "--break-system-packages"])
        import boto3; return boto3
def r2_cfg(): return CFG.get("r2") or {}
def r2_enabled():
    r = r2_cfg()
    return bool(r.get("account_id") and r.get("bucket") and r.get("access_key_id") and r.get("secret_access_key"))
def r2_client():
    r = r2_cfg(); b = _boto3()
    return b.client("s3", endpoint_url=f"https://{r['account_id']}.r2.cloudflarestorage.com",
                    aws_access_key_id=r["access_key_id"], aws_secret_access_key=r["secret_access_key"],
                    region_name="auto")
def r2_public(key):
    base = (r2_cfg().get("public_base_url") or "").rstrip("/")
    return f"{base}/{key}" if base else key
def r2_upload(local, key, ctype):
    r2_client().upload_file(local, r2_cfg()["bucket"], key, ExtraArgs={"ContentType": ctype})
    return r2_public(key)
def r2_presign_put(key, ctype, expires=3600):
    return r2_client().generate_presigned_url("put_object",
        Params={"Bucket": r2_cfg()["bucket"], "Key": key, "ContentType": ctype}, ExpiresIn=expires)

def _insert_match(gid, video, replay, thumb, size, uploader, meta):
    players = meta.get("players") or []; saver = meta.get("saver"); winner = meta.get("winner")
    sp = next((p for p in players if p.get("name") == saver), None)
    won = (1 if sp.get("team") == winner else 0) if (sp and winner) else None
    c = db()
    c.execute("INSERT OR REPLACE INTO matches (id,uploader,uploaded,video,replay,thumb,video_size,map,matchup,length,length_sec,type,winner,saver,np,players,won,analysis) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (gid, uploader or saver, datetime.datetime.now().isoformat(timespec="seconds"),
         video, replay, thumb, size or 0,
         meta.get("map"), meta.get("matchup"), meta.get("length"), _len_sec(meta.get("length") or ""),
         meta.get("type"), winner, saver, len(players),
         json.dumps(players, ensure_ascii=False), won, None))
    c.commit(); c.close()
    tag = " [R2]" if (video or "").startswith("http") else ""
    log(f"✓ 등록됨: {meta.get('map') or '게임'} ({(size or 0)/1048576:.0f}MB) by {uploader or saver or '?'}{tag}")

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

def _ffprobe_dur(path):
    probe = None
    if FFMPEG:
        c = (FFMPEG[:-10] + "ffprobe.exe") if FFMPEG.lower().endswith("ffmpeg.exe") else FFMPEG.replace("ffmpeg", "ffprobe")
        if os.path.isfile(c): probe = c
    probe = probe or shutil.which("ffprobe")
    if not probe: return None
    try:
        r = _run([probe, "-v", "error", "-show_entries", "format=duration",
                  "-of", "default=nw=1:nk=1", path], capture_output=True, timeout=20)
        return float((r.stdout or "0").strip() or 0)
    except Exception:
        return None

CLIP_KINDS = {"battle", "gg", "drop"}
def make_clips(video_path, highlights, game_len_sec, out_dir, lead=6.0, maxn=3, dur=30.0, pre=12.0):
    """하이라이트(교전·드랍·GG) 지점에서 짧은 공유용 클립 생성 → [(highlight_idx, local_path), ...]."""
    if not FFMPEG or not highlights: return []
    vdur = _ffprobe_dur(video_path)
    offset = (vdur - game_len_sec) if (vdur and game_len_sec and vdur > game_len_sec + 0.5) else lead
    offset = max(0.0, min(offset, 60.0))
    cand = [(i, h) for i, h in enumerate(highlights) if h.get("kind") in CLIP_KINDS]
    def _pr(ih):
        h = ih[1]; lbl = h.get("label") or ""
        if "최대" in lbl: return 0
        return {"gg": 1, "drop": 2, "battle": 3}.get(h.get("kind"), 9)
    cand.sort(key=_pr); cand = cand[:maxn]
    cand.sort(key=lambda ih: ih[1].get("sec", 0))
    made = []
    for idx, h in cand:
        vstart = max(0.0, (h.get("sec", 0) or 0) + offset - pre)
        clip = os.path.join(out_dir, f"clip{idx}.mp4")
        try:
            _run([FFMPEG, "-y", "-loglevel", "error", "-ss", f"{vstart:.2f}", "-i", video_path,
                  "-t", f"{dur:.0f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                  "-g", "48", "-keyint_min", "24",
                  "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", clip], timeout=180)
            if os.path.isfile(clip) and os.path.getsize(clip) > 5000:
                made.append((idx, clip))
        except Exception:
            pass
    return made

def ingest(video_path, rep_path, uploader=None):
    if not video_path or not os.path.isfile(video_path) or os.path.getsize(video_path) < 10000:
        log("영상이 비어있어 등록 생략."); return
    gid = datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)
    size = os.path.getsize(video_path)
    base = os.path.join(UPLOAD_DIR, gid); os.makedirs(base, exist_ok=True)
    # .rep(작음)은 항상 로컬 보관 — 분석/다운로드용
    rdst = None; meta = {}
    if rep_path and os.path.isfile(rep_path):
        rdst = os.path.join(base, "replay.rep"); shutil.copy(rep_path, rdst); meta = parse_rep(rdst)
    replay_ref = f"{gid}/replay.rep" if rdst else None
    # 리플레이가 없거나(메뉴·대기 화면) 분석할 선수 정보가 없으면 = 게임이 아님 → 저장하지 않고 폐기(용량 낭비 방지)
    if not (rdst and (meta.get("players"))):
        secs = ""
        try: secs = f"({os.path.getsize(video_path)/1048576:.0f}MB)"
        except Exception: pass
        log(f"리플레이가 없는 녹화 {secs} 는 게임이 아니라서 저장하지 않고 버립니다.")
        try:
            if video_path and os.path.isfile(video_path): os.remove(video_path)
        except OSError: pass
        try:
            import shutil as _sh2; _sh2.rmtree(base, ignore_errors=True)
        except Exception: pass
        return
    # 너무 짧은 게임(초반에 나간 게임 등)은 저장하지 않음
    _gsec = _len_sec(meta.get("length") or "")
    if _gsec and _gsec < CFG.get("min_game_sec", 120):
        log(f"게임이 너무 짧아({meta.get('length')}) 저장하지 않고 버립니다 — 초반에 끝난 게임으로 보입니다.")
        try:
            if video_path and os.path.isfile(video_path): os.remove(video_path)
        except OSError: pass
        try:
            import shutil as _sh3; _sh3.rmtree(base, ignore_errors=True)
        except Exception: pass
        return
    # 영상 앞 로비/로딩을 잘라 카운트다운(0:00)부터 보이게
    try:
        _gl = _len_sec(meta.get("length") or "")
        if _gl and video_path and os.path.isfile(video_path): _trim_lead(video_path, _gl)
    except Exception: pass
    if sb_writable():
        analysis = None
        try:
            if rdst:
                analysis = extract_analysis(rdst)
                try: analysis["highlights"] = compute_highlights(analysis)
                except Exception: pass
        except Exception as e:
            log(f"분석 실패(계속 진행): {e}")
        _tt = None
        try: _tt = _thumb_time((analysis or {}).get("highlights"), video_path, _gl)
        except Exception: pass
        tmp_thumb = os.path.join(base, "thumb.jpg"); has_thumb = make_thumb(video_path, tmp_thumb, at=_tt)
        try:
            if analysis and analysis.get("highlights"):
                _clips = make_clips(video_path, analysis["highlights"], _gsec or 0, base)
                for _ci, _cl in _clips:
                    try: analysis["highlights"][_ci]["clip"] = sb_upload(_cl, f"clips/{gid}_{_ci}.mp4", "video/mp4")
                    except Exception: pass
                    try: os.remove(_cl)
                    except OSError: pass
                if _clips: log(f"  하이라이트 클립 {len(_clips)}개 생성·업로드")
        except Exception as _e:
            log(f"클립 생성 생략: {_e}")
        try:
            video_url = sb_upload(video_path, f"videos/{gid}.mp4", "video/mp4")
            thumb_url = sb_upload(tmp_thumb, f"thumbs/{gid}.jpg", "image/jpeg") if has_thumb else None
            replay_url = sb_upload(rdst, f"replays/{gid}.rep", "application/octet-stream") if rdst else None
            players = meta.get("players") or []; saver = meta.get("saver"); winner = meta.get("winner")
            sp = next((p for p in players if p.get("name") == saver), None)
            won = (sp.get("team") == winner) if (sp and winner is not None) else None
            sb_insert_match({
                "id": gid, "uploader": uploader or saver,
                "uploaded": datetime.datetime.now().isoformat(timespec="seconds"),
                "video": video_url, "thumb": thumb_url, "replay": replay_url,
                "video_size": size or 0, "map": meta.get("map"), "matchup": meta.get("matchup"),
                "length": meta.get("length"), "length_sec": _len_sec(meta.get("length") or ""),
                "type": meta.get("type"), "winner": winner, "saver": saver,
                "np": len(players), "players": players, "won": won, "analysis": analysis})
            for p in (video_path, tmp_thumb):
                try: os.remove(p)
                except OSError: pass
            log(f"☁ Supabase 등록: {meta.get('map') or '게임'} ({(size or 0)/1048576:.0f}MB) by {uploader or saver or '?'}")
            return
        except Exception as e:
            log(f"Supabase 업로드/저장 실패: {e} — 로컬에 보관합니다.")
    if r2_enabled():
        tmp_thumb = os.path.join(base, "thumb.jpg"); has_thumb = make_thumb(video_path, tmp_thumb)
        try:
            video_ref = r2_upload(video_path, f"videos/{gid}.mp4", "video/mp4")
            thumb_ref = r2_upload(tmp_thumb, f"thumbs/{gid}.jpg", "image/jpeg") if has_thumb else None
        except Exception as e:
            log(f"R2 업로드 실패: {e}"); return
        for p in (video_path, tmp_thumb):
            try: os.remove(p)
            except OSError: pass
        _insert_match(gid, video_ref, replay_ref, thumb_ref, size, uploader, meta)
    else:
        vdst = os.path.join(base, "game.mp4"); shutil.move(video_path, vdst)
        thumb = os.path.join(base, "thumb.jpg"); has_thumb = make_thumb(vdst, thumb)
        _insert_match(gid, f"{gid}/game.mp4", replay_ref,
                      (f"{gid}/thumb.jpg" if has_thumb else None), size, uploader, meta)

# ===================== 5. 갤러리 서버 (ENCORE UI) =====================
import logging; logging.getLogger("werkzeug").setLevel(logging.ERROR)

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

def _thumb_time(highlights, video_path, game_len_sec):
    """가장 극적인 순간(최대 교전 우선 → 후반 교전 → 드랍)의 영상 시각.
    영상 길이로 게임 시작 오프셋을 역산해 게임시각 → 영상시각으로 변환(트림 여부 무관)."""
    if not highlights: return None
    battles = [h for h in highlights if h.get("kind") == "battle" and h.get("sec") is not None]
    pick = next((h for h in battles if h.get("label") == "최대 교전"), None)
    if not pick and battles: pick = max(battles, key=lambda h: h.get("sec") or 0)
    if not pick:
        drops = [h for h in highlights if h.get("kind") == "drop" and h.get("sec") is not None]
        pick = drops[0] if drops else None
    if not pick: return None
    s = float(pick.get("sec") or 0)
    if game_len_sec and s >= float(game_len_sec) - 4: s = max(0.0, float(game_len_sec) - 12)
    dur = _ffprobe_dur(video_path)
    if dur and game_len_sec: return max(0.0, dur - float(game_len_sec)) + s
    return s + 6.0

def esc(s): return html.escape(str(s)) if s is not None else ""
def _team_color(players, t):
    cs = [p.get("color") for p in players if p.get("team") == t]
    return cs[0] if cs else "#7c8a99"

def _media_url(v):
    if not v: return ""
    return v if v.startswith("http") else "/media/" + v


def _roster(g, t, compact=False):
    rows = ""
    for p in [x for x in g["players"] if x.get("team") == t]:
        me = "me" if p.get("name") == g.get("me") else ""
        apm = "" if compact else f'<span class="ap">{p.get("apm") or 0}<i>apm</i></span>'
        rc = (p.get("race") or "?")[0].upper()
        rows += (f'<li class="prow {me}"><span class="cc" style="background:{esc(p.get("color"))}"></span>'
                 f'<a class="pn pnl" href="/player/{quote(p.get("name") or "")}">{esc(p.get("name")) or "—"}</a>'
                 f'<span class="rb r-{esc(p.get("race"))}">{rc}</span>{apm}</li>')
    return rows

def _teams(g, compact=False):
    w = g.get("winner")
    def one(t):
        wc = "is-win" if w == t else ""
        tag = '<span class="wtag">WIN</span>' if w == t else ""
        return (f'<div class="team {wc}"><div class="thead"><span class="tnum">TEAM {t}</span>{tag}</div>'
                f'<ul class="roster">{_roster(g, t, compact)}</ul></div>')
    return f'{one(1)}<div class="vsbar"><span>VS</span></div>{one(2)}'

def _resbadge(g, big=False):
    w = g.get("won"); cls = "win" if w is True else ("loss" if w is False else "na")
    txt = "승리" if w is True else ("패배" if w is False else "기록")
    return f'<span class="resbadge {cls} {"big" if big else ""}">{txt}</span>'

def _poster(g, big=False):
    c1, c2 = _team_color(g["players"], 1), _team_color(g["players"], 2)
    pa = f' poster="{esc(g["thumb_url"])}"' if g.get("thumb_url") else ""
    inner = f'<video controls preload="metadata"{pa} src="{esc(g["video_url"])}"></video>'
    return (f'<div class="poster {"big" if big else ""}" style="--c1:{c1};--c2:{c2}">'
            f'<div class="pscan"></div><div class="pgrid"></div>{inner}{_resbadge(g, big)}'
            f'<div class="pmeta"><span class="mu">{esc(g["matchup"])}</span>'
            f'<span class="pln">◷ {esc(g["length"])}</span></div></div>')












def _player_hero(name, av, games, wr, avg, rc):
    return (f'<section class="phero"><a class="pback" href="/">‹ 아카이브</a>'
            f'<div class="prow"><div class="phav">{esc(av)}</div>'
            f'<div><div class="pey">Player Profile</div><h1 class="pname">{esc(name)}</h1></div></div>'
            f'<div class="pstats">{_stat(games,"경기")}{_stat(wr,"승률",True)}{_stat(avg,"평균 APM")}'
            f'<div class="stat"><div class="v" style="font-size:15px;font-weight:600">{esc(rc)}</div><div class="k">종족</div></div></div></section>')


PAGE_SIZE = 24

























# ===================== 6. 녹화기 (ffmpeg) =====================
_ENC_CACHE = None
_ENC_IS_SW = False   # 소프트웨어(libx264) 인코딩 여부 → 다운스케일 판단에 사용
_ENC_FORCE_SW = False   # 런타임 NVENC 실패가 누적되면 강제로 소프트웨어로 고정
def _force_software_encoder(reason=""):
    """게임 도중 GPU 인코더(NVENC)가 반복 실패할 때 호출 — 이후 녹화는 libx264로."""
    global _ENC_FORCE_SW, _ENC_CACHE
    if _ENC_FORCE_SW: return
    _ENC_FORCE_SW = True; _ENC_CACHE = None   # 캐시 비워 다음 인코딩부터 재선택
    if reason: log("[안정성] " + reason)
def _enc_is_software():
    _encoder_args()   # _ENC_IS_SW 확정
    return _ENC_IS_SW
def _encoder_args():
    """인코더 자동 선택. NVENC는 '실제로 인코딩 되는지'까지 테스트 — 목록엔 있어도 런타임 실패면 libx264로."""
    global _ENC_CACHE, _ENC_IS_SW
    if _ENC_CACHE is not None: return _ENC_CACHE
    pref = (CFG.get("encoder") or "auto").lower()
    if _ENC_FORCE_SW: pref = "x264"   # 런타임 폴백 발동 시 사용자 설정보다 우선
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
    # 키프레임 간격 ~2초 — 시크(특히 분할 보기 다중 영상 동시 시크) 속도를 위해 GOP 고정.
    # 기본은 GOP가 ~250프레임(8초)이라 시크 시 최대 8초어치를 디코드해야 해 버벅인다.
    try: _gop = max(15, int(round(2 * float(CFG.get("fps", FPS) or FPS))))
    except Exception: _gop = 60
    if use_nvenc:
        _ENC_IS_SW = False
        _ENC_CACHE = ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", "20",
                      "-g", str(_gop)]; name = "NVENC (NVIDIA 하드웨어)"
    else:
        _ENC_IS_SW = True
        preset = (CFG.get("preset") or "auto").lower()
        if preset in ("auto", ""): preset = "superfast"   # 소프트웨어는 게임 끊김 방지 위해 가벼운 프리셋
        _ENC_CACHE = ["-c:v", "libx264", "-preset", preset, "-crf", "25",
                      "-g", str(_gop), "-keyint_min", str(max(1, _gop // 2))]; name = f"libx264 (소프트웨어, {preset})"
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
        # 프레임/종료 콜백 — 테두리 설정과 무관하게 재사용(폴백 시 새 캡처에 다시 등록)
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
        def on_closed():
            pass
        def _wgc_make(border):
            c = WindowsCapture(cursor_capture=None, draw_border=border, monitor_index=1, window_name=None)
            c.event(on_frame_arrived); c.event(on_closed)
            return c

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

        # 녹화 중 노란 테두리 제거: draw_border=False (Win11 빌드 22000+에서 IsBorderRequired 지원).
        # 구형 OS에서 그 설정으로 시작이 안 되면 기본값(테두리 표시)으로 폴백 — WGC 백엔드 자체는 유지.
        cap = control = None
        for _border in (False, None):
            try:
                cap = _wgc_make(_border); control = cap.start_free_threaded()
                if _border is None:
                    log("  WGC: 캡처 테두리 끄기 미지원 OS → 기본 설정으로 시작(테두리가 보일 수 있음)")
                break
            except Exception as e:
                control = None
                if _border is False:
                    log(f"  WGC 테두리 끄기로 시작 실패({e}) → 기본 설정으로 재시도")
                else:
                    log(f"  WGC 시작 실패: {e}"); return False
        if control is None:
            return False
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
            _found, _fg, _min = sc_window_state(CFG.get("starcraft_process") or "StarCraft.exe")
            if _min:
                log("[!] 스타크래프트가 최소화되어 있어요 — 게임 화면을 띄워두면 자동으로 정상 녹화됩니다.")
            elif _found and not _fg:
                log("[!] 스타크래프트가 뒤에 있어요(다른 창이 앞) — 게임 창을 앞으로 두면 화면이 잡힙니다.")
                log("    • 듀얼 모니터면 config.json 의 \"output_idx\" 를 게임이 있는 모니터 번호(0/1/2)로 지정해 보세요")
            else:
                log("[!] 화면 캡처를 확인 못 했어요(검은 화면일 수 있음). 그래도 녹화는 계속합니다.")
                log("    • 먼저 한 판 하고 갤러리에서 영상 확인 (메뉴 정지화면 오탐일 수 있음)")
                log("    • config.json 의 \"capture\" 를 \"wgc\" 로 바꾸거나, 스타를 '창 모드(전체 화면)'로 해보세요")
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

def sc_window_state(procname):
    """스타크래프트 창 상태 → (창있음, 포커스됨, 최소화됨). 윈도우가 아니거나 못 찾으면 (False, False, False).
    검은 화면 오탐(최소화·다른 모니터)을 정확히 안내하는 데 사용."""
    if sys.platform != "win32":
        return (False, False, False)
    try:
        import ctypes
        from ctypes import wintypes
        u = ctypes.windll.user32
        target = (procname or "").lower(); pids = set()
        for p in psutil.process_iter(["name", "pid"]):
            try:
                if (p.info["name"] or "").lower() == target: pids.add(p.info["pid"])
            except (psutil.NoSuchProcess, psutil.AccessDenied): pass
        if not pids:
            return (False, False, False)
        box = {"hwnd": None}
        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def _cb(hwnd, _lp):
            try:
                if not u.IsWindowVisible(hwnd): return True
                pid = wintypes.DWORD()
                u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value in pids:
                    box["hwnd"] = hwnd; return False   # 첫 가시 창에서 멈춤
            except Exception:
                pass
            return True
        u.EnumWindows(WNDENUMPROC(_cb), 0)
        hwnd = box["hwnd"]
        if not hwnd:
            return (True, False, False)               # 프로세스는 있으나 가시 창 없음(로딩 등)
        minimized = bool(u.IsIconic(hwnd))
        foreground = bool(u.GetForegroundWindow() == hwnd)
        return (True, foreground, minimized)
    except Exception:
        return (False, False, False)

def list_reps(d):
    if not os.path.isdir(d): return {}
    out = {}
    for f in glob.glob(os.path.join(d, "**", "*.rep"), recursive=True):
        try: out[f] = os.path.getmtime(f)
        except OSError: pass
    return out

PENDING_PATH = os.path.join(DATA_DIR, "pending.json")
def _load_pending():
    if os.path.isfile(PENDING_PATH):
        try: return json.load(open(PENDING_PATH, encoding="utf-8"))
        except Exception: return []
    return []
def _save_pending(q): json.dump(q, open(PENDING_PATH, "w", encoding="utf-8"))
def _post(video, rep):
    sv = CFG.get("server", {}) or {}; url = (sv.get("url", "") or "").rstrip("/") + "/upload"; key = sv.get("api_key", "")
    files = {"video": ("game.mp4", open(video, "rb"), "video/mp4")}
    if rep and os.path.isfile(rep): files["replay"] = ("replay.rep", open(rep, "rb"), "application/octet-stream")
    try:
        r = requests.post(url, files=files, data={"key": key, "uploader": CFG.get("username") or ""}, timeout=(10, 1800))
        return r.status_code == 200
    finally:
        for f in files.values():
            try: f[1].close()
            except Exception: pass
def _post_r2(video, rep):
    sv = CFG.get("server", {}) or {}; base = (sv.get("url", "") or "").rstrip("/"); key = sv.get("api_key", "")
    pr = requests.post(base + "/api/presign", json={"key": key}, timeout=30)
    if pr.status_code == 409: return None          # 서버에 R2 미설정 → 레거시로
    if pr.status_code != 200: return False
    info = pr.json(); size = os.path.getsize(video)
    tmp_thumb = os.path.join(REC_DIR, "up_thumb.jpg"); has_thumb = make_thumb(video, tmp_thumb)
    with open(video, "rb") as f:
        if requests.put(info["video_put"], data=f, headers={"Content-Type": "video/mp4"},
                        timeout=(10, 3600)).status_code not in (200, 201): return False
    if has_thumb and info.get("thumb_put"):
        try:
            with open(tmp_thumb, "rb") as f:
                requests.put(info["thumb_put"], data=f, headers={"Content-Type": "image/jpeg"}, timeout=(10, 600))
        except Exception: pass
    files = {}
    if rep and os.path.isfile(rep): files["replay"] = ("replay.rep", open(rep, "rb"), "application/octet-stream")
    data = {"key": key, "uploader": CFG.get("username") or "", "gid": info["gid"],
            "video_url": info["video_url"], "thumb_url": info.get("thumb_url") or "", "size": str(size)}
    try:
        rr = requests.post(base + "/api/register", data=data, files=files, timeout=120)
    finally:
        for fo in files.values():
            try: fo[1].close()
            except Exception: pass
    return rr.status_code == 200

def _put_file(url, path, ctype):
    with open(path, "rb") as f:
        r = requests.put(url, data=f, headers={"Content-Type": ctype}, timeout=(10, 3600))
    if r.status_code not in (200, 201):
        raise RuntimeError(f"R2 PUT 실패 {r.status_code}")

def _cloud_send(video, rep):
    """영상·썸네일·.rep 를 R2로 직접, 메타+분석을 Supabase Edge Function 으로. 성공 시 True (영상 삭제 포함)."""
    if not video or not os.path.isfile(video): return True
    cl = CFG.get("cloud") or {}; url = (cl.get("function_url", "") or "").rstrip("/"); key = cl.get("upload_key", "")
    user = CFG.get("username") or ""
    meta = parse_rep(rep) if (rep and os.path.isfile(rep)) else {}
    try: analysis = extract_analysis(rep) if (rep and os.path.isfile(rep) and SCREP) else None
    except Exception: analysis = None
    pr = requests.post(url, json={"key": key, "action": "presign"}, timeout=30)
    if pr.status_code != 200: return False
    info = pr.json(); gid = info["gid"]; size = os.path.getsize(video)
    tmp_thumb = os.path.join(REC_DIR, "up_thumb.jpg"); has_thumb = make_thumb(video, tmp_thumb)
    _put_file(info["video_put"], video, "video/mp4")
    if has_thumb: _put_file(info["thumb_put"], tmp_thumb, "image/jpeg")
    if rep and os.path.isfile(rep): _put_file(info["rep_put"], rep, "application/octet-stream")
    players = meta.get("players") or []; saver = meta.get("saver"); winner = meta.get("winner")
    sp = next((p for p in players if p.get("name") == saver), None)
    won = (sp.get("team") == winner) if (sp and winner) else None
    row = {"id": gid, "uploader": user or saver,
           "uploaded": datetime.datetime.now().isoformat(timespec="seconds"),
           "video": info["video_url"], "thumb": (info["thumb_url"] if has_thumb else None),
           "replay": (info["rep_url"] if (rep and os.path.isfile(rep)) else None), "video_size": size,
           "map": meta.get("map"), "matchup": meta.get("matchup"), "length": meta.get("length"),
           "length_sec": _len_sec(meta.get("length") or ""), "type": meta.get("type"),
           "winner": winner, "saver": saver, "np": len(players),
           "players": players, "won": won, "analysis": analysis}
    rr = requests.post(url, json={"key": key, "action": "register", "match": row}, timeout=60)
    if rr.status_code != 200: return False
    try: os.remove(video)
    except OSError: pass
    return True

def upload_cloud(video, rep):
    if os.path.isfile(video): log(f"↑ 클라우드 업로드 중… ({os.path.getsize(video)/1048576:.0f}MB)")
    try:
        if _cloud_send(video, rep):
            log("✓ 클라우드 등록 완료"); return
        log("✗ 업로드 실패 → 대기열")
    except Exception as e:
        log(f"✗ 클라우드 업로드 실패({e}) → 대기열")
    q = _load_pending(); q.append({"v": video, "r": rep}); _save_pending(q)

def upload_remote(video, rep):
    if not video or not os.path.isfile(video): return
    sv = CFG.get("server", {}) or {}
    log(f"↑ 업로드 중… ({os.path.getsize(video)/1048576:.0f}MB → {sv.get('url','')})")
    try:
        res = _post_r2(video, rep)        # R2 직접 업로드 시도
        if res is None: res = _post(video, rep)   # 서버에 R2 미설정 → 서버 경유
        if res:
            log("✓ 업로드 완료")
            try: os.remove(video)
            except OSError: pass
        else:
            log("✗ 업로드 실패 → 대기열"); q = _load_pending(); q.append({"v": video, "r": rep}); _save_pending(q)
    except Exception as e:
        log(f"✗ 업로드 실패({e}) → 대기열"); q = _load_pending(); q.append({"v": video, "r": rep}); _save_pending(q)
def _flush_pending():
    q = _load_pending()
    if not q: return
    still = []
    for it in q:
        if not os.path.isfile(it.get("v") or ""): continue
        try:
            if (CFG.get("cloud") or {}).get("function_url"):
                if not _cloud_send(it["v"], it.get("r")): still.append(it)   # 성공 시 내부에서 삭제
            else:
                ok = _post_r2(it["v"], it.get("r"))
                if ok is None: ok = _post(it["v"], it.get("r"))
                if ok:
                    try: os.remove(it["v"])
                    except OSError: pass
                else: still.append(it)
        except Exception: still.append(it)
    _save_pending(still)
def _dispatch(video, rep):
    if (CFG.get("cloud") or {}).get("function_url"): upload_cloud(video, rep)
    elif CFG.get("mode") == "recorder": upload_remote(video, rep)
    else: ingest(video, rep, uploader=(CFG.get("username") or None))

def recorder_loop(cfg):
    proc = cfg["starcraft_process"]; autosave = cfg["replay_autosave_dir"]
    poll = float(cfg.get("poll_seconds", 4)); rec = Recorder(int(cfg.get("fps", FPS)))
    known = list_reps(autosave); was = False; active = False; enc_fail = 0
    try: ensure_audio()
    except Exception: pass
    log("준비 완료. 스타를 켜면 자동으로 녹화가 시작됩니다. (이 창은 켜둔 채로 두세요)")
    while True:
        try:
            run = sc_running(proc)
            if run and not was:
                log("스타크래프트 감지됨."); known = list_reps(autosave); active = rec.start()
            if run:
                if not rec._recording():
                    if active: log("녹화 스트림이 끊겨 자동으로 다시 시작합니다.")
                    active = rec.start()
                    if not active:                       # 재시작이 안 붙음 → 누적되면 인코더 문제로 판단
                        enc_fail += 1
                        if enc_fail >= 2 and not _enc_is_software():
                            _force_software_encoder("녹화가 연달아 실패했어요 — GPU 인코더(NVENC) 문제로 보고 "
                                                    "소프트웨어(CPU) 인코더로 전환합니다. 화질은 그대로예요.")
                            rec.verified = False; active = rec.start()
                cur = list_reps(autosave); new = [f for f in cur if f not in known]
                if new:
                    newest = max(new, key=lambda f: cur[f])
                    log(f"한 판 종료 감지: {os.path.basename(newest)}")
                    time.sleep(1.5)
                    vid = rec.stop(); active = False
                    threading.Thread(target=_dispatch, args=(vid, newest), daemon=True).start()
                    known = cur
                    if sc_running(proc): active = rec.start()
            if not run and was:
                log("스타크래프트 종료됨.")
                vid = rec.stop(); active = False; rec.verified = False
                cur = list_reps(autosave); new = [f for f in cur if f not in known]
                if vid and new:
                    newest = max(new, key=lambda f: cur[f])
                    threading.Thread(target=_dispatch, args=(vid, newest), daemon=True).start()
                elif vid and os.path.isfile(vid):
                    # 리플레이가 없으면(메뉴·대기 화면 등) 게임이 아니므로 저장하지 않고 폐기 — 용량 낭비 방지
                    log(f"  리플레이가 없는 녹화({rec.last_seconds:.0f}초)는 게임이 아니라 저장하지 않고 버립니다.")
                    try: os.remove(vid)
                    except OSError: pass
                known = cur; log("대기 상태.")
            # 웹 표시용 실시간 상태 갱신
            if run and rec._recording():
                enc_fail = 0                              # 정상 녹화 중이면 실패 카운터 초기화
                _wf, _wfg, _wmin = sc_window_state(proc)
                REC_STATE.update(rec=True, text=("녹화 중 — 게임 최소화됨" if _wmin else "녹화 중"))
            elif run:
                REC_STATE.update(rec=False, text="스타크래프트 감지됨")
            else:
                REC_STATE.update(rec=False, text="대기 중 — 스타를 켜면 자동 시작")
            if CFG.get('mode') == 'recorder' or (CFG.get('cloud') or {}).get('function_url'): _flush_pending()
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
        _MUTEX = ctypes.windll.kernel32.CreateMutexW(None, False, "ENCORE_Recorder_SingleInstance")
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
            winreg.SetValueEx(key, "ENCORE", 0, winreg.REG_SZ, cmd)
            log("윈도우 시작 시 자동 실행 등록됨 (끄려면 config.json 의 autostart 를 false 로)")
        else:
            try: winreg.DeleteValue(key, "ENCORE")
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
        v, _ = winreg.QueryValueEx(key, "ENCORE"); winreg.CloseKey(key)
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
    """아주 작은 상태창. 평소엔 상태만, 필요할 때만 설정·로그를 펼친다."""
    import tkinter as tk
    import tkinter.font as _tkfont
    BG="#0E1117"; SURF="#161B25"; INK="#EAEDF3"; INK2="#C5CAD3"; DIM="#8B93A3"; FAINT="#5B6373"
    JADE="#4F8CFF"; JADE2="#73A6FF"; REC="#FF5D52"; AMB="#E7A73F"; LINE="#202736"; LINE2="#2C3445"
    PANEL="#0B0E14"
    W = 340
    root = tk.Tk(); root.title("ENCORE"); root.configure(bg=BG)
    try: root.iconphoto(True, tk.PhotoImage(data=_ENCORE_ICON))
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
    BASE_H, SET_H, LOG_H = 182, 262, 196
    root.geometry(f"{W}x{BASE_H}"); root.resizable(False, True)
    st = {"log": False, "settings": False}

    # === 헤더: 로고+ENCORE (좌) · 클라우드 배지 (우) ===
    head = tk.Frame(root, bg=BG); head.pack(fill="x", padx=14, pady=(11,0))
    mk = tk.Canvas(head, width=20, height=15, bg=BG, highlightthickness=0); mk.pack(side="left", pady=(1,0))
    mk.create_rectangle(0,9,4,15, fill=INK, outline=""); mk.create_rectangle(7,4,11,15, fill=INK, outline=""); mk.create_rectangle(15,0,19,15, fill=JADE2, outline="")
    tk.Label(head, text="ENCORE", bg=BG, fg=INK, font=(LAT,12,"bold")).pack(side="left", padx=(7,0))
    _cs = cloud_state()
    _cmap = {"cloud": (JADE2, "☁ 클라우드"), "readonly": (AMB, "⚠ 키 필요"), "local": (DIM, "● 로컬")}
    _cc, _ct = _cmap[_cs]
    tk.Label(head, text=_ct, bg=SURF, fg=_cc, font=(KOR,9,"bold"), padx=8, pady=2).pack(side="right")

    # === 상태: 점 + 상태(한 줄) + 보조(안내 · 경기 N) ===
    midf = tk.Frame(root, bg=BG); midf.pack(fill="x", padx=14, pady=(8,0))
    dot = tk.Canvas(midf, width=11, height=11, bg=BG, highlightthickness=0); dot.pack(side="left", pady=(5,0))
    did = dot.create_oval(1,1,10,10, fill=FAINT, outline="")
    stx = tk.Frame(midf, bg=BG); stx.pack(side="left", padx=(9,0))
    status_lbl = tk.Label(stx, text="시작 중…", bg=BG, fg=INK, font=(KOR,15,"bold"), anchor="w"); status_lbl.pack(anchor="w")
    sub_lbl = tk.Label(stx, text="", bg=BG, fg=DIM, font=(KOR,9), anchor="w"); sub_lbl.pack(anchor="w")

    # === 로그 패널 (접이식) ===
    logwrap = tk.Frame(root, bg=BG)
    errbar = tk.Label(logwrap, text="", bg="#3A1E18", fg="#ffb4a6", font=(KOR,9), anchor="w",
                      padx=10, pady=6, justify="left", wraplength=W-40)
    logtxt = tk.Text(logwrap, bg="#0A0C10", fg=DIM, font=(MON,9), bd=0, padx=10, pady=8,
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
    _sbe = sb_enabled()
    def do_sync():
        set_log(True); threading.Thread(target=lambda: sync_existing_to_cloud(), daemon=True).start()
    def do_reanalyze():
        set_log(True); threading.Thread(target=lambda: reanalyze_all(), daemon=True).start()
    def _save_cfg():
        try: json.dump(cfg, open(CONFIG_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        except Exception as e: log(f"설정 저장 실패: {e}")

    # === 버튼 헬퍼 ===
    def btn(parent, text, cmd, primary=False, small=False):
        base = JADE if primary else "#1B212D"; hov = JADE2 if primary else "#262C36"; fg = "#FFFFFF" if primary else INK
        bord = JADE if primary else LINE2
        px, py, fs = (12, 5, 9) if small else (15, 8, 10)
        b = tk.Label(parent, text=text, bg=base, fg=fg, font=(KOR,fs,"bold"), padx=px, pady=py, cursor="hand2",
                     highlightthickness=1, highlightbackground=bord, highlightcolor=bord)
        b.bind("<Button-1>", lambda e: cmd())
        b.bind("<Enter>", lambda e: b.config(bg=hov)); b.bind("<Leave>", lambda e: b.config(bg=base))
        return b
    def link(parent, text, cmd, color=DIM):
        l = tk.Label(parent, text=text, bg=BG, fg=color, font=(KOR,9,"bold"), cursor="hand2")
        l.bind("<Button-1>", lambda e: cmd())
        l.bind("<Enter>", lambda e: l.config(fg=INK)); l.bind("<Leave>", lambda e: l.config(fg=color))
        return l

    # === 녹화 설정 패널 (접이식) ===
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
        om.config(bg="#1B212D", fg=INK, font=(KOR,9), activebackground="#262C36", activeforeground=INK,
                  relief="flat", bd=0, highlightthickness=1, highlightbackground=LINE2, anchor="w", padx=10, pady=4, cursor="hand2")
        try: om["menu"].config(bg=SURF, fg=INK, activebackground=JADE, activeforeground="#fff", font=(KOR,9), bd=0, activeborderwidth=0)
        except Exception: pass
        om.pack(side="left", fill="x", expand=True)
    opt_row("화질", SCALE_OPTS, "scale")
    opt_row("인코더", ENC_OPTS, "encoder")
    opt_row("캡처", CAP_OPTS, "capture")
    opt_row("모니터", MON_OPTS, "output_idx")
    tk.Label(optwrap, text="기본값(자동)이 최상 화질 — GPU로 게임 끊김 없이 녹화합니다", bg=PANEL, fg=DIM,
             font=(KOR,8), wraplength=W-48, justify="left").pack(anchor="w", padx=14, pady=(5,9))
    if _sbe:
        tk.Frame(optwrap, bg=LINE, height=1).pack(fill="x", padx=14, pady=(0,8))
        mrow = tk.Frame(optwrap, bg=PANEL); mrow.pack(fill="x", padx=14, pady=(0,11))
        tk.Label(mrow, text="유지보수", bg=PANEL, fg=DIM, font=(KOR,8), anchor="w").pack(side="left")
        btn(mrow, "재분석", do_reanalyze, small=True).pack(side="right")
        btn(mrow, "업로드", do_sync, small=True).pack(side="right", padx=(0,7))

    # === 패널 토글 + 리사이즈 ===
    def _resize():
        h = BASE_H + (SET_H if st["settings"] else 0) + (LOG_H if st["log"] else 0)
        root.geometry(f"{W}x{h}")
    def set_log(open_):
        if open_ and st["settings"]: set_settings(False)
        st["log"] = open_
        if open_:
            logwrap.pack(fill="both", expand=True, padx=11, pady=(0,7))
            if LAST_ERR.get("msg"): errbar.config(text="⚠ " + LAST_ERR["msg"]); errbar.pack(fill="x", pady=(0,5))
            else: errbar.pack_forget()
            logtxt.pack(fill="both", expand=True); logtog.config(text="로그 ▴")
        else:
            logwrap.pack_forget(); logtog.config(text="로그 ▾")
        _resize()
    def set_settings(open_):
        if open_ and st["log"]: set_log(False)
        st["settings"] = open_
        if open_: optwrap.pack(fill="x", padx=12, pady=(2,2)); settog.config(text="⚙ 설정 ▴", fg=JADE)
        else: optwrap.pack_forget(); settog.config(text="⚙ 설정", fg=DIM)
        _resize()
    def toggle_log(): set_log(not st["log"])
    def toggle_settings(): set_settings(not st["settings"])

    # === 주요 액션: 갤러리 (강조) + 폴더 열기 ===
    tk.Frame(root, bg=LINE, height=1).pack(fill="x", padx=14, pady=(8,0))
    acts = tk.Frame(root, bg=BG); acts.pack(fill="x", padx=13, pady=(8,0))
    btn(acts, "갤러리", open_gallery, primary=True).pack(side="left", fill="x", expand=True)
    btn(acts, "폴더 열기", open_folder).pack(side="left", padx=(7,0))

    # === 푸터 (토글 + 종료) ===
    foot = tk.Frame(root, bg=BG); foot.pack(side="bottom", fill="x", padx=15, pady=(8,10))
    settog = link(foot, "⚙ 설정", toggle_settings, DIM); settog.pack(side="left")
    logtog = link(foot, "로그 ▾", toggle_log, DIM); logtog.pack(side="left", padx=(16,0))
    link(foot, "종료", do_quit, DIM).pack(side="right")
    root.protocol("WM_DELETE_WINDOW", do_quit)

    def _prep_and_run():
        global FFMPEG, SCREP
        try:
            if not FFMPEG: FFMPEG = ensure_ffmpeg()
            if not SCREP: SCREP = ensure_screp()
        except Exception as e:
            log(f"도구 준비 중 문제: {e}")
        if not FFMPEG:
            log("⚠ ffmpeg 준비 실패 — 인터넷 연결 확인 후 다시 실행해 주세요."); return
        try: recover_orphan_clips()
        except Exception as e: log(f"미처리 영상 복구 건너뜀: {e}")
        try: rebuild_db_from_recordings()
        except Exception as e: log(f"폴더 복구 건너뜀: {e}")
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
            dot.itemconfig(did, fill=REC); status_lbl.config(text="녹화 중", fg=REC); sub = "게임 화면 녹화 중"
        elif REC_STATE.get("ready"):
            dot.itemconfig(did, fill=JADE); status_lbl.config(text="대기 중", fg=INK); sub = "스타 켜면 자동 녹화"
        else:
            dot.itemconfig(did, fill=AMB); status_lbl.config(text="준비 중…", fg=INK); sub = "최초 실행 — 도구 준비 중 (1~2분)"
        try:
            n = count_matches()
            if n: sub = f"{sub} · 경기 {n}"
        except Exception: pass
        sub_lbl.config(text=sub)
        if LAST_ERR.get("msg") and (time.time() - LAST_ERR.get("t", 0) < 8):
            if not st["log"]: set_log(True)
            else: errbar.config(text="⚠ " + LAST_ERR["msg"])
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
    print("  ENCORE 상태 점검")
    print("=" * 50)
    print(f"  데이터 폴더 : {DATA_DIR}")
    print(f"  리플레이  : {CFG.get('replay_autosave_dir') or '(없음)'}")
    try:
        _c = db(); _n = _c.execute("SELECT COUNT(*) FROM matches").fetchone()[0]; _c.close()
        print(f"  로컬 경기  : {_n}개 (matches.db)")
    except Exception: pass
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
    global FFMPEG, SCREP, CFG
    cfg = load_or_make_config(); CFG = cfg; init_db()
    try: _apply_autostart(cfg)
    except Exception: pass
    if "--sync-existing" in sys.argv or cfg.get("mode") == "sync":
        try: SCREP = ensure_screp()
        except Exception: pass
        sync_existing_to_cloud(); 
        try: input("\n끝났어요. 엔터로 종료...")
        except Exception: pass
        return
    if "--status" in sys.argv or "--check" in sys.argv:
        _print_status()
        try: input("\n엔터로 종료...")
        except Exception: pass
        return
    if "--rebuild-db" in sys.argv or cfg.get("mode") == "rebuild":
        try: SCREP = ensure_screp()
        except Exception: pass
        try: FFMPEG = ensure_ffmpeg()
        except Exception: pass
        n = rebuild_db_from_recordings()
        print(f"\n복구 완료: {n}개 경기를 DB에 추가했어요.")
        try: input("엔터로 종료...")
        except Exception: pass
        return
    # 이미 실행 중이면(자동 실행 + 수동 실행 겹침) 갤러리만 열고 종료
    if not _single_instance():
        try: open_app((cfg.get("gallery_url") or "https://encorestar.netlify.app/").rstrip("/"))
        except Exception: pass
        return
    try: _LOGFILE["p"] = os.path.join(DATA_DIR, "recorder.log")
    except Exception: pass
    mode = cfg.get("mode", "all")
    use_gui = (mode == "all" and sys.platform == "win32" and cfg.get("ui", "window") != "console")
    print("=" * 56); print(f"  스타크래프트 자동 녹화/아카이브 — 모드: {mode}"); print("=" * 56)
    _cst = cloud_state()
    if _cst == "cloud":
        log(f"☁ 클라우드 ON — Supabase({_sb_base()}) 에 저장·공유됩니다.")
    elif _cst == "readonly":
        log("⚠ 클라우드 읽기전용 — config.json 의 supabase.service_key 가 비어있어요. 채우고 재시작하면 업로드가 켜져요.")
    else:
        log("● 로컬 모드 — 이 PC에만 저장됩니다. (config.json 의 supabase 를 채우면 클라우드 ON)")
    if mode in ("all", "recorder"):
        log(f"리플레이 폴더: {cfg['replay_autosave_dir']}")
        if not os.path.isdir(cfg["replay_autosave_dir"]):
            log("⚠ 리플레이 폴더를 못 찾았어요. 스타에서 리플레이를 한 번 저장하면 폴더가 생깁니다.")
        if not use_gui:               # GUI면 창부터 띄우고 백그라운드에서 받음(첫 실행이 멈춘 듯 안 보이게)
            FFMPEG = ensure_ffmpeg()
            if not FFMPEG:
                _safe_input("\nffmpeg가 없어 녹화를 할 수 없어요. 엔터로 종료..."); return
    cloud_on = bool((cfg.get("cloud") or {}).get("function_url"))
    if (mode in ("all", "server") or cloud_on) and not use_gui:
        SCREP = ensure_screp()        # 클라우드 모드: 클라이언트가 리플레이를 직접 분석
        if not FFMPEG: FFMPEG = ensure_ffmpeg()
    port = cfg["port"]; url = (cfg.get("gallery_url") or "https://encorestar.netlify.app/").rstrip("/")
    if cloud_on:
        log("클라우드 모드: 영상은 R2로, 메타+분석은 Supabase 로 직접 업로드합니다.")
        g = cfg.get("gallery_url") or ""
        if g:
            log(f"갤러리 → {g}")
            try: open_app(g)
            except Exception: pass
        print("-" * 56); recorder_loop(cfg); return
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
