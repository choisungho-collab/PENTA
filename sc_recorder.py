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
import sqlite3, secrets, base64, tempfile
from collections import Counter, defaultdict

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
        print(f"[setup] Installing Python packages: {', '.join(need)} …")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", *need])
        except Exception as e:
            print("[!] Auto-install of packages failed. Please run it manually:")
            print(f"    {sys.executable} -m pip install {' '.join(need)}")
            print("Details:", e); _safe_input("\nPress Enter to exit..."); sys.exit(1)
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
_ENCORE_ICON = "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"
_SCENE_IDLE_B64 = "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TSJNs61lTWSKwnqBIXPrLSPayGhHIUHkcHu3gjcvhRqIAicg1IW0Um3a2GLmYSEUniBys7ZwHlit61CRVMCBaKppz2zlwGAagJHR/tESROpCK6FFg40u3QXk8QKiCrrS4oJ7ntm35Hi5wq4+USisHfc86MpXiBIsXWbc/NiR2YGT7EGuQGMwMjLaV0RRMrzza/uufZv0McuGGwTkS8wmWolszdAWXuzEfqhDGprtAPNjR7p62l0rzQ4bRvxmgxMDBqP9S7ai7AcFJ/rd+zcgClXO51qxo2DSSSOOFGMPicaic7Zf+5ofO8JKUzS+6Dlr3xaddALGMDgZoFoePOUMmyxGWyf9Fzl8HyMHy1YL+WsIcatAk73cOpybwKTIBS2bO7lc2dT2n/nxI3G5C2qKZbdhSC0wzLstbWOcvMaw+bQDDHZgH8oUW1HuB+m/4Mg7yiSyw2tXeSJ87dMLRGdlgpuRKCbPSmWQo+NHtVMJiR4gwTc6INltjb/ctnubd0A7ObAPRUbv4YYcOyD9l31h28wkilcXSXQo8a5M7rgD6NgxvQEqdHUhwQlfFSPqyim7aYadtAu2ubA6YKA13YWjW/2EZgdONLG+A896/zEJIqHfSmKvRcyPH+UBSCyvrSlW4ZTC76RhDyXqQ9ct2ZGT3ZhZK2bddWEBq6sGhgXu+LzcN66HP7HdcuF4z2+fzfafmS7HD1v+rHeLScjB0fFjFPkMQkGkAANtZYo2D8455yg0dHVKD6i8dsL/D9KfWHM0Ypjhy2OQY3vXtwkymmb58Ki9U+0urIu2ETwWWg0YrZBJCk9KGICy2BB2hLb/IDAiqTqIxpwpKsT7G61BYzDaYCG7LuQw6b/bSMxSj5t236xJOIj1vW6qVRA5RK0JUX0irjZ020RbThlxZKhgwGC0uFBYxorSaOcpxgbf/buDB56x3JW1aGto0NCzxQ08eTtl0cfNUMGAwchW90ZrxwYnQlch5Hjjbqau/5pLNAb0qArqV5TChFApDBUMGIyMjNaGDY6rDp3GkEp4KILfDZXhlNMkTFEwYDAyMto0eKAk3IhKKsFCp9K3GyQYMBgZGW2i9hAjhCuahVCtG+R3MjwwYDAyMtoahEgkP0ZJf2VvAwMDBiMjo20HifgTxhxuZMBgZGS0XwDDaNdoZrfAyMjIyMiAwcjIyMjIgMHIyMjIyIDByMjIyMiAwcjIyMjIgMHIyMjIyIDByMjIyMiAwcjIyMjIgMHIyMjIaB10wJqoGhkZGRmZxmBkZGRkZMBgZGRkZGTAYGRkZGRkwGBkZGRkZMBgZGRkZGTAYGRkZGRkwGBkZGRkZMBgZGRkZGTAYGRkZGRkwGBkZGRkZMBgZGRkZGTAYGRkZGRkwGBkZGRkZMBgZGRkZGTAYGRkZGRkwGBkZGRktMv0/4DqCJFlO+kiAAAAAElFTkSuQmCC"
_SCENE_WARM_B64 = "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"
FPS_GAME   = 23.81
REC_STATE  = {"rec": False, "text": "Idle", "game": None}   # live recording status (for web display)
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
        print(f"[migrate] Moved your old data to {DATA_DIR}.")
except Exception: pass
FFMPEG = None
SCREP  = None
CFG    = {}

import queue as _queue
GUI_Q = _queue.Queue(maxsize=4000)
REC_STATE = {"recording": False, "encoder": "", "ready": False, "upload_pct": None}
LAST_ERR = {"msg": "", "t": 0.0}
UP_DONE = {"t": 0.0, "shown": 0.0}
_LOGFILE = {"p": None}
def log(m):
    line = f"[{datetime.datetime.now():%H:%M:%S}] {m}"
    try: print(line, flush=True)
    except Exception: pass
    s = str(m)
    if any(k in s for k in ("Error", "error", "Failed", "failed", "Traceback", "Exception")) and ("restart" not in s.lower()):
        LAST_ERR["msg"] = s[:240]; LAST_ERR["t"] = time.time()
    if "Recording started" in s: REC_STATE["recording"] = True
    elif ("Recording stopped" in s) or ("StarCraft closed" in s) or ("Idle." in s): REC_STATE["recording"] = False
    if "Ready. Launch StarCraft" in s: REC_STATE["ready"] = True
    if s.startswith("Encoder:"): REC_STATE["encoder"] = s.split("Encoder:", 1)[1].strip()
    if ("Uploaded" in s) and ("\u2713" in s): UP_DONE["t"] = time.time()
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
        log(f"Config auto-created → {CONFIG_PATH}")
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
        log("Preparing audio engine (pyaudiowpatch, first run only)…")
        _run([sys.executable, "-m", "pip", "install", "-q", "pyaudiowpatch", "--break-system-packages"], timeout=300)
        import pyaudiowpatch  # noqa
        log("Audio engine ready.")
        return True
    except Exception as e:
        log(f"  (audio) pyaudiowpatch auto-install failed → silent recording. Manual: pip install pyaudiowpatch ({e})")
        return False

def ensure_ffmpeg():
    local = os.path.join(HERE, "ffmpeg.exe")
    if os.path.isfile(local): return local
    found = shutil.which("ffmpeg")
    if found: return found
    log("Downloading ffmpeg… (~90MB, first run only, 1-2 min)")
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
            log(f"ffmpeg ready. (source: {label})")
            return local
        except Exception as e:
            log(f"    {label} failed: {e} → trying next source")
    log("[!] All ffmpeg auto-downloads failed. Please download it manually:")
    log("    1) Download https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip")
    log("    2) Unzip it and find  bin\\ffmpeg.exe  inside")
    log(f"    3) Copy it into this folder:  {HERE}")
    log("    4) Run START.bat again")
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
            log("screp ready (map/race/APM/result shown in the gallery).")
            return local
        raise RuntimeError("Download failed (temporary network/GitHub error) — re-run shortly and it retries automatically")
    except Exception as e:
        log(f"(skipping screp auto-install — video is fine, only metadata hidden: {e})")
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
def _coach_race(race, units):
    """Race letter (P/T/Z) from screp ShortName; unit-based fallback for Random/unknown."""
    r = (race or "")[:1].upper()
    if r in ("P", "T", "Z"): return r
    names = " ".join(str(u) for u in (units or []))
    if any(u in names for u in ("Drone", "Zergling", "Hatchery", "Overlord", "Hydralisk", "Mutalisk", "Sunken")): return "Z"
    if any(u in names for u in ("Probe", "Zealot", "Pylon", "Dragoon", "Gateway", "Nexus", "Photon")): return "P"
    if any(u in names for u in ("SCV", "Marine", "Barracks", "Supply Depot", "Command Center", "Bunker")): return "T"
    return "P"


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
class _ProgressReader:
    """requests에 파일을 스트리밍하며 read마다 진행률 콜백. __len__로 Content-Length 노출(문서 §7)."""
    def __init__(self, f, total, cb): self._f=f; self._total=total; self._cb=cb; self._sent=0
    def read(self, n=-1):
        chunk=self._f.read(n)
        if chunk:
            self._sent+=len(chunk)
            try: self._cb(self._sent, self._total)
            except Exception: pass
        return chunk
    def __len__(self): return self._total
def _up_progress(sent, total):
    try: REC_STATE["upload_pct"]=int(sent*100/total) if total else 0
    except Exception: pass
def sb_upload(local, path, ctype, on_progress=None):
    """Supabase Storage 업로드 → 공개 URL (버킷이 public 이어야 함). on_progress(sent,total) 진행률 콜백."""
    import requests
    base = _sb_base(); bk = _sb_bucket(); k = _sb_key(write=True); total = os.path.getsize(local)
    with open(local, "rb") as f:
        body = _ProgressReader(f, total, on_progress) if on_progress else f
        r = requests.post("%s/storage/v1/object/%s/%s" % (base, bk, path), data=body,
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
def sb_get_matches(limit=24, offset=0, cols="*"):
    return [_sb_norm(x) for x in _sb_get("matches?select=%s&order=uploaded.desc&limit=%d&offset=%d" % (cols, limit, offset)).json()]
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
            lg("⚠ Supabase service_role key is empty → put it in supabase.service_key in config.json and restart.")
        else:
            lg("No Supabase config. Fill in supabase in config.json first.")
        return (0, 0, 0)
    recover_orphan_clips(lg)         # 게임 직후 종료 등으로 ingest 전에 멈춘 평면 영상 먼저 복구
    rebuild_db_from_recordings(lg)   # 폴더엔 있는데 DB엔 없는 경기 먼저 복구
    c = db()
    try: rows = c.execute("SELECT * FROM matches ORDER BY id ASC").fetchall()
    finally: c.close()
    lg(f"Found {len(rows)} existing games — starting upload to Supabase…")
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
            lg(f"  · skipped (no video file): {d.get('map') or mid}"); skipped += 1; continue
        tlocal = os.path.join(UPLOAD_DIR, d.get("thumb")) if d.get("thumb") else None
        rlocal = os.path.join(UPLOAD_DIR, d.get("replay")) if d.get("replay") else None
        try:
            lg(f"  · uploading: {d.get('map') or mid} ({(d.get('video_size') or 0)/1048576:.0f}MB)…")
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
            done += 1; lg(f"    ✓ done: {d.get('map') or mid}")
        except Exception as e:
            failed += 1; lg(f"    ✗ failed({mid}): {e}")
    lg(f"Existing-game upload done — completed {done} · skipped {skipped} · failed {failed}")
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
        lg("✗ Can't reanalyze without screp."); return 0
    if not sb_writable():
        lg("✗ No cloud write permission (check service_key)."); return 0
    if not sb_cfg().get("service_key"):
        lg("⚠ No service_key — updating existing games may be blocked by RLS. Fill supabase.service_key in config.json to be safe.")
    try:
        matches = sb_get_matches(limit=100000, cols="id,replay,map")  # analysis 통째 수신 방지(어차피 새로 만들어 덮어씀)
    except Exception as e:
        lg(f"✗ Couldn't load the game list: {e}"); return 0
    lg(f"Reanalyzing {len(matches)} existing games…")
    done = failed = skipped = 0
    for m in matches:
        mid = m.get("id")
        if not mid: continue
        rep = os.path.join(UPLOAD_DIR, mid, "replay.rep")
        tmp = None
        if not os.path.isfile(rep):
            rurl = _media_url(m.get("replay")) if m.get("replay") else None
            if not rurl:
                skipped += 1; lg(f"  · skipped (no replay): {m.get('map') or mid}"); continue
            try:
                import requests, tempfile
                rr = requests.get(rurl, timeout=120); rr.raise_for_status()
                tmp = tempfile.mktemp(suffix=".rep")
                with open(tmp, "wb") as f: f.write(rr.content)
                rep = tmp
            except Exception as e:
                failed += 1; lg(f"  · failed to fetch .rep ({mid}): {e}"); continue
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
            done += 1; lg(f"  · reanalyzed ✓ {meta.get('map') or mid}")
        except Exception as e:
            failed += 1; lg(f"  · reanalysis failed({mid}): {e}")
        finally:
            if tmp:
                try: os.remove(tmp)
                except OSError: pass
    lg(f"✓ Reanalysis done — updated {done} · skipped {skipped} · failed {failed}")
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
                        lg(f"  · folder move failed({gid}): {e}"); continue
            video = os.path.join(d, "game.mp4"); rep = os.path.join(d, "replay.rep"); thumb = os.path.join(d, "thumb.jpg")
            try: size = os.path.getsize(video)
            except Exception: size = 0
            meta = {}
            if os.path.isfile(rep) and SCREP:
                try: meta = parse_rep(rep)
                except Exception as e: lg(f"  · replay analysis failed({gid}): {e}")
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
                lg(f"  · recovered: {meta.get('map') or gid} ({size/1048576:.0f}MB)")
            except Exception as e:
                lg(f"  · DB recovery failed({gid}): {e}")
    if found:
        lg(f"Folder recovery — found {found} · added {added} · moved {moved}")
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
        lg("There are pending videos but the AutoSave replay folder wasn't found — check replay_autosave_dir in config.json.")
        return 0
    lg(f"Found {len(cand)} pending videos — matching them with replays…")
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
            lg(f"  · held (no matching replay): clip_{stamp}"); continue
        used.add(best)
        lg(f"  · recovered: clip_{stamp}  ←  {os.path.basename(best)}")
        try:
            ingest(vpath, best, uploader=CFG.get("username") or None)
            recovered += 1
        except Exception as e:
            lg(f"  · recovery failed(clip_{stamp}): {e}")
    if recovered: lg(f"✓ Pending-video recovery done — {recovered} item(s)")
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
        log("Installing boto3…")
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
    log(f"✓ Registered: {meta.get('map') or 'game'} ({(size or 0)/1048576:.0f}MB) by {uploader or saver or '?'}{tag}")

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
            log("Trimmed the lobby/loading intro so playback starts at the countdown")
        else:
            try: os.remove(tmp)
            except OSError: pass
    except Exception as e:
        log(f"Skipped video trim (kept original): {e}")

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
        log("Video is empty, skipping registration."); return
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
        log(f"Recording {secs} has no replay, so it isn't a game — discarding without saving.")
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
        log(f"Game too short ({meta.get('length')}) — discarding without saving; looks like it ended early.")
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
            log(f"Analysis failed (continuing): {e}")
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
                if _clips: log(f"  Created and uploaded {len(_clips)} highlight clips")
        except Exception as _e:
            log(f"Skipped clip creation: {_e}")
        try:
            video_url = sb_upload(video_path, f"videos/{gid}.mp4", "video/mp4", on_progress=_up_progress); REC_STATE["upload_pct"]=None
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
            log(f"☁ Supabase registered: {meta.get('map') or 'game'} ({(size or 0)/1048576:.0f}MB) by {uploader or saver or '?'}")
            return
        except Exception as e:
            REC_STATE["upload_pct"]=None
            log(f"Supabase upload/save failed: {e} — keeping it locally.")
    if r2_enabled():
        tmp_thumb = os.path.join(base, "thumb.jpg"); has_thumb = make_thumb(video_path, tmp_thumb)
        try:
            video_ref = r2_upload(video_path, f"videos/{gid}.mp4", "video/mp4")
            thumb_ref = r2_upload(tmp_thumb, f"thumbs/{gid}.jpg", "image/jpeg") if has_thumb else None
        except Exception as e:
            log(f"R2 upload failed: {e}"); return
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
def _media_url(v):
    if not v: return ""
    return v if v.startswith("http") else "/media/" + v


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
    if reason: log("[stability] " + reason)
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
                if errs: log("  NVENC error: " + "  /  ".join(errs[-2:]))
                return False
            return True
        except Exception as e:
            log(f"  NVENC test exception: {e}")
            return False
    if pref == "nvenc":
        use_nvenc = True
    elif pref in ("x264", "libx264", "software", "cpu"):
        use_nvenc = False
    else:  # auto — 실제 인코딩 테스트
        use_nvenc = ("h264_nvenc" in have) and _nvenc_ok()
        if ("h264_nvenc" in have) and not use_nvenc:
            log("  NVENC is listed but failed actual encoding → switching to software (libx264)")
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
    log(f"Encoder: {name}")
    try: REC_STATE["enc_short"] = "NVENC" if use_nvenc else "x264"
    except Exception: pass
    return _ENC_CACHE

def _reset_enc_cache():
    """인코더 설정 변경 시 캐시를 비워 다음 녹화부터 재선택 + GUI 칩 재감지 유도."""
    global _ENC_CACHE, _ENC_IS_SW
    _ENC_CACHE = None; _ENC_IS_SW = False
    try: REC_STATE.pop("enc_short", None); REC_STATE.pop("res_short", None)
    except Exception: pass


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
                log(f"  (audio) pyaudiowpatch not installed → silent recording. Install: pip install pyaudiowpatch ({e})"); return
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
                    if dev is None: raise RuntimeError("WASAPI loopback device not found")
                ch = int(dev.get("maxInputChannels") or 2) or 2
                rate = int(dev.get("defaultSampleRate") or 48000) or 48000
                wf = wave.open(box["path"], "wb"); wf.setnchannels(ch); wf.setsampwidth(2); wf.setframerate(rate)
                stream = p.open(format=pa.paInt16, channels=ch, rate=rate, input=True,
                                input_device_index=dev["index"], frames_per_buffer=2048)
                box["t0"] = time.time(); box["ok"] = True
                log(f"  ♪ Audio capture started ({str(dev.get('name','?'))[:26]} · {rate}Hz {ch}ch)")
                while not box["stop"].is_set():
                    try: wf.writeframes(stream.read(2048, exception_on_overflow=False))
                    except Exception: break
            except Exception as e:
                log(f"  (audio) capture failed → silent recording: {e}")
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
                self.path = out; log("■ Audio merge complete"); return out
            log("  (audio) merge result empty, using video only")
            try:
                if os.path.isfile(out): os.remove(out)
            except OSError: pass
            return vid
        except Exception as e:
            log(f"  (audio) merge failed → video only: {e}"); return vid

    def _start_wgc(self, verify=True):
        """WGC(OBS식)로 프레임을 받아 ffmpeg로 인코딩. 정지화면이어도 직전 프레임을 고정 fps로 계속 먹임(전체화면 게임도 잡힘)."""
        if "cv2" not in sys.modules:
            try: import cv2  # noqa: F401  # windows-capture가 import 시 cv2를 부르는 버전 대비(프레임은 numpy로만 처리)
            except Exception:
                import types as _t; sys.modules["cv2"] = _t.ModuleType("cv2")  # 빈 스텁 → exe에 OpenCV 없이 작동
        try:
            from windows_capture import WindowsCapture
        except ImportError:
            try:
                log("Installing WGC engine (windows-capture)…")
                _run([sys.executable, "-m", "pip", "install", "-q", "windows-capture", "--break-system-packages"], timeout=240)
                from windows_capture import WindowsCapture
            except Exception as e:
                log(f"  WGC unavailable (install failed: {e})"); return False
        try:
            import numpy as _np
        except Exception as e:
            log(f"  WGC unavailable (numpy missing: {e})"); return False
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
            if vf: log(f"  Lower software load: capture {h}p → encode {_target_height(h)}p")
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
                    log("  WGC: this OS can't disable the capture border → starting with defaults (a border may show)")
                break
            except Exception as e:
                control = None
                if _border is False:
                    log(f"  WGC failed to start with border off ({e}) → retrying with defaults")
                else:
                    log(f"  WGC failed to start: {e}"); return False
        if control is None:
            return False
        ft = threading.Thread(target=feeder, daemon=True); ft.start()
        self._wgc_control = control
        self._wgc_state = {"stop": stop_ev, "feeder": ft, "proc_box": proc_box}
        self.backend = "wgc"
        if not verify:
            log("● Recording started (WGC)"); return True
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
            log("● Recording started (WGC — capture verified)"); return True
        if ok:                                       # 파일이 아직 작으면(정적 화면) 잠깐 더 대기 후 재확인
            time.sleep(2.5)
            if _sz() >= 8000:
                log("● Recording started (WGC — capture verified)"); return True
        stop_ev.set()
        try: control.stop()
        except Exception: pass
        try: ft.join(timeout=5)
        except Exception: pass
        self.backend = "ffmpeg"; self._wgc_control = None; self._wgc_state = None
        log("  WGC capture not working (frames:{}, ffmpeg:{}, file:{}B, error:{}) → trying another method".format(
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
                        log(f"● Recording started ({'Monitor '+str(self.output_idx) if self.mode=='ddagrab' else 'gdigrab'})"); return True
            except Exception: pass
            self.verified = False
        # 1순위: WGC (auto/wgc) — 전체화면도 잡히는 OBS식 엔진
        if capmode in ("auto", "wgc"):
            try:
                if self._start_wgc(verify=True):
                    self.verified = True; self.verified_backend = "wgc"; return True
            except Exception as e:
                log(f"WGC error: {e}")
            if capmode == "wgc":
                log("  WGC failed → falling back to ddagrab/gdigrab")
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
                    log(f"● Recording started ({'Monitor '+str(idx) if mode=='ddagrab' else 'gdigrab'}) — capture verified")
                    return True
                self._kill()
            except Exception as e:
                log(f"Recording start error({mode} #{idx}): {e}"); self._kill()
        if not self.warned_black:
            self.warned_black = True
            _found, _fg, _min = sc_window_state(CFG.get("starcraft_process") or "StarCraft.exe")
            if _min:
                log("[!] StarCraft is minimized — keep the game on screen and it records normally.")
            elif _found and not _fg:
                log("[!] StarCraft is behind another window — bring the game to the front to capture it.")
                log("    • On dual monitors, set \"output_idx\" in config.json to the monitor number with the game (0/1/2)")
            else:
                log("[!] Couldn't verify screen capture (may be a black screen). Recording continues anyway.")
                log("    • Play a game first and check the video in the gallery (a still menu can be a false alarm)")
                log("    • Set \"capture\" to \"wgc\" in config.json, or run StarCraft in windowed (fullscreen) mode")
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
            log("■ Recording stopped")
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
        log("■ Recording stopped")
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
        raise RuntimeError(f"R2 PUT failed {r.status_code}")

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
    if os.path.isfile(video): log(f"↑ Uploading to cloud… ({os.path.getsize(video)/1048576:.0f}MB)")
    try:
        if _cloud_send(video, rep):
            log("✓ Uploaded to cloud"); return
        log("✗ Upload failed → queued")
    except Exception as e:
        log(f"✗ Cloud upload failed({e}) → queued")
    q = _load_pending(); q.append({"v": video, "r": rep}); _save_pending(q)

def upload_remote(video, rep):
    if not video or not os.path.isfile(video): return
    sv = CFG.get("server", {}) or {}
    log(f"↑ Uploading… ({os.path.getsize(video)/1048576:.0f}MB → {sv.get('url','')})")
    try:
        res = _post_r2(video, rep)        # R2 직접 업로드 시도
        if res is None: res = _post(video, rep)   # 서버에 R2 미설정 → 서버 경유
        if res:
            log("✓ Uploaded")
            try: os.remove(video)
            except OSError: pass
        else:
            log("✗ Upload failed → queued"); q = _load_pending(); q.append({"v": video, "r": rep}); _save_pending(q)
    except Exception as e:
        log(f"✗ Upload failed({e}) → queued"); q = _load_pending(); q.append({"v": video, "r": rep}); _save_pending(q)
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
    log("Ready. Launch StarCraft and recording starts automatically. (keep this window open)")
    while True:
        try:
            run = sc_running(proc)
            if run and not was:
                log("StarCraft detected."); known = list_reps(autosave); active = rec.start()
            if run:
                if not rec._recording():
                    if active: log("Recording stream dropped; restarting automatically.")
                    active = rec.start()
                    if not active:                       # 재시작이 안 붙음 → 누적되면 인코더 문제로 판단
                        enc_fail += 1
                        if enc_fail >= 2 and not _enc_is_software():
                            _force_software_encoder("Recording failed repeatedly — treating it as a GPU encoder (NVENC) issue and "
                                                    "switching to the software (CPU) encoder. Quality stays the same.")
                            rec.verified = False; active = rec.start()
                cur = list_reps(autosave); new = [f for f in cur if f not in known]
                if new:
                    newest = max(new, key=lambda f: cur[f])
                    log(f"Game-end detected: {os.path.basename(newest)}")
                    time.sleep(1.5)
                    vid = rec.stop(); active = False
                    threading.Thread(target=_dispatch, args=(vid, newest), daemon=True).start()
                    known = cur
                    if sc_running(proc): active = rec.start()
            if not run and was:
                log("StarCraft closed.")
                vid = rec.stop(); active = False; rec.verified = False
                cur = list_reps(autosave); new = [f for f in cur if f not in known]
                if vid and new:
                    newest = max(new, key=lambda f: cur[f])
                    threading.Thread(target=_dispatch, args=(vid, newest), daemon=True).start()
                elif vid and os.path.isfile(vid):
                    # 리플레이가 없으면(메뉴·대기 화면 등) 게임이 아니므로 저장하지 않고 폐기 — 용량 낭비 방지
                    log(f"  Recording with no replay ({rec.last_seconds:.0f}s) isn't a game — discarding without saving.")
                    try: os.remove(vid)
                    except OSError: pass
                known = cur; log("Idle.")
            # 웹 표시용 실시간 상태 갱신
            if run and rec._recording():
                enc_fail = 0                              # 정상 녹화 중이면 실패 카운터 초기화
                _wf, _wfg, _wmin = sc_window_state(proc)
                REC_STATE.update(rec=True, text=("Recording — game minimized" if _wmin else "Recording"))
            elif run:
                REC_STATE.update(rec=False, text="StarCraft detected")
            else:
                REC_STATE.update(rec=False, text="Idle — launch StarCraft to start")
            if CFG.get('mode') == 'recorder' or (CFG.get('cloud') or {}).get('function_url'): _flush_pending()
            was = run; time.sleep(poll)
        except KeyboardInterrupt:
            log("Shutting down."); rec.stop(); break
        except Exception:
            log("Error:\n" + traceback.format_exc()); time.sleep(poll)

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
            log("Registered to run at Windows startup (set autostart to false in config.json to disable)")
        else:
            try: winreg.DeleteValue(key, "ENCORE")
            except FileNotFoundError: pass
        winreg.CloseKey(key)
        return True
    except Exception as e:
        log(f"Skipped autostart setup: {e}")
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

# ---- bundled brand font: SUIT (Latin subset, ~13KB/weight) — matches ENCORE web ----
_SUIT_REG_B64  = "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AHIAUwB1AG4AUwB1AG4AOwAgAEsAbwByAGUAYQBuACAARwBsAHkAcABoAHMAIABmAHIAbwBtACAAUwBvAHUAcgBjAGUAIABIAGEAbgAgAFMAYQBuAHMAIAAoAFMAYQBuAGQAbwBsAGwAIABDAG8AbQBtAHUAbgBpAGMAYQB0AGkAbwBuAHMAOwAgAFMAbwBvAC0AeQBvAHUAbgBnACAASgBhAG4AZwAsACAASgBvAG8ALQB5AGUAbwBuACAASwBhAG4AZwApAGgAdAB0AHAAOgAvAC8AcwB1AG4ALgBmAG8ALwBzAHUAaQB0AFQAaABpAHMAIABGAG8AbgB0ACAAUwBvAGYAdAB3AGEAcgBlACAAaQBzACAAbABpAGMAZQBuAHMAZQBkACAAdQBuAGQAZQByACAAdABoAGUAIABTAEkATAAgAE8AcABlAG4AIABGAG8AbgB0ACAATABpAGMAZQBuAHMAZQAsACAAVgBlAHIAcwBpAG8AbgAgADEALgAxAC4AIABUAGgAaQBzACAARgBvAG4AdAAgAFMAbwBmAHQAdwBhAHIAZQAgAGkAcwAgAGQAaQBzAHQAcgBpAGIAdQB0AGUAZAAgAG8AbgAgAGEAbgAgACIAQQBTACAASQBTACIAIABCAEEAUwBJAFMALAAgAFcASQBUAEgATwBVAFQAIABXAEEAUgBSAEEATgBUAEkARQBTACAATwBSACAAQwBPAE4ARABJAFQASQBPAE4AUwAgAE8ARgAgAEEATgBZACAASwBJAE4ARAAsACAAZQBpAHQAaABlAHIAIABlAHgAcAByAGUAcwBzACAAbwByACAAaQBtAHAAbABpAGUAZAAuACAAUwBlAGUAIAB0AGgAZQAgAFMASQBMACAATwBwAGUAbgAgAEYAbwBuAHQAIABMAGkAYwBlAG4AcwBlACAAZgBvAHIAIAB0AGgAZQAgAHMAcABlAGMAaQBmAGkAYwAgAGwAYQBuAGcAdQBhAGcAZQAsACAAcABlAHIAbQBpAHMAcwBpAG8AbgBzACAAYQBuAGQAIABsAGkAbQBpAHQAYQB0AGkAbwBuAHMAIABnAG8AdgBlAHIAbgBpAG4AZwAgAHkAbwB1AHIAIAB1AHMAZQAgAG8AZgAgAHQAaABpAHMAIABGAG8AbgB0ACAAUwBvAGYAdAB3AGEAcgBlAC4AaAB0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AAAAAAAAAAAAAAAAAAAAAAAAAAD/4gAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAKAAAAAAAAAAD/7AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP/E/+IAAP/E/+z/9v/YAAAAAP/sAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD/9v/sAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP/sAAD/9gAAAAAAAAAAAAAAAAAAAAAAKAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP+wAAAAAAAA//YAAP/O/9gAAAAA/+wAAP/iAAAAAAAAAAAAAP/iAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/+wAAP/iAAD/7AAA//YAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD/2AAAAAAAAAAAAAAAAP/2/+L/9v/2/+L/7P/sAAD/4gAAAAAACgAAAAD/4gAA/8T/9gAA/8T/7AAA/4gAAP+c/7r/Vv/i/+z/7P/s/+z/2P/2/8T/2P/E/+wAAP/2AAAAAP/OAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD/9v/2/+L/7AAAAAAAAAAAAAAAAAAAAGQAAAAA/9gAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD/2P/iAAAAAAAA//YAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/+z/9v/2/+L/7AAA/9j/2P/YAAAAAAAAAAAAAP/YAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/+z/4v/s/87/2P+6/9j/7AAA/8QAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP/YAAAAAAAAAAD/9gAAAAAAAAAAAAAAAP/sAAAAAAAAAAAAFAAAAAD/7AAAAAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAA/+z/7P/E/9j/7P/2/9j/2P/sAAAAAAAAAAAAAP/sAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/84AAP/iAAAAAP/s/+IAAAAAAAAAAAAA/+wAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP/s/+z/zv/OAAD/9gAAAAD/2P/sAAAAAAAAAAD/7AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP/sAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP/sAAIAAgACADcAAAB4AHgANgABAAMAdgABAAIACAAEAAMACAAEAAUABAAGAAcABAAEAAgACQAIAAoACwAMAA0ADgAOAA8AEAARAAUAGQAaABMAGAAaABQAGwAZABUAFgAXABgAGQAZABoAGgAbABwAHQAeAB8AIAAgACEAIgAjABgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAASAAEAAgB3AAEAAgAFAAIAAgACAAUAAgADAAQAAgACAAIAAgAFAAIABQACAAYABwAIAAkACQAKAAsAFwADAA8ADQAPAA8ADwAMAA8ADQANABgADQANAA4ADgAPAA4ADwAOABAAEQASABMAEwAUABUAFgANAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABoAGgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAGwAbABsAGwAbABsAAAAAAAAAGQABAAAACgAuAKgAAURGTFQACAAEAAAAAP//AAkAAAABAAIAAwAEAAUABgAHAAgACWFhbHQAOHBudW0APnNpbmYARHNzMDEASnNzMTcAVHNzMTgAXnN1YnMAaHN1cHMAbnRudW0AdAAAAAEAAAAAAAEABAAAAAEAAgAGAAEABgAAAQAABgABAAcAAAEBAAYAAQAIAAABAgAAAAEAAQAAAAEAAwAAAAEABQAJABQBDAEMARoBMgFoAZ4BvAHeAAMAAAABAAgAAQDCABsAPABAAEQATABWAF4AaAByAHYAegB+AIIAhgCKAI4AkgCWAJoAngCiAKYAqgCuALIAtgC6AL4AAQAcAAEANwADAEcAQgBFAAQAUQBVAEgARgADAFIAVgBJAAQAUwBXAEoAQwAEAFQAWABLAEQAAQBMAAEATQABAE4AAQBPAAEAUAABADgAAQA5AAEAOgABADsAAQA8AAEAPQABAD4AAQA/AAEAQAABAEEAAQBlAAEAZgABAFkAAQBaAAEAgwACAAcACgAKAAAAKAAoAAEAOABBAAIARwBQAAwAWQBaABYAZQBmABgAggCCABoAAQAAAAEACAABABQAGAABAAAAAQAIAAEABgAcAAIAAQA5ADwAAAABAAAAAQAIAAIAHgAMADgAOQA6ADsAPAA9AD4APwBAAEEAWQBaAAIAAgBHAFAAAABlAGYACgABAAAAAQAIAAIAHgAMAEcASABJAEoASwBMAE0ATgBPAFAAZQBmAAIAAgA4AEEAAABZAFoACgABAAAAAQAIAAIADAADAEIAQwBEAAEAAwA4ADsAPAABAAAAAQAIAAIADgAEABwANwBFAEYAAQAEAAoAKAA4ADkAAQAAAAEACAABAAYAAQABAAEAggAA"
_SUIT_MED_B64  = "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AHIAcwBpAG8AbgAgADIALgAwADQAMAA7AEcAbAB5AHAAaABzACAAMwAuADIALgAzACAAKAAzADIANgAwACkAUwBVAEkAVAAtAE0AZQBkAGkAdQBtAFMAdQBuAFMAdQBuADsAIABLAG8AcgBlAGEAbgAgAEcAbAB5AHAAaABzACAAZgByAG8AbQAgAFMAbwB1AHIAYwBlACAASABhAG4AIABTAGEAbgBzACAAKABTAGEAbgBkAG8AbABsACAAQwBvAG0AbQB1AG4AaQBjAGEAdABpAG8AbgBzADsAIABTAG8AbwAtAHkAbwB1AG4AZwAgAEoAYQBuAGcALAAgAEoAbwBvAC0AeQBlAG8AbgAgAEsAYQBuAGcAKQBoAHQAdABwADoALwAvAHMAdQBuAC4AZgBvAC8AcwB1AGkAdABUAGgAaQBzACAARgBvAG4AdAAgAFMAbwBmAHQAdwBhAHIAZQAgAGkAcwAgAGwAaQBjAGUAbgBzAGUAZAAgAHUAbgBkAGUAcgAgAHQAaABlACAAUwBJAEwAIABPAHAAZQBuACAARgBvAG4AdAAgAEwAaQBjAGUAbgBzAGUALAAgAFYAZQByAHMAaQBvAG4AIAAxAC4AMQAuACAAVABoAGkAcwAgAEYAbwBuAHQAIABTAG8AZgB0AHcAYQByAGUAIABpAHMAIABkAGkAcwB0AHIAaQBiAHUAdABlAGQAIABvAG4AIABhAG4AIAAiAEEAUwAgAEkAUwAiACAAQgBBAFMASQBTACwAIABXAEkAVABIAE8AVQBUACAAVwBBAFIAUgBBAE4AVABJAEUAUwAgAE8AUgAgAEMATwBOAEQASQBUAEkATwBOAFMAIABPAEYAIABBAE4AWQAgAEsASQBOAEQALAAgAGUAaQB0AGgAZQByACAAZQB4AHAAcgBlAHMAcwAgAG8AcgAgAGkAbQBwAGwAaQBlAGQALgAgAFMAZQBlACAAdABoAGUAIABTAEkATAAgAE8AcABlAG4AIABGAG8AbgB0ACAATABpAGMAZQBuAHMAZQAgAGYAbwByACAAdABoAGUAIABzAHAAZQBjAGkAZgBpAGMAIABsAGEAbgBnAHUAYQBnAGUALAAgAHAAZQByAG0AaQBzAHMAaQBvAG4AcwAgAGEAbgBkACAAbABpAG0AaQB0AGEAdABpAG8AbgBzACAAZwBv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"
_SUIT_SB_B64   = "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AAAAAOKlTPIAAAAA4qVM8v/G/yYD/QNOAAAABwACAAAAAAAAA+gAAADmAAADHQBCAncAUwLfAEoC2ABUAlkASAJFAFIDZwBNAswAVAEGAFQCPAA+ArUAUwJAAFIDegBTAt0AUQNwAE0CiABTA3YATQKzAFQChgBOAoIAPwLPAFUDAwBCBEUASQLsAEIC3QBCAlAALAGxAFQCTgA3AlIASwHUACICUgA3AiwANwGkACsCTgA3AjkAUgD6AEkA9P/GAhMATwDjAEIDTABRAisASgI0ADcCVQBQAkkANwFkAEUB4wA5AYsALQIsAEsCOgAtAucAMgIqAC0COwAyAdQANQEeAEICfQAyAZMALAI6ADQCSgAzAmoAMwJVADQCVQAzAjEAQgJNADMCVQAzAvQAMgJUADMCagAzAn0AMgHiACwCagAxAmoAjAJqAEwCagBDAmoAMwJqAD4CagA+AmoAWAJqAEECagA+APYALAFrACwBcgAsAYMALAD2ACwBawAsAXIALAGDACwBEQA4ASAAJgElAF0BKgBDAzEAZwFOAGoCKwAtAe0AsQIhAEQDEgA2AaMALgGjAEIBBwA4AREAJgI1AEMCPAA2AYkAaAGIAEEBfgBBAX4AQQFuAGcBbgBBAcUAVQHFAEIBGABSARcAPwGRAEsA7gBIBDwAXAOIAC4EGABIAugASwE8AHkCbgBDAtUARAKqAGsCbwBGAm8AbALeAEoCHgA3BCIAVwPoAUUD6AB8A+gAhwPoAEAD6ADAARgAUgABAAAD3P78AAAERf/GABQD/QABAAAAAAAAAAAAAAAAAAAAiAAEA2YCWAAFAAQCigJYAAAASwKKAlgAAAFeADIBaAAAAAAAAAAAAAAAAIAAAAMAAOAgAAAAAAAAAABTVU5OAMAAICcTA9z+/AAAA9wBBAAAAAEAAAAAAc0C0gAAACAAAgAAABEA0gADAAEECQAAACoAAAADAAEECQABABoAKgADAAEECQACAA4ARAADAAEECQADADAAUgADAAEECQAEABoAKgADAAEECQAFAEIAggADAAEECQAGABoAxAADAAEECQAIAAYA3gADAAEECQAJAL4A5AADAAEECQALACQBogADAAEECQANApYBxgADAAEECQAOADQEXAADAAEECQAQAAgEkAADAAEECQARABAEmAADAAEECQEAAB4EqAADAAEECQEBABwExgADAAEECQECAB4E4gBDAG8AcAB5AHIAaQBnAGgAdAAgAKkAIAAyADAAMgAyACAAUwB1AG4ALgBTAFUASQBUACAAUwBlAG0AaQBCAG8AbABkAFIAZQBnAHUAbABhAHIAMgAuADAANAAwADsAUwBVAE4ATgA7AFMAVQBJAFQALQBTAGUAbQBpAEIAbwBsAGQAVgBlAHIAcwBpAG8AbgAgADIALgAwADQAMAA7AEcAbAB5AHAAaABzACAAMwAuADIALgAzACAAKAAzADIANgAwACkAUwBVAEkAVAAtAFMAZQBtAGkAQgBvAGwAZABTAHUAbgBTAHUAbgA7ACAASwBvAHIAZQBhAG4AIABHAGwAeQBwAGgAcwAgAGYAcgBvAG0AIABTAG8AdQByAGMAZQAgAEgAYQBuACAAUwBhAG4AcwAgACgAUwBhAG4AZABvAGwAbAAgAEMAbwBtAG0AdQBuAGkAYwBhAHQAaQBvAG4AcwA7ACAAUwBvAG8ALQB5AG8AdQBuAGcAIABKAGEAbgBnACwAIABKAG8AbwAtAHkAZQBvAG4AIABLAGEAbgBnACkAaAB0AHQAcAA6AC8ALwBzAHUAbgAuAGYAbwAvAHMAdQBpAHQAVABoAGkAcwAgAEYAbwBuAHQAIABTAG8AZgB0AHcAYQByAGUAIABpAHMAIABsAGkAYwBlAG4AcwBlAGQAIAB1AG4AZABlAHIAIAB0AGgAZQAgAFMASQBMACAATwBwAGUAbgAgAEYAbwBuAHQAIABMAGkAYwBlAG4AcwBlACwAIABWAGUAcgBzAGkAbwBuACAAMQAuADEALgAgAFQAaABpAHMAIABGAG8AbgB0ACAAUwBvAGYAdAB3AGEAcgBlACAAaQBzACAAZABpAHMAdAByAGkAYgB1AHQAZQBkACAAbwBuACAAYQBuACAAIgBBAFMAIABJAFMAIgAgAEIAQQBTAEkAUwAsACAAVwBJAFQASABPAFUAVAAgAFcAQQBSAFIAQQBOAFQASQBFAFMAIABPAFIAIABDAE8ATgBEAEkAVABJAE8ATgBTACAATwBGACAAQQBOAFkAIABLAEkATgBEACwAIABlAGkAdABoAGUAcgAgAGUAeABwAHIAZQBzAHMAIABvAHIAIABpAG0AcABsAGkAZQBkAC4AIABTAGUAZQAgAHQAaABl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AAAAAAAAAAD/sAAA//n/2P/i/+L/9v/2/+z/6wAAAAAAAAAA//b/7AAAAAD/9v/2AAAAAAAAAAAAAAAAAAAAAP9g/+z/7AAA/5L/sAAF//b/xP/E/87/2P/Y/7r/nP+m/+z/sP+9/73/nQAAAAAAAAAA/7AAAAAAAAAAAAAAAAD/sP/c/9b/7AAA/8r/xP/2AAAAAP/E/+z/7P/Y/7D/7P/EAAAAAAAAAAAAAAAAAAD/YP/iAAAAAP9+/6b/7P/s/9j/7P/K/87/2P+I/1b/Z//O/5L/s/+zAAAAAP/YAAAAAAAAAAAAAP/2AAAAAAAA/+z/7wAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/+IAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACgAAAAAAAAAA/+wAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD/xP/iAAD/x//s//b/4wAAAAD/7AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA//b/7AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD/7AAA//YAAAAAAAAAAAAAAAAAAAAAACgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD/sAAAAAAAAP/2AAD/zv/YAAAAAP/sAAD/5QAAAAAAAAAAAAD/4gAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP/sAAD/4gAA/+wAAP/2AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/9gAAAAAAAAAAAAAAAD/9v/r//b/9v/o/+z/7AAA/+IAAAAAAAoAAAAA/+IAAP/E//YAAP/E/+wAAP+IAAD/nP+6/1b/4v/s/+z/7//s/9j/9v/E/9j/xP/sAAD/9gAAAAD/zgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA//b/9v/i/+wAAAAAAAAAAAAAAAAAAABnAAAAAP/YAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/9j/4gAAAAAAAP/2AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP/s//b/9v/i/+kAAP/Y/9j/2AAAAAAAAAAAAAD/2AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP/s/+L/5f/X/97/uv/e/+wAAP/PAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD/2AAAAAAAAAAA//YAAAAAAAAAAAAAAAD/6QAAAAAAAAAAABQAAAAA//IAAAAAAAAAAAAAAAAAAP/+AAAAAAAAAAAAAP/s//L/xP/Y/+z/9v/Y/+P/7AAAAAAAAAAAAAD/8gAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP/OAAD/4gAAAAD/7P/iAAAAAAAAAAAAAP/yAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD/7P/s/8v/zgAA//YAAAAA/9j/7AAAAAAAAAAA//IAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD/7AAAAAAAAAAAAAAAAAAAAAAAAAAAAAD/8gACAAIAAgA3AAAAeAB4ADYAAQADAHYAAQACAAgABAADAAgABAAFAAQABgAHAAQABAAIAAkACAAKAAsADAANAA4ADgAPABAAEQAFABkAGgATABgAGgAUABsAGQAVABYAFwAYABkAGQAaABoAGwAcAB0AHgAfACAAIAAhACIAIwAYAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAEgABAAIAdwABAAIABQACAAIAAgAFAAIAAwAEAAIAAgACAAIABQACAAUAAgAGAAcACAAJAAkACgALABcAAwAPAA0ADwAPAA8ADAAPAA0ADQAYAA0ADQAOAA4ADwAOAA8ADgAQABEAEgATABMAFAAVABYADQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAaABoAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABsAGwAbABsAGwAbAAAAAAAAABkAAQAAAAoALgCoAAFERkxUAAgABAAAAAD//wAJAAAAAQACAAMABAAFAAYABwAIAAlhYWx0ADhwbnVtAD5zaW5mAERzczAxAEpzczE3AFRzczE4AF5zdWJzAGhzdXBzAG50bnVtAHQAAAABAAAAAAABAAQAAAABAAIABgABAAYAAAEAAAYAAQAHAAABAQAGAAEACAAAAQIAAAABAAEAAAABAAMAAAABAAUACQAUAQwBDAEaATIBaAGeAbwB3gADAAAAAQAIAAEAwgAbADwAQABEAEwAVgBeAGgAcgB2AHoAfgCCAIYAigCOAJIAlgCaAJ4AogCmAKoArgCyALYAugC+AAEAHAABADcAAwBHAEIARQAEAFEAVQBIAEYAAwBSAFYASQAEAFMAVwBKAEMABABUAFgASwBEAAEATAABAE0AAQBOAAEATwABAFAAAQA4AAEAOQABADoAAQA7AAEAPAABAD0AAQA+AAEAPwABAEAAAQBBAAEAZQABAGYAAQBZAAEAWgABAIMAAgAHAAoACgAAACgAKAABADgAQQACAEcAUAAMAFkAWgAWAGUAZgAYAIIAggAaAAEAAAABAAgAAQAUABgAAQAAAAEACAABAAYAHAACAAEAOQA8AAAAAQAAAAEACAACAB4ADAA4ADkAOgA7ADwAPQA+AD8AQABBAFkAWgACAAIARwBQAAAAZQBmAAoAAQAAAAEACAACAB4ADABHAEgASQBKAEsATABNAE4ATwBQAGUAZgACAAIAOABBAAAAWQBaAAoAAQAAAAEACAACAAwAAwBCAEMARAABAAMAOAA7ADwAAQAAAAEACAACAA4ABAAcADcARQBGAAEABAAKACgAOAA5AAEAAAABAAgAAQAGAAEAAQABAIIAAA=="
_SUIT_BOLD_B64 = "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AAAAAOKlTPIAAAAA4qVM8v/E/yMECwNOAAEABwACAAAAAAAAA+gAAADmAAADJgA/AnwAUALeAEcC3QBRAl4ARQJKAE8DZwBKAtMAUQEMAFECRQA7AsUAUAJDAE8DigBQAuYATgNzAEoCjgBQA3gASgK5AFECigBLAoQAPALUAFIDCwA/BFEARgL6AD8C6gA/AlcAKQG4AFECVQA2AlkASgHWACECWQA2AjIANgGtACoCVQA2AkIAUQEGAEoA/P/EAiAATgDsAEEDWgBQAjcASQI4ADYCXABPAlIANgFoAEQB6QA4AZoAKwI4AEoCRgAsAvYAMQI6ACwCSAAwAdwANAEoAEEChAAwAaIAKgJAADICTwAxAmsAMQJaADICWgAxAjUAQQJSADECWgAxAvsAMAJZADECawAxAoQAMAHzACoCagAwAmoAgwJqAEcCagA+AmoAMAJqADkCagA5AmoAVAJqAD0CagA5APkAKQFpACkBcAApAX8AKQD5ACkBaQApAXAAKQF/ACkBFgA1AScAIwEqAFoBMQBAAzkAZAFYAGcCMQAqAfIArgImAEQDHQA2AbAALgGwAEIBBwA2AREAIwI2AEECPAA2AZQAaAGUAEEBfgBBAX4AQQF2AGcBdgBBAdsAVQHbAEIBJQBSASQAPwGoAEsA+gBIBDwAWQOIACgEHwBFAv8ASwFGAHkCdABAAtUAQgKqAGkCewBGAnsAbALoAEYCHwAwBCUAUgPoAUED6AB5A+gAhAPoAD0D6AC+ASUAUgABAAAD3P78AAAEUf/EABMECwABAAAAAAAAAAAAAAAAAAAAiAAEA2YCvAAFAAQCigJYAAAASwKKAlgAAAFeADIBaAAAAAAAAAAAAAAAAIAAAAMAAOAgAAAAAAAAAABTVU5OAKAAICcTA9z+/AAAA9wBBAAAAAEAAAAAAc0C0gAAACAAAgAAABEA0gADAAEECQAAACoAAAADAAEECQABAAgAKgADAAEECQACAAgAMgADAAEECQADACgAOgADAAEECQAEABIAYgADAAEECQAFAEIAdAADAAEECQAGABIAtgADAAEECQAIAAYAyAADAAEECQAJAL4AzgADAAEECQALACQBjAADAAEECQANApYBsAADAAEECQAOADQERgADAAEECQAQAAgAKgADAAEECQARAAgAMgADAAEECQEAAB4EegADAAEECQEBABwEmAADAAEECQECAB4EtABDAG8AcAB5AHIAaQBnAGgAdAAgAKkAIAAyADAAMgAyACAAUwB1AG4ALgBTAFUASQBUAEIAbwBsAGQAMgAuADAANAAwADsAUwBVAE4ATgA7AFMAVQBJAFQALQBCAG8AbABkAFMAVQBJAFQAIABCAG8AbABkAFYAZQByAHMAaQBvAG4AIAAyAC4AMAA0ADAAOwBHAGwAeQBwAGgAcwAgADMALgAyAC4AMwAgACgAMwAyADYAMAApAFMAVQBJAFQALQBCAG8AbABkAFMAdQBuAFMAdQBuADsAIABLAG8AcgBlAGEAbgAgAEcAbAB5AHAAaABzACAAZgByAG8AbQAgAFMAbwB1AHIAYwBlACAASABhAG4AIABTAGEAbgBzACAAKABTAGEAbgBkAG8AbABsACAAQwBvAG0AbQB1AG4AaQBjAGEAdABpAG8AbgBzADsAIABTAG8AbwAtAHkAbwB1AG4AZwAgAEoAYQBuAGcALAAgAEoAbwBvAC0AeQBlAG8AbgAgAEsAYQBuAGcAKQBoAHQAdABwADoALwAvAHMAdQBuAC4AZgBvAC8AcwB1AGkAdABUAGgAaQBzACAARgBvAG4AdAAgAFMAbwBmAHQAdwBhAHIAZQAgAGkAcwAgAGwAaQBjAGUAbgBzAGUAZAAgAHUAbgBkAGUAcgAgAHQAaABlACAAUwBJAEwAIABPAHAAZQBuACAARgBvAG4AdAAgAEwAaQBjAGUAbgBzAGUALAAgAFYAZQByAHMAaQBvAG4AIAAxAC4AMQAuACAAVABoAGkAcwAgAEYAbwBuAHQAIABTAG8AZgB0AHcAYQByAGUAIABpAHMAIABkAGkAcwB0AHIAaQBiAHUAdABlAGQAIABvAG4AIABhAG4AIAAiAEEAUwAgAEkAUwAiACAAQgBBAFMASQBTACwAIABXAEkAVABIAE8AVQBUACAAVwBBAFIAUgBBAE4AVABJAEUAUwAgAE8AUgAgAEMATwBOAEQASQBUAEkATwBOAFMAIABPAEYAIABBAE4AWQAgAEsASQBOAEQALAAgAGUAaQB0AGgAZQByACAAZQB4AHAAcgBlAHMAcwAgAG8AcgAgAGkAbQBwAGwAaQBlAGQALgAgAFMAZQBlACAAdABoAGUAIABTAEkATAAgAE8AcABlAG4AIABG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AAAAAAAAAAAAAAAAAAAAAP9g/+z/7AAA/5L/sAAF//b/xP/E/87/2P/Y/7r/nP+m/+z/sP+6/7r/owAAAAAAAAAA/7AAAAAAAAAAAAAAAAD/sP/Z/9b/7AAA/83/xP/2AAAAAP/E/+z/7P/Y/7D/7P/EAAAAAAAAAAAAAAAAAAD/YP/iAAAAAP9+/6b/7P/s/9j/7P/N/87/2P+I/1b/Zv/O/5L/sP+wAAAAAP/YAAAAAAAAAAAAAP/2AAAAAAAA/+z/8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/+IAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACgAAAAAAAAAA/+wAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD/xP/iAAD/yP/s//b/6QAAAAD/7AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA//b/7AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD/7AAA//YAAAAAAAAAAAAAAAAAAAAAACgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD/sAAAAAAAAP/2AAD/zv/YAAAAAP/sAAD/5gAAAAAAAAAAAAD/4gAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP/sAAD/4gAA/+wAAP/2AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/9gAAAAAAAAAAAAAAAD/9v/v//b/9v/r/+z/7AAA/+IAAAAAAAoAAAAA/+IAAP/E//YAAP/E/+wAAP+IAAD/nP+6/1b/4v/s/+z/8P/s/9j/9v/E/9j/xP/sAAD/9gAAAAD/zgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA//b/9v/i/+wAAAAAAAAAAAAAAAAAAABoAAAAAP/YAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/9j/4gAAAAAAAP/2AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP/s//b/9v/i/+gAAP/Y/9j/2AAAAAAAAAAAAAD/2AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP/s/+L/4f/b/+H/uv/h/+wAAP/VAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD/2AAAAAAAAAAA//YAAAAAAAAAAAAAAAD/6AAAAAAAAAAAABQAAAAA//UAAAAAAAAAAAAAAAAAAP/8AAAAAAAAAAAAAP/s//X/xP/Y/+z/9v/Y/+n/7AAAAAAAAAAAAAD/9QAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP/OAAD/4gAAAAD/7P/iAAAAAAAAAAAAAP/1AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD/7P/s/8r/zgAA//YAAAAA/9j/7AAAAAAAAAAA//UAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD/7AAAAAAAAAAAAAAAAAAAAAAAAAAAAAD/9QACAAIAAgA3AAAAeAB4ADYAAQADAHYAAQACAAgABAADAAgABAAFAAQABgAHAAQABAAIAAkACAAKAAsADAANAA4ADgAPABAAEQAFABkAGgATABgAGgAUABsAGQAVABYAFwAYABkAGQAaABoAGwAcAB0AHgAfACAAIAAhACIAIwAYAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAEgABAAIAdwABAAIABQACAAIAAgAFAAIAAwAEAAIAAgACAAIABQACAAUAAgAGAAcACAAJAAkACgALABcAAwAPAA0ADwAPAA8ADAAPAA0ADQAYAA0ADQAOAA4ADwAOAA8ADgAQABEAEgATABMAFAAVABYADQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAaABoAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABsAGwAbABsAGwAbAAAAAAAAABkAAQAAAAoALgCoAAFERkxUAAgABAAAAAD//wAJAAAAAQACAAMABAAFAAYABwAIAAlhYWx0ADhwbnVtAD5zaW5mAERzczAxAEpzczE3AFRzczE4AF5zdWJzAGhzdXBzAG50bnVtAHQAAAABAAAAAAABAAQAAAABAAIABgABAAYAAAEAAAYAAQAHAAABAQAGAAEACAAAAQIAAAABAAEAAAABAAMAAAABAAUACQAUAQwBDAEaATIBaAGeAbwB3gADAAAAAQAIAAEAwgAbADwAQABEAEwAVgBeAGgAcgB2AHoAfgCCAIYAigCOAJIAlgCaAJ4AogCmAKoArgCyALYAugC+AAEAHAABADcAAwBHAEIARQAEAFEAVQBIAEYAAwBSAFYASQAEAFMAVwBKAEMABABUAFgASwBEAAEATAABAE0AAQBOAAEATwABAFAAAQA4AAEAOQABADoAAQA7AAEAPAABAD0AAQA+AAEAPwABAEAAAQBBAAEAZQABAGYAAQBZAAEAWgABAIMAAgAHAAoACgAAACgAKAABADgAQQACAEcAUAAMAFkAWgAWAGUAZgAYAIIAggAaAAEAAAABAAgAAQAUABgAAQAAAAEACAABAAYAHAACAAEAOQA8AAAAAQAAAAEACAACAB4ADAA4ADkAOgA7ADwAPQA+AD8AQABBAFkAWgACAAIARwBQAAAAZQBmAAoAAQAAAAEACAACAB4ADABHAEgASQBKAEsATABNAE4ATwBQAGUAZgACAAIAOABBAAAAWQBaAAoAAQAAAAEACAACAAwAAwBCAEMARAABAAMAOAA7ADwAAQAAAAEACAACAA4ABAAcADcARQBGAAEABAAKACgAOAA5AAEAAAABAAgAAQAGAAEAAQABAIIAAA=="
def _register_bundled_fonts():
    """Privately register bundled SUIT fonts on Windows so the recorder matches the web brand.
    No-op on non-Windows or any failure (GUI then falls back to Segoe UI via _pick)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        FR_PRIVATE = 0x10
        d = tempfile.mkdtemp(prefix="encore_suit_")
        for fn, b in (("SUIT-Regular.otf", _SUIT_REG_B64), ("SUIT-Medium.otf", _SUIT_MED_B64),
                      ("SUIT-SemiBold.otf", _SUIT_SB_B64), ("SUIT-Bold.otf", _SUIT_BOLD_B64)):
            p = os.path.join(d, fn)
            with open(p, "wb") as fh:
                fh.write(base64.b64decode(b))
            ctypes.windll.gdi32.AddFontResourceExW(ctypes.c_wchar_p(p), FR_PRIVATE, 0)
    except Exception:
        pass


def run_gui(cfg, url):
    """Ambient status bar: scene backdrop + status; settings/log expand on demand."""
    import tkinter as tk
    import tkinter.font as _tkfont
    import math
    BG="#0B0E14"; SURF="#161B25"; INK="#EDF0F6"; INK2="#A7AFBE"; DIM="#6E7686"
    AZ="#5B9BFF"; AZ2="#84B4FF"; REC="#FF5C57"; AMB="#E7A73F"; LINE="#1E2531"; LINE2="#2B3340"
    PANEL="#0B0E14"; SKY="#0c1018"; GND="#06090e"
    W=520; CH=140

    def _mix(h1, h2, t):
        a=tuple(int(h1[i:i+2],16) for i in (1,3,5)); b=tuple(int(h2[i:i+2],16) for i in (1,3,5))
        return "#%02x%02x%02x" % tuple(int(a[i]+(b[i]-a[i])*t) for i in range(3))

    _register_bundled_fonts()
    root=tk.Tk(); root.title("ENCORE"); root.configure(bg=BG)
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
    LAT=_pick("SUIT","Segoe UI","Arial"); SANS_M=_pick("SUIT Medium","SUIT","Segoe UI","Arial"); SANS_SB=_pick("SUIT SemiBold","SUIT","Segoe UI","Arial"); MON=_pick("Consolas","Cascadia Mono","Courier New")
    fW=(SANS_SB,15); fSub=(SANS_M,11); fChip=(SANS_M,10); fBtn=(SANS_SB,11); fMeta=(SANS_M,10)

    try:
        scene_idle=tk.PhotoImage(data=_SCENE_IDLE_B64); scene_warm=tk.PhotoImage(data=_SCENE_WARM_B64)
    except Exception:
        scene_idle=scene_warm=None
    root._scenes=(scene_idle, scene_warm)

    BASE_H=CH; SET_H=120; LOG_H=200
    root.geometry(f"{W}x{BASE_H}"); root.resizable(False, True)
    st={"log":False,"settings":False,"rec":False,"rec_start":0.0}

    # ---------- callbacks ----------
    def open_gallery():
        try: open_app(url)
        except Exception: pass
    def open_folder():
        try:
            if sys.platform=="win32": os.startfile(REC_DIR)
        except Exception: pass
    def do_quit():
        try: root.destroy()
        except Exception: pass
        os._exit(0)
    _sbe=sb_enabled()
    def do_sync():
        set_log(True); threading.Thread(target=lambda: sync_existing_to_cloud(), daemon=True).start()
    def do_reanalyze():
        set_log(True); threading.Thread(target=lambda: reanalyze_all(), daemon=True).start()
    def _save_cfg():
        try: json.dump(cfg, open(CONFIG_PATH,"w",encoding="utf-8"), ensure_ascii=False, indent=2)
        except Exception as e: log(f"Failed to save settings: {e}")

    def _scale_short(v): return {"auto":"Auto","source":"Source","1080":"1080p","720":"720p","480":"480p"}.get(str(v),"Auto")
    def _enc_short(v):   return {"auto":"Auto","nvenc":"NVENC","x264":"x264"}.get(str(v),"Auto")

    # ---------- tooltip ----------
    _tipwin={"w":None}
    def _tip_hide():
        try:
            if _tipwin["w"]: _tipwin["w"].destroy(); _tipwin["w"]=None
        except Exception: pass
    def _tip_show(widget, text):
        _tip_hide()
        try:
            tw=tk.Toplevel(root); tw.wm_overrideredirect(True); tw.configure(bg=LINE2)
            tk.Label(tw, text=text, bg="#0a0d13", fg=INK, font=(LAT,9), padx=7, pady=3).pack(padx=1, pady=1)
            tw.update_idletasks()
            x=widget.winfo_rootx()+widget.winfo_width()//2 - tw.winfo_width()//2
            y=widget.winfo_rooty()-tw.winfo_height()-6
            tw.geometry(f"+{x}+{y}"); _tipwin["w"]=tw
        except Exception: pass

    # ---------- canvas (scene + status + meta + actions) ----------
    cv=tk.Canvas(root, width=W, height=CH, bg=GND, highlightthickness=0); cv.pack(fill="x")
    cv_img=cv.create_image(0,0, anchor="nw", image=scene_idle) if scene_idle else None
    lid=cv.create_oval(18,28,27,37, fill=AZ, outline="")
    wid=cv.create_text(40,32, anchor="w", text="Starting\u2026", fill=INK, font=fW)
    sid=cv.create_text(150,32, anchor="w", text="", fill=DIM, font=fSub)
    def _layout_status():
        try:
            bb=cv.bbox(wid); x=(bb[2] if bb else 120)+9; cv.coords(sid, x, 32)
        except Exception: pass

    # meta: chips + cloud (top-right)
    meta=tk.Frame(cv, bg=SKY)
    PILL="#13171f"; PILLH="#1c2740"
    specpill=tk.Frame(meta, bg=PILL, highlightthickness=1, highlightbackground=LINE2, highlightcolor=LINE2)
    chipQ=tk.Label(specpill, text=_scale_short(cfg.get("scale","auto")), bg=PILL, fg=INK2, font=fChip, cursor="hand2")
    chipQ.pack(side="left", padx=(10,7), pady=4)
    _specsep=tk.Frame(specpill, bg=LINE2, width=1, height=11); _specsep.pack(side="left", pady=5)
    chipE=tk.Label(specpill, text=_enc_short(cfg.get("encoder","auto")), bg=PILL, fg=INK2, font=fChip, cursor="hand2")
    chipE.pack(side="left", padx=(7,10), pady=4)
    def _spec_hover(on):
        bg=PILLH if on else PILL; bd=AZ if on else LINE2; fg="#ffffff" if on else INK2
        specpill.config(bg=bg, highlightbackground=bd)
        chipQ.config(bg=bg, fg=fg); chipE.config(bg=bg, fg=fg); _specsep.config(bg=(AZ if on else LINE2))
    for w in (specpill, chipQ, chipE, _specsep):
        w.bind("<Button-1>", lambda e: toggle_settings())
        w.bind("<Enter>", lambda e: _spec_hover(True))
        w.bind("<Leave>", lambda e: (None if st["settings"] else _spec_hover(False)))
    specpill.pack(side="left")
    _cs=cloud_state()
    _cloud_txt,_cloud_col={"cloud":("\u2601 Cloud",AZ2),"readonly":("\u26a0 Key",AMB),"local":("\u25cf Local",DIM)}[_cs]
    tk.Label(meta, text=_cloud_txt, bg=SKY, fg=_cloud_col, font=fMeta).pack(side="left", padx=(9,0))
    cv.create_window(W-14, 24, anchor="e", window=meta)

    # actions: buttons (bottom-left)
    btnf=tk.Frame(cv, bg=GND)
    def mkbtn(parent, text, cmd, primary=False):
        base="#2c5499" if primary else "#181c26"; hov="#36639f" if primary else "#1f2531"
        fg="#dfeaff" if primary else INK2; bord="#5e84c8" if primary else LINE2
        b=tk.Label(parent, text=text, bg=base, fg=fg, font=fBtn, padx=14, pady=7, cursor="hand2",
                   highlightthickness=1, highlightbackground=bord, highlightcolor=bord)
        b.bind("<Button-1>", lambda e: cmd()); b.bind("<Enter>", lambda e: b.config(bg=hov)); b.bind("<Leave>", lambda e: b.config(bg=base))
        return b
    mkbtn(btnf, "\u25b6  Gallery", open_gallery, primary=True).pack(side="left")
    mkbtn(btnf, "Open folder", open_folder).pack(side="left", padx=(7,0))
    cv.create_window(16, CH-22, anchor="w", window=btnf)

    # icons: gear + log (bottom-right) with tooltips
    icof=tk.Frame(cv, bg=GND)
    def mkicon(parent, glyph, cmd, tip):
        f=tk.Frame(parent, bg="#181c26", highlightthickness=1, highlightbackground=LINE2, cursor="hand2", width=31, height=31)
        f.pack_propagate(False)
        lb=tk.Label(f, text=glyph, bg="#181c26", fg=DIM, font=(LAT,13)); lb.pack(expand=True)
        def _en(e): _tip_show(f, tip); f.config(bg="#1f2531"); lb.config(bg="#1f2531", fg=INK)
        def _lv(e): _tip_hide();      f.config(bg="#181c26"); lb.config(bg="#181c26", fg=DIM)
        for w in (f, lb):
            w.bind("<Button-1>", lambda e: cmd()); w.bind("<Enter>", _en); w.bind("<Leave>", _lv)
        return f, lb
    gearf, gearl = mkicon(icof, "\u2699", lambda: toggle_settings(), "Settings"); gearf.pack(side="left")
    logf,  logl  = mkicon(icof, "\u2630", lambda: toggle_log(),      "Log");      logf.pack(side="left", padx=(7,0))
    cv.create_window(W-14, CH-22, anchor="e", window=icof)

    # toast
    _toast={"id":None}
    def hide_toast():
        try:
            if _toast["id"] is not None: cv.delete(_toast["id"]); _toast["id"]=None
        except Exception: pass
    def show_toast(text="Uploaded \u2713"):
        hide_toast()
        lbl=tk.Label(cv, text=text, bg=AZ, fg="#ffffff", font=(LAT,10,"bold"), padx=13, pady=5)
        _toast["id"]=cv.create_window(W//2, 30, window=lbl)
        root.after(5000, hide_toast)

    # ---------- settings panel (below canvas) ----------
    optwrap=tk.Frame(root, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
    tk.Label(optwrap, text="Recording settings", bg=PANEL, fg=INK2, font=(LAT,9,"bold")).pack(anchor="w", padx=14, pady=(11,5))
    SCALE_OPTS=[("Auto (best)","auto"),("Source res","source"),("1080p","1080"),("720p","720"),("480p","480")]
    ENC_OPTS=[("Auto (GPU first)","auto"),("GPU \u00b7 NVENC","nvenc"),("CPU \u00b7 x264","x264")]
    CAP_OPTS=[("Auto","auto"),("WGC (fullscreen OK)","wgc"),("DDA","ddagrab"),("GDI","gdigrab")]
    MON_OPTS=[("Auto","auto"),("Monitor 1","0"),("Monitor 2","1"),("Monitor 3","2")]
    def opt_row(label, opts, key, chip=None, shortfn=None):
        row=tk.Frame(optwrap, bg=PANEL); row.pack(fill="x", padx=14, pady=3)
        tk.Label(row, text=label, bg=PANEL, fg=INK2, font=(LAT,9), width=7, anchor="w").pack(side="left")
        cur=str(cfg.get(key,"auto")); m={l:v for l,v in opts}
        curlbl=next((l for l,v in opts if v==cur), opts[0][0]); var=tk.StringVar(value=curlbl)
        def on_sel(lbl, k=key, mp=m, lb=label, ch=chip, sf=shortfn):
            cfg[k]=mp[lbl]; _save_cfg(); log(f"Setting: {lb} -> {lbl} (applies from next recording)")
            if k in ("encoder","preset","fps"):
                try: _reset_enc_cache()
                except Exception: pass
            if ch is not None and sf is not None:
                try: ch.config(text=sf(cfg[k]))
                except Exception: pass
        om=tk.OptionMenu(row, var, *[l for l,_ in opts], command=on_sel)
        om.config(bg="#1B212D", fg=INK, font=(LAT,9), activebackground="#262C36", activeforeground=INK,
                  relief="flat", bd=0, highlightthickness=1, highlightbackground=LINE2, anchor="w", padx=10, pady=4, cursor="hand2")
        try: om["menu"].config(bg=SURF, fg=INK, activebackground=AZ, activeforeground="#fff", font=(LAT,9), bd=0, activeborderwidth=0)
        except Exception: pass
        om.pack(side="left", fill="x", expand=True)
    opt_row("Quality", SCALE_OPTS, "scale", chipQ, _scale_short)
    opt_row("Encoder", ENC_OPTS, "encoder", chipE, _enc_short)
    opt_row("Capture", CAP_OPTS, "capture")
    opt_row("Monitor", MON_OPTS, "output_idx")
    tk.Label(optwrap, text="Auto (default) records at the highest quality, on GPU, without slowing the game.",
             bg=PANEL, fg=DIM, font=(LAT,8), wraplength=W-48, justify="left").pack(anchor="w", padx=14, pady=(5,9))
    if _sbe:
        tk.Frame(optwrap, bg=LINE, height=1).pack(fill="x", padx=14, pady=(0,8))
        mrow=tk.Frame(optwrap, bg=PANEL); mrow.pack(fill="x", padx=14, pady=(0,11))
        tk.Label(mrow, text="Maintenance", bg=PANEL, fg=DIM, font=(LAT,8), anchor="w").pack(side="left")
        mkbtn(mrow, "Reanalyze", do_reanalyze).pack(side="right")
        mkbtn(mrow, "Upload", do_sync).pack(side="right", padx=(0,7))

    # ---------- log panel (below) ----------
    logwrap=tk.Frame(root, bg=BG)
    errbar=tk.Label(logwrap, text="", bg="#3A1E18", fg="#ffb4a6", font=(LAT,9), anchor="w",
                    padx=10, pady=6, justify="left", wraplength=W-40)
    logtxt=tk.Text(logwrap, bg="#0A0C10", fg=DIM, font=(MON,9), bd=0, padx=10, pady=8,
                   height=9, wrap="word", state="disabled")

    # ---------- toggles + resize ----------
    def _resize():
        h=BASE_H + (SET_H if st["settings"] else 0) + (LOG_H if st["log"] else 0)
        root.geometry(f"{W}x{h}")
    def _chip_on(on):
        try: _spec_hover(on)
        except Exception: pass
        gearl.config(fg=(AZ2 if on else DIM))
    def set_log(open_):
        if open_ and st["settings"]: set_settings(False)
        st["log"]=open_
        if open_:
            logwrap.pack(fill="both", expand=True, padx=11, pady=(0,7))
            if LAST_ERR.get("msg"): errbar.config(text="\u26a0 " + LAST_ERR["msg"]); errbar.pack(fill="x", pady=(0,5))
            else: errbar.pack_forget()
            logtxt.pack(fill="both", expand=True); logl.config(fg=AZ2)
        else:
            logwrap.pack_forget(); logl.config(fg=DIM)
        _resize()
    def set_settings(open_):
        if open_ and st["log"]: set_log(False)
        st["settings"]=open_
        if open_: optwrap.pack(fill="x", padx=12, pady=(2,2))
        else: optwrap.pack_forget()
        _chip_on(open_)
        _resize()
    def toggle_log(): set_log(not st["log"])
    def toggle_settings(): set_settings(not st["settings"])

    # ---------- window close (X = quit; minimize stays in taskbar) ----------
    root.protocol("WM_DELETE_WINDOW", do_quit)

    # ---------- background prep + recorder ----------
    def _prep_and_run():
        global FFMPEG, SCREP
        try:
            if not FFMPEG: FFMPEG=ensure_ffmpeg()
            if not SCREP: SCREP=ensure_screp()
        except Exception as e:
            log(f"Problem preparing tools: {e}")
        if not FFMPEG:
            log("\u26a0 ffmpeg not ready - check your internet connection and run again."); return
        try: recover_orphan_clips()
        except Exception as e: log(f"Skipped recovering pending clips: {e}")
        try: rebuild_db_from_recordings()
        except Exception as e: log(f"Skipped folder recovery: {e}")
        recorder_loop(cfg)
    threading.Thread(target=_prep_and_run, daemon=True).start()

    # ---------- light pulse ----------
    def _pulse():
        try:
            if not int(root.winfo_exists()): return
        except Exception: return
        base=REC if st["rec"] else AZ
        k=0.55+0.45*(0.5+0.5*math.sin(time.time()*2.3))
        try: cv.itemconfig(lid, fill=_mix(GND, base, k))
        except Exception: pass
        root.after(90, _pulse)

    # ---------- detect actual auto values (resolution / encoder) ----------
    def _detect_actuals():
        try:
            sh=0
            try: sh=int(root.winfo_screenheight())
            except Exception: pass
            th=_target_height(sh)   # _encoder_args 실행 → enc_short 설정
            outh=(sh if sh else 1080) if th is None else th
            if outh: REC_STATE["res_short"]=f"{outh}p"
        except Exception: pass
        finally:
            REC_STATE["_detecting"]=False

    # ---------- poll ----------
    def poll():
        appended=False
        for _ in range(150):
            try: line=GUI_Q.get_nowait()
            except Exception: break
            if st["log"]:
                logtxt.config(state="normal"); logtxt.insert("end", line+"\n"); appended=True
        if appended:
            n=int(logtxt.index("end-1c").split(".")[0])
            if n>300: logtxt.delete("1.0", f"{n-300}.0")
            logtxt.see("end"); logtxt.config(state="disabled")
        rec=bool(REC_STATE.get("recording"))
        if rec and not st["rec"]:
            st["rec"]=True; st["rec_start"]=time.time()
            if scene_warm and cv_img is not None: cv.itemconfig(cv_img, image=scene_warm)
        elif not rec and st["rec"]:
            st["rec"]=False
            if scene_idle and cv_img is not None: cv.itemconfig(cv_img, image=scene_idle)
        up=REC_STATE.get("upload_pct")
        if rec:
            el=int(time.time()-st["rec_start"]); sub=f"\u00b7 {el//60:d}:{el%60:02d}"
            cv.itemconfig(wid, text="Recording", fill=INK)
        elif up is not None:
            sub="\u00b7 sending video"; cv.itemconfig(wid, text=f"Uploading {up}%", fill=INK)
        elif REC_STATE.get("ready"):
            sub="\u00b7 auto-records"; cv.itemconfig(wid, text="Ready", fill=INK)
        else:
            sub="\u00b7 preparing tools (1-2 min)"; cv.itemconfig(wid, text="Starting\u2026", fill=INK)
        cv.itemconfig(sid, text=sub); _layout_status()
        try:
            if str(cfg.get("scale","auto")).lower()=="auto":
                _r=REC_STATE.get("res_short")
                if _r: chipQ.config(text=_r)
            if str(cfg.get("encoder","auto")).lower()=="auto":
                _e=REC_STATE.get("enc_short")
                if _e: chipE.config(text=_e)
            if REC_STATE.get("ready") and not REC_STATE.get("enc_short") and not REC_STATE.get("_detecting"):
                REC_STATE["_detecting"]=True
                threading.Thread(target=_detect_actuals, daemon=True).start()
        except Exception: pass
        if UP_DONE.get("t",0) > UP_DONE.get("shown",0):
            UP_DONE["shown"]=UP_DONE["t"]; show_toast()
        if LAST_ERR.get("msg") and (time.time()-LAST_ERR.get("t",0) < 8):
            if not st["log"]: set_log(True)
            else: errbar.config(text="\u26a0 " + LAST_ERR["msg"])
        root.after(500, poll)

    try: root.update()
    except Exception: pass
    if sys.platform=="win32":
        try: _hide_console()
        except Exception: pass
    _pulse(); poll()
    try: root.mainloop()
    except Exception as ex: log(f"GUI window closed: {ex}")



def _print_status():
    s = sb_cfg(); st = cloud_state()
    print("\n" + "=" * 50)
    print("  ENCORE status check")
    print("=" * 50)
    print(f"  Data folder : {DATA_DIR}")
    print(f"  Replays     : {CFG.get('replay_autosave_dir') or '(none)'}")
    try:
        _c = db(); _n = _c.execute("SELECT COUNT(*) FROM matches").fetchone()[0]; _c.close()
        print(f"  Local games : {_n} (matches.db)")
    except Exception: pass
    print("-" * 50)
    print(f"  Supabase URL : {s.get('url') or '(none)'}")
    print(f"  anon_key     : {'set' if s.get('anon_key') else 'missing'}")
    print(f"  service_key  : {'set' if s.get('service_key') else 'missing  ← needed to upload'}")
    print(f"  bucket       : {s.get('bucket') or 'media'}")
    verdict = {"cloud": "☁ 클라우드 ON (업로드 가능)",
               "readonly": "⚠ 읽기전용 (service_key 입력 필요)",
               "local": "● 로컬 전용"}[st]
    print(f"\n  → {verdict}")
    if s.get("url") and (s.get("service_key") or s.get("anon_key")):
        print("\n  Testing Supabase connection...")
        try:
            import requests
            r = requests.get(_sb_base() + "/rest/v1/matches?select=id&limit=1", headers=_sb_h(), timeout=12)
            if r.status_code < 300:
                print("  ✓ Connection OK — read matches table successfully")
                try:
                    r2 = requests.get(_sb_base() + "/rest/v1/matches?select=id",
                                      headers={**_sb_h(), "Prefer": "count=exact", "Range": "0-0"}, timeout=12)
                    cr = r2.headers.get("content-range", "")
                    if "/" in cr: print(f"    ☁ Games stored in cloud: {cr.split('/')[-1]}")
                except Exception: pass
                if s.get("service_key"):
                    try:
                        rb = requests.get(_sb_base() + "/storage/v1/bucket/" + (_sb_bucket()),
                                          headers=_sb_h(write=True), timeout=12)
                        if rb.status_code < 300: print(f"  ✓ Storage bucket '{_sb_bucket()}' access OK (ready to upload)")
                        else: print(f"  ✗ Bucket access failed: HTTP {rb.status_code} — check bucket name/key")
                    except Exception as e: print(f"  ✗ Bucket test error: {e}")
            else:
                print(f"  ✗ Connection failed: HTTP {r.status_code} — {r.text[:140]}")
                print("    (the key may be wrong or the table may not exist. Make sure you ran schema.sql)")
        except Exception as e:
            print(f"  ✗ Connection test error: {e}")
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
        try: input("\nDone. Press Enter to exit...")
        except Exception: pass
        return
    if "--status" in sys.argv or "--check" in sys.argv:
        _print_status()
        try: input("\nPress Enter to exit...")
        except Exception: pass
        return
    if "--rebuild-db" in sys.argv or cfg.get("mode") == "rebuild":
        try: SCREP = ensure_screp()
        except Exception: pass
        try: FFMPEG = ensure_ffmpeg()
        except Exception: pass
        n = rebuild_db_from_recordings()
        print(f"\nRecovery complete: added {n} games to the DB.")
        try: input("Press Enter to exit...")
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
    print("=" * 56); print(f"  StarCraft auto recorder/archive — mode: {mode}"); print("=" * 56)
    _cst = cloud_state()
    if _cst == "cloud":
        log(f"☁ Cloud ON — saving and sharing via Supabase({_sb_base()}).")
    elif _cst == "readonly":
        log("⚠ Cloud read-only — supabase.service_key in config.json is empty. Fill it and restart to enable uploads.")
    else:
        log("● Local mode — saved only on this PC. (fill in supabase in config.json to turn Cloud ON)")
    if mode in ("all", "recorder"):
        log(f"Replay folder: {cfg['replay_autosave_dir']}")
        if not os.path.isdir(cfg["replay_autosave_dir"]):
            log("⚠ Couldn't find the replay folder. Save a replay once in StarCraft and the folder will appear.")
        if not use_gui:               # GUI면 창부터 띄우고 백그라운드에서 받음(첫 실행이 멈춘 듯 안 보이게)
            FFMPEG = ensure_ffmpeg()
            if not FFMPEG:
                _safe_input("\nWithout ffmpeg, recording isn't possible. Press Enter to exit..."); return
    cloud_on = bool((cfg.get("cloud") or {}).get("function_url"))
    if (mode in ("all", "server") or cloud_on) and not use_gui:
        SCREP = ensure_screp()        # 클라우드 모드: 클라이언트가 리플레이를 직접 분석
        if not FFMPEG: FFMPEG = ensure_ffmpeg()
    url = (cfg.get("gallery_url") or "https://encorestar.netlify.app/").rstrip("/")
    if cloud_on:
        log("Cloud mode: video to R2, metadata + analysis uploaded directly to Supabase.")
        g = cfg.get("gallery_url") or ""
        if g:
            log(f"Gallery → {g}  (open it from the Gallery button)")
            # startup browser auto-open removed
        print("-" * 56); recorder_loop(cfg); return
    if mode == "all":
        log(f"Gallery → {url}  (open it from the Gallery button)")
        # startup browser auto-open removed - gallery opens via button only
        # 보기 좋은 상태창(GUI). 윈도우 + tkinter 가능하면 GUI로, 아니면 콘솔로.
        if sys.platform == "win32" and (cfg.get("ui", "window") != "console"):
            try:
                import tkinter  # noqa: F401  (가용성 확인)
                run_gui(cfg, url); return
            except Exception as e:
                log(f"GUI unavailable ({e}) → continuing in console mode")
    if mode in ("all", "recorder"):
        if not FFMPEG: FFMPEG = ensure_ffmpeg()
        print("-" * 56); recorder_loop(cfg)

if __name__ == "__main__":
    main()
