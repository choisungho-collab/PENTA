#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
myPENTA — 리그 오브 레전드 자동 녹화 (한 번 실행하면 다 됨)
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
import os, sys, json, time, socket, subprocess, datetime, traceback, threading, hashlib

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
            print("상세:", e); _safe_input("\n엔터를 누르면 종료...")
            sys.exit(1)
    # 선택: 시스템 트레이용(윈도우 전용). 없어도 동작 — ✕가 종료로 폴백. 실패는 조용히 무시.
    if sys.platform == "win32":
        for _mod, _pkg in [("pystray", "pystray"), ("PIL", "pillow")]:
            try:
                __import__(_mod)
            except Exception:
                try:
                    subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", _pkg],
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception:
                    pass
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
REC_STATE  = {"rec": False, "text": "Idle", "game": None}   # 실시간 녹화 상태(웹 표시용)
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
    if any(k in s for k in ("error", "Error", "failed", "Failed", "exception", "Traceback")) and ("restarting" not in s):
        LAST_ERR["msg"] = s[:240]; LAST_ERR["t"] = time.time()
    if "Recording started" in s:
        REC_STATE["recording"] = True
        if "WGC" in s: REC_STATE["capture"] = "WGC"
        elif "gdigrab" in s: REC_STATE["capture"] = "GDI"
        elif "Monitor" in s: REC_STATE["capture"] = "DXGI"
    elif ("Recording stopped" in s) or ("Idle" in s) or ("Game ended" in s): REC_STATE["recording"] = False
    if "Ready." in s: REC_STATE["ready"] = True
    if s.startswith("Encoder:"): REC_STATE["encoder"] = s.split("Encoder:", 1)[1].strip()
    if "Upload complete" in s: REC_STATE["uploaded_at"] = time.time()
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

def _atomic_write_json(path, data):
    """JSON을 원자적으로 저장 — 쓰는 도중 앱이 종료/크래시/정전이 나도 원본 파일이 깨지지 않는다.
    임시파일에 완전히 쓰고 fsync 로 디스크에 확정한 뒤 os.replace 로 통째 교체(전부 or 전무)."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        try: os.fsync(f.fileno())
        except Exception: pass
    os.replace(tmp, path)


def load_or_make_config():
    cfg = None
    if os.path.isfile(CONFIG_PATH):
        try:
            cfg = json.load(open(CONFIG_PATH, encoding="utf-8"))
            if not isinstance(cfg, dict):
                raise ValueError("config.json is not a JSON object")
        except Exception as e:
            # config.json 손상 → 망가진 파일은 .broken 으로 백업하고 기본값으로 재생성 (앱이 안 켜지는 것 방지)
            try: os.replace(CONFIG_PATH, CONFIG_PATH + ".broken")
            except Exception:
                try: os.remove(CONFIG_PATH)
                except Exception: pass
            log(f"config.json 손상 — 기본값으로 재생성합니다 (기존 파일은 config.json.broken 으로 백업): {e}")
            cfg = None
    if cfg is None:
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
        _atomic_write_json(CONFIG_PATH, cfg)
        log(f"Config created → {CONFIG_PATH}")
    # service_key 영구보관: 한 번 넣으면 data 폴더에 저장 → 이후 zip 통째로 덮어써도 유지
    try:
        _sk = ((cfg.get("supabase") or {}).get("service_key") or "").strip()
        _secret = os.path.join(DATA_DIR, "penta_secret.json")
        if _sk:
            _atomic_write_json(_secret, {"service_key": _sk})
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
        log("Setting up audio engine (pyaudiowpatch, first run)…")
        _run([sys.executable, "-m", "pip", "install", "-q", "pyaudiowpatch", "--break-system-packages"], timeout=300)
        import pyaudiowpatch  # noqa
        log("Audio engine ready.")
        return True
    except Exception as e:
        log(f"  (audio) pyaudiowpatch install failed → recording without sound. Manual: pip install pyaudiowpatch ({e})")
        return False

def ensure_ffmpeg():
    local = os.path.join(HERE, "ffmpeg.exe")
    if os.path.isfile(local): return local
    found = shutil.which("ffmpeg")
    if found: return found
    log("Downloading ffmpeg… (~80MB, first run only, 1–3 min)")
    sources = [
        ("gyan-essentials", "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"),
        ("BtbN", "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"),
        ("gyan-full", "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-full.zip"),
    ]
    def _fetch(url, timeout=180, tries=3):
        last = None
        for _i in range(tries):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    total = int(r.headers.get("Content-Length") or 0)
                    buf = io.BytesIO(); got = 0
                    while True:
                        chunk = r.read(262144)
                        if not chunk: break
                        buf.write(chunk); got += len(chunk)
                    if total and got < int(total * 0.99):
                        raise IOError(f"불완전 다운로드 {got}/{total} bytes")
                    return buf.getvalue()
            except Exception as e:
                last = e
                if _i < tries - 1:
                    log(f"    Retrying {_i+1}/{tries-1} ({type(e).__name__})…"); time.sleep(2.0 * (_i + 1))
        raise last
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
            data = _fetch(url)
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
    log("[!] ffmpeg auto-download failed on all sources. Please download manually:")
    log("    1) Download https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip")
    log("    2) Unzip and find  bin\\ffmpeg.exe  inside")
    log(f"    3) Copy it to this folder:  {HERE}")
    log("    4) Run penta_recorder.exe again")
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
PROXY_DEFAULT = "https://mypenta.netlify.app"   # Riot API 프록시(Netlify Function) — config.json 없어도 분석이 자동 연결되도록 기본값
SB_DEFAULTS = {
    "url": "https://bsrvmesrygbfeqicquvq.supabase.co",
    "anon_key": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImJzcnZtZXNyeWdiZmVxaWNxdXZxIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODIzNjA2NjQsImV4cCI6MjA5NzkzNjY2NH0.PBnGgLxvMDOK_yUQxTH11EwizEz5oJ1OWp-9I5nG8Ug",
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
            log("Trimmed the lobby/loading intro so it starts at the countdown")
        else:
            try: os.remove(tmp)
            except OSError: pass
    except Exception as e:
        log(f"Skipped trimming (keeping original): {e}")


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
            log("  NVENC is listed but failed to encode → switching to software (libx264)")
    if use_nvenc:
        _ENC_IS_SW = False
        _ENC_CACHE = ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", "20"]; name = "NVENC"
    else:
        _ENC_IS_SW = True
        preset = (CFG.get("preset") or "auto").lower()
        if preset in ("auto", ""): preset = "superfast"   # 소프트웨어는 게임 끊김 방지 위해 가벼운 프리셋
        _ENC_CACHE = ["-c:v", "libx264", "-preset", preset, "-crf", "25"]; name = f"x264 ({preset})"
    log(f"Encoder: {name}")
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
                log(f"  (audio) pyaudiowpatch not installed → recording without sound. Install: pip install pyaudiowpatch ({e})"); return
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
                log(f"  ♪ Audio recording started ({str(dev.get('name','?'))[:26]} · {rate}Hz {ch}ch)")
                while not box["stop"].is_set():
                    try: wf.writeframes(stream.read(2048, exception_on_overflow=False))
                    except Exception: break
            except Exception as e:
                log(f"  (audio) capture failed → recording without sound: {e}")
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
                self.path = out; log("■ Audio merged"); return out
            log("  (audio) merge result empty → using video only")
            try:
                if os.path.isfile(out): os.remove(out)
            except OSError: pass
            return vid
        except Exception as e:
            log(f"  (audio) merge failed → video only: {e}"); return vid

    def _start_wgc(self, verify=True):
        """WGC(OBS식)로 프레임을 받아 ffmpeg로 인코딩. 정지화면이어도 직전 프레임을 고정 fps로 계속 먹임(전체화면 게임도 잡힘)."""
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
        try:
            # draw_border=False → 녹화 중 노란 테두리 제거(Windows 11에서 적용; Windows 10은 OS에 해당 기능이 없어 무시됨)
            cap = WindowsCapture(cursor_capture=None, draw_border=False, monitor_index=1, window_name=None)
        except Exception as e:
            log(f"  WGC init failed: {e}"); return False

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
            if vf: log(f"  Lowering CPU load: capturing {h}p → encoding at {_target_height(h)}p")
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
            log(f"  WGC start failed: {e}"); return False
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
        log("  WGC produced no frames (frames:{}, ffmpeg:{}, file:{}B, err:{}) → trying another method".format(
            n1, "alive" if alive else "dead", _sz(), ferr or "none"))
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
                log(f"Recording start error ({mode} #{idx}): {e}"); self._kill()
        if not self.warned_black:
            self.warned_black = True
            log("[!] Couldn't verify capture (the screen may be black). Recording continues anyway.")
            log("    • Play a game first and check the recording (it may be a false alarm from the loading screen)")
            log("    • Set \"capture\" to \"wgc\" in config.json, or run League in 'windowed (fullscreen)' mode")
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


def _sec_mmss(s):
    s = int(s or 0)
    return f"{s//60}:{s%60:02d}"

def _video_dur(video_path):
    """ffprobe로 영상 실제 길이(초)를 잰다. 분석을 못 했을 때 길이 판단용. 실패하면 0."""
    try:
        fp = os.path.join(HERE, "ffprobe.exe")
        if not os.path.isfile(fp): fp = "ffprobe"
        out = subprocess.run([fp, "-v", "error", "-show_entries", "format=duration",
                              "-of", "default=nw=1:nk=1", video_path],
                             capture_output=True, text=True, timeout=30).stdout.strip()
        return float(out) if out else 0.0
    except Exception:
        return 0.0

def _discard(video_path, reason):
    log(f"  Discarding (not saving) — {reason}")
    try:
        if video_path and os.path.isfile(video_path): os.remove(video_path)
    except OSError: pass

def _live_gid(analysis, start_ts):
    """Live 자체분석 경기의 공통 ID — matchId가 없을 때, 같은 게임을 녹화한 사람끼리 같은 값이 나오게 한다.
    같은 게임은 참가자 10명과 날짜가 동일하므로 (정렬한 참가자 이름 + 날짜)를 해시한다.
    (일반 매치메이킹에서 같은 10명이 같은 날 다시 만날 확률은 사실상 0이라 충돌 걱정이 없다.)"""
    names = sorted([(p.get("name") or "") for p in (analysis.get("players") or []) if p.get("name")])
    try:
        day = datetime.datetime.fromtimestamp(start_ts).strftime("%Y%m%d")
    except Exception:
        day = datetime.datetime.now().strftime("%Y%m%d")
    key = "|".join(names) + "|" + day
    return "live_" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def ingest_lol(video_path, riot_id, start_ts, end_ts, proxy_url, platform="kr", live_data=None):
    # 화면 녹화 + (게임 종료 후) Riot 매치를 연결해 분석·업로드한다.
    # Riot 매치 연결이 안 되더라도(개발키 만료/레이트리밋/타이밍 등) 영상은 업로드하고 아카이브에 올린다.
    if not video_path or not os.path.isfile(video_path) or os.path.getsize(video_path) < 10000:
        log("Video is empty → skipping registration."); return
    if not riot_id:
        return _discard(video_path, "Couldn't verify your Riot ID (may not be a game)")

    # --- Riot 매치 연결 시도 (실패해도 영상은 올린다; 분석만 비움) ---
    match, puuid, analysis, mid = None, None, {}, ""
    if proxy_url:
        try:
            match, puuid = penta_lol.resolve_match(proxy_url, riot_id, start_ts, end_ts, platform)
        except Exception as e:
            log(f"  Match lookup failed ({e}) — uploading the video without analysis.")
        if match:
            mid = (match.get("metadata") or {}).get("matchId") or str((match.get("info") or {}).get("gameId") or "")
            try:
                timeline = penta_lol.proxy_get(proxy_url, "timeline", matchId=mid, platform=platform)
                analysis = penta_lol.analyze_match(match, timeline) or {}
            except Exception as e:
                log(f"  Analysis failed ({e}) — uploading the video without analysis."); analysis = {}
        else:
            log("  No Riot match linked (API key/timing) — uploading the video without analysis.")
    else:
        log("  proxy_url not set — Riot analysis skipped.")

    # Riot 분석이 비었으면(키 만료/레이트리밋/타이밍) Live Client 스냅샷으로 자체 분석 — 키 없이 동작
    if not analysis.get("players") and live_data and live_data.get("snaps"):
        try:
            _mn = (riot_id or "").split("#")[0]
            _la = penta_lol.analyze_live(live_data.get("snaps"), live_data.get("events"), _mn) or {}
            if _la.get("players"):
                analysis = _la
                log(f"  Self-analysis from Live Client ({len(_la['players'])} players, no Riot key needed).")
        except Exception as e:
            log(f"  Live self-analysis failed ({e}).")

    # --- 게임 길이: 분석값이 있으면 그걸, 없으면 영상 실제 길이로 ---
    dur = analysis.get("duration") or 0
    if dur and dur > 100000: dur = dur / 1000.0    # 과거 게임은 길이가 ms일 수 있어 보정
    if not dur:
        dur = _video_dur(video_path)
    if dur and dur < CFG.get("min_game_sec", 300):
        return _discard(video_path, f"Game too short ({int(dur)}s)")

    # --- ID: 매치ID가 있으면 그걸, 없으면(Live 자체분석) 같은 게임 녹화자끼리 묶이도록 참가자 기반 ID, 그도 없으면 임시 ID ---
    if mid:
        gid = mid
    elif analysis.get("players"):
        gid = _live_gid(analysis, start_ts)   # 같은 게임을 녹화한 사람끼리 멀티뷰로 묶임
    else:
        gid = "local_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    row_id = gid + "__" + (puuid or riot_id.replace("#", "_")).replace("/", "_")   # 시점별 고유 행 id
    safe = row_id.replace("/", "_")
    size = os.path.getsize(video_path)
    base = os.path.join(UPLOAD_DIR, safe); os.makedirs(base, exist_ok=True)
    try:
        if dur and analysis: _trim_lead(video_path, dur)   # 분석으로 시점을 아는 경우에만 로비/로딩 컷
    except Exception: pass
    if not sb_writable():
        log("Cloud (Supabase) not configured → keeping locally only."); return
    tmp_thumb = os.path.join(base, "thumb.jpg"); has_thumb = make_thumb(video_path, tmp_thumb)
    try:
        video_url = sb_upload(video_path, f"videos/{safe}.mp4", "video/mp4")
        thumb_url = sb_upload(tmp_thumb, f"thumbs/{safe}.jpg", "image/jpeg") if has_thumb else None
        players = analysis.get("players") or []
        me = next((p for p in players if puuid and p.get("puuid") == puuid), None)
        if not me and riot_id:
            _mn2 = riot_id.split("#")[0]
            me = next((p for p in players if p.get("name") == _mn2), None)
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
        log(f"Upload complete — {('matchId ' + gid) if mid else 'video only (no analysis)'}")
    except Exception as e:
        log(f"Upload failed: {e}")

def recorder_loop(cfg):
    proc = cfg.get("league_process", "League of Legends.exe")
    proxy = (cfg.get("proxy_url") or "").strip() or PROXY_DEFAULT; platform = cfg.get("platform", "kr")
    poll = float(cfg.get("poll_seconds", 4)); rec = Recorder(int(cfg.get("fps", FPS)))
    was = False; active = False; riot_id = None; start_ts = None
    live_snaps = []; live_evts = []; last_snap_t = -999.0   # 게임 중 Live Client 스냅샷 수집용
    try: ensure_audio()
    except Exception: pass
    if not proxy:
        log("Note: proxy_url in config.json is empty. Set your Netlify proxy URL to connect analysis.")
    log("Ready. Start a League of Legends game and it records automatically. (Keep this window open.)")
    while True:
        try:
            run = sc_running(proc)   # 게임 인스턴스(League of Legends.exe) = 인게임
            if run and not was:
                log("Game detected. Checking your info…")
                for _ in range(20):
                    if penta_lol.game_active():
                        riot_id = penta_lol.my_riot_id() or riot_id; break
                    time.sleep(1)
                start_ts = time.time(); active = rec.start()
                live_snaps = []; live_evts = []; last_snap_t = -999.0
            if run:
                if not rec._recording():
                    if active: log("Recording stream dropped → restarting automatically.")
                    active = rec.start()
                if not riot_id and penta_lol.game_active():
                    riot_id = penta_lol.my_riot_id()
                # Live Client 스냅샷 수집(약 25초 간격) — Riot API가 안 돼도 게임 종료 후 자체 분석할 수 있게
                try:
                    snap = penta_lol.live_snapshot()
                    if snap and (float(snap.get("t") or 0) - last_snap_t) >= 25:
                        live_snaps.append(snap); last_snap_t = float(snap.get("t") or 0)
                        _ev = penta_lol.live_events()
                        if _ev: live_evts = _ev
                except Exception: pass
            if not run and was:
                log("Game ended.")
                vid = rec.stop(); active = False; rec.verified = False
                end_ts = time.time()
                if vid and os.path.isfile(vid):
                    threading.Thread(target=ingest_lol, args=(vid, riot_id, start_ts, end_ts, proxy, platform), kwargs={"live_data": {"snaps": list(live_snaps), "events": list(live_evts)}}, daemon=True).start()
                riot_id = None; start_ts = None; log("Idle.")
            # 웹 표시용 실시간 상태 갱신
            if run and rec._recording():
                REC_STATE.update(rec=True, text="Recording")
            elif run:
                REC_STATE.update(rec=False, text="Game detected")
            else:
                REC_STATE.update(rec=False, text="Idle — auto-records when a game starts")
            was = run; time.sleep(poll)
        except KeyboardInterrupt:
            log("Quitting."); rec.stop(); break
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
            log("Registered to run at Windows startup (set autostart to false in config.json to disable)")
        else:
            try: winreg.DeleteValue(key, "PENTA")
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

def _load_recorder_fonts():
    """Register bundled .ttf fonts so Tkinter can use Space Grotesk / IBM Plex Mono (Windows only)."""
    if sys.platform != "win32": return
    try:
        import ctypes
        base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
        fdir = os.path.join(base, "fonts")
        if not os.path.isdir(fdir): return
        for fn in os.listdir(fdir):
            if fn.lower().endswith((".ttf", ".otf")):
                ctypes.windll.gdi32.AddFontResourceExW(os.path.join(fdir, fn), 0x10, 0)
    except Exception: pass


def run_gui(cfg, url):
    """Compact status bar. Shows status only; expands the log when something needs attention."""
    import tkinter as tk
    import tkinter.font as _tkfont
    BG="#080A0E"; SURF="#161B23"; CARD="#0F131A"
    INK="#ECE7DD"; INK2="#C2BBAD"; DIM="#867F71"; FAINT="#564F44"
    GOLD="#DEC79C"; GOLD2="#EFDDBC"; REC="#FF5470"; TEAL="#52C3AC"; LINE="#1F252E"; LINE2="#2B323C"
    W=466
    _load_recorder_fonts()
    root=tk.Tk(); root.title("myPENTA"); root.configure(bg=BG)
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
    SG  =_pick("Space Grotesk","Segoe UI")
    SG_M=_pick("Space Grotesk Medium","Space Grotesk","Segoe UI Semibold","Segoe UI")
    SG_S=_pick("Space Grotesk SemiBold","Space Grotesk","Segoe UI Semibold","Segoe UI")
    PLEX=_pick("IBM Plex Mono","Consolas","Segoe UI")
    UI=SG; SEMI=SG_S; MON=PLEX
    BASE_H, SET_H, LOG_H = 160, 156, 210
    root.geometry(f"{W}x{BASE_H}"); root.resizable(False, True)
    st={"log":False,"settings":False}
    _CAPLBL={"auto":"Auto","wgc":"WGC","ddagrab":"DXGI","gdigrab":"GDI"}
    _ENCLBL={"auto":"Auto","nvenc":"NVENC","x264":"x264"}
    _SCLBL={"auto":"Auto","source":"Source","1080":"1080p","720":"720p","480":"480p"}

    # === Top accent: a thin line turns red while recording (visible even if the window is half-covered) ===
    topacc=tk.Frame(root,bg=BG,height=2); topacc.pack(fill="x")

    # === Status line: dot + status + sub (left) | quality preset toggle + cloud (right edge) ===
    # 앱 이름 'myPENTA'는 OS 타이틀바에 이미 있어 상단 헤더는 제거. Cloud 상태는 맨 오른쪽.
    midf=tk.Frame(root,bg=BG); midf.pack(fill="x",padx=17,pady=(9,0))
    dot=tk.Canvas(midf,width=7,height=7,bg=BG,highlightthickness=0); dot.pack(side="left",pady=(5,0))
    did=dot.create_oval(1,1,6,6,fill=DIM,outline="")
    status_lbl=tk.Label(midf,text="Starting\u2026",bg=BG,fg=INK,font=(SG_M,12)); status_lbl.pack(side="left",padx=(8,0))
    sub_lbl=tk.Label(midf,text="",bg=BG,fg=INK2,font=(SG,8)); sub_lbl.pack(side="left",anchor="s",padx=(7,0),pady=(0,2))
    _cs=cloud_state()
    _cmap={"cloud":(GOLD2,"\u2601 Cloud"),"readonly":(GOLD,"\u26a0 Key needed"),"local":(INK2,"\u25cf Local")}
    _cc,_ct=_cmap.get(_cs,_cmap["local"])
    # 맨 오른쪽(side=right를 먼저 pack해 우측 끝에 고정), 그 왼쪽에 프리셋 토글.
    cloud_lbl=tk.Label(midf,text=_ct,bg=BG,fg=_cc,font=(SG_M,8)); cloud_lbl.pack(side="right",anchor="s",padx=(10,0),pady=(0,2))
    opt_lbl=tk.Label(midf,text="",bg=BG,fg=INK2,font=(PLEX,8),cursor="hand2"); opt_lbl.pack(side="right",anchor="s",pady=(0,2))
    opt_lbl.bind("<Button-1>",lambda e: toggle_settings())
    opt_lbl.bind("<Enter>",lambda e: opt_lbl.config(fg=GOLD2 if st["settings"] else INK)); opt_lbl.bind("<Leave>",lambda e: opt_lbl.config(fg=GOLD if st["settings"] else INK2))
    tk.Frame(root,bg=LINE,height=1).pack(fill="x",padx=17,pady=(8,0))

    # === Log area (hidden until needed) ===
    logwrap=tk.Frame(root,bg=BG)
    errbar=tk.Label(logwrap,text="",bg="#3A1E18",fg="#FFB4A6",font=(UI,9),anchor="w",padx=11,pady=6,justify="left",wraplength=W-44)
    logtxt=tk.Text(logwrap,bg="#0C0D10",fg=DIM,font=(MON,9),bd=0,padx=11,pady=8,height=8,wrap="word",state="disabled")

    # === Callbacks ===
    def open_gallery():
        try: open_app(url)
        except Exception: pass
    def open_folder():
        try:
            if sys.platform=="win32": os.startfile(REC_DIR)
        except Exception: pass
    _TRAY={"icon":None,"show":False,"quit":False}
    def do_quit():
        try:
            if _TRAY.get("icon"): _TRAY["icon"].stop()
        except Exception: pass
        try: root.destroy()
        except Exception: pass
        os._exit(0)
    def _on_close():
        # ✕ → 트레이로 최소화(트레이 가능할 때). 트레이가 없으면 그냥 종료.
        if _TRAY.get("icon"):
            try: root.withdraw()
            except Exception: pass
        else:
            do_quit()
    def _tray_run(ic):
        try: ic.run()
        except Exception as e: log(f"Tray stopped: {e}")
    def _make_tray():
        # 시스템 트레이 아이콘(윈도우 전용). pystray/Pillow가 없으면 조용히 비활성 → ✕가 종료.
        if sys.platform!="win32": return
        try:
            import pystray
            from PIL import Image
            import io as _io, base64 as _b64
            img=Image.open(_io.BytesIO(_b64.b64decode(_PENTA_ICON)))
            def _open(i=None,it=None): _TRAY["show"]=True
            def _gal(i=None,it=None): _TRAY["show"]=True; _TRAY["gallery"]=True
            def _qt(i=None,it=None): _TRAY["quit"]=True
            menu=pystray.Menu(
                pystray.MenuItem("Open myPENTA", _open, default=True),
                pystray.MenuItem("Open gallery", _gal),
                pystray.MenuItem("Quit", _qt))
            ic=pystray.Icon("myPENTA", img, "myPENTA \u2014 auto-recording", menu)
            _TRAY["icon"]=ic
            threading.Thread(target=_tray_run, args=(ic,), daemon=True).start()
        except Exception as e:
            log(f"System tray off ({e}); window close will quit instead.")
    def _save_cfg():
        try: _atomic_write_json(CONFIG_PATH, cfg)
        except Exception as e: log(f"Failed to save settings: {e}")

    # === Settings panel (collapsible) ===
    PANEL="#0B0C0F"
    optwrap=tk.Frame(root,bg=PANEL,highlightbackground=LINE,highlightthickness=1)
    tk.Label(optwrap,text="RECORDING SETTINGS",bg=PANEL,fg=INK2,font=(SEMI,8,"bold")).pack(anchor="w",padx=15,pady=(12,6))
    SCALE_OPTS=[("Auto (best)","auto"),("Source","source"),("1080p","1080"),("720p","720"),("480p","480")]
    ENC_OPTS=[("Auto (GPU first)","auto"),("GPU \u00b7 NVENC","nvenc"),("CPU \u00b7 x264","x264")]
    CAP_OPTS=[("Auto","auto"),("WGC (fullscreen)","wgc"),("DXGI","ddagrab"),("GDI","gdigrab")]
    MON_OPTS=[("Auto","auto"),("Monitor 1","0"),("Monitor 2","1"),("Monitor 3","2")]
    def opt_row(label, opts, key):
        row=tk.Frame(optwrap,bg=PANEL); row.pack(fill="x",padx=15,pady=3)
        tk.Label(row,text=label,bg=PANEL,fg=DIM,font=(UI,9),width=8,anchor="w").pack(side="left")
        cur=str(cfg.get(key,"auto")); m={l:v for l,v in opts}
        curlbl=next((l for l,v in opts if v==cur), opts[0][0])
        var=tk.StringVar(value=curlbl)
        def on_sel(lbl,k=key,mp=m,lb=label):
            cfg[k]=mp[lbl]; _save_cfg(); log(f"Setting: {lb} \u2192 {lbl} (applies to next recording)")
        om=tk.OptionMenu(row,var,*[l for l,_ in opts],command=on_sel)
        om.config(bg="#181B21",fg=INK,font=(UI,9),activebackground="#23272F",activeforeground=INK,relief="flat",bd=0,highlightthickness=1,highlightbackground=LINE2,anchor="w",padx=11,pady=4,cursor="hand2")
        try: om["menu"].config(bg=SURF,fg=INK,activebackground=GOLD,activeforeground="#080A0E",font=(UI,9),bd=0,activeborderwidth=0)
        except Exception: pass
        om.pack(side="left",fill="x",expand=True)
    opt_row("Quality",SCALE_OPTS,"scale")
    opt_row("Encoder",ENC_OPTS,"encoder")
    tk.Label(optwrap,text="Auto = best quality, GPU-accelerated so your game stays smooth",bg=PANEL,fg=FAINT,font=(UI,8),wraplength=W-50,justify="left").pack(anchor="w",padx=15,pady=(6,12))

    # === Panel toggle + resize ===
    def _resize():
        h=BASE_H+(SET_H if st["settings"] else 0)+(LOG_H if st["log"] else 0)
        root.geometry(f"{W}x{h}")
    def set_log(open_):
        if open_ and st["settings"]: set_settings(False)
        st["log"]=open_
        if open_:
            logwrap.pack(fill="both",expand=True,padx=12,pady=(0,8))
            if LAST_ERR.get("msg"): errbar.config(text="\u26a0 "+LAST_ERR["msg"]); errbar.pack(fill="x",pady=(0,5))
            else: errbar.pack_forget()
            logtxt.pack(fill="both",expand=True)
        else:
            logwrap.pack_forget()
        log_btn.config(fg=GOLD if open_ else ICON_FG, highlightbackground=ICON_ON if open_ else ICON_BORD)
        _resize()
    def set_settings(open_):
        if open_ and st["log"]: set_log(False)
        st["settings"]=open_
        if open_: optwrap.pack(fill="x",padx=13,pady=(3,2)); opt_lbl.config(fg=GOLD)
        else: optwrap.pack_forget(); opt_lbl.config(fg=INK2)
        set_btn.config(fg=GOLD if open_ else ICON_FG, highlightbackground=ICON_ON if open_ else ICON_BORD)
        _resize()
    def toggle_log(): set_log(not st["log"])
    def toggle_settings(): set_settings(not st["settings"])

    # === Toolbar: primary actions (Gallery / Open folder) + secondary icons (Settings / Log). Quit = window close (X). ===
    ICON_FG="#9A9282"; ICON_BORD="#232A34"; ICON_ON="#4A4131"
    def add_tip(widget, text):
        tip={"w":None}
        def show(_e):
            if tip["w"] or not text: return
            try:
                x=widget.winfo_rootx()+widget.winfo_width()//2-len(text)*3
                y=widget.winfo_rooty()-23
                w=tk.Toplevel(widget); w.wm_overrideredirect(True); w.configure(bg=LINE2)
                tk.Label(w,text=text,bg="#1B2129",fg=INK,font=(SG,8),padx=7,pady=2).pack(padx=1,pady=1)
                w.wm_geometry("+%d+%d"%(max(0,x),max(0,y))); tip["w"]=w
            except Exception: pass
        def hide(_e):
            if tip["w"]:
                try: tip["w"].destroy()
                except Exception: pass
                tip["w"]=None
        widget.bind("<Enter>",show,add="+"); widget.bind("<Leave>",hide,add="+")
    def tbtn(parent, text, cmd, gold=False):
        fg=GOLD if gold else INK2; fgh=GOLD2 if gold else INK
        bord=ICON_ON if gold else LINE2; bordh="#6A5C44" if gold else "#3A434F"
        b=tk.Label(parent,text=text,bg=BG,fg=fg,font=(SG_M,9),padx=12,pady=6,cursor="hand2",
                   highlightthickness=1,highlightbackground=bord,highlightcolor=bord)
        b.bind("<Button-1>",lambda e: cmd())
        b.bind("<Enter>",lambda e: b.config(fg=fgh,highlightbackground=bordh))
        b.bind("<Leave>",lambda e: b.config(fg=fg,highlightbackground=bord))
        return b
    def ibtn(parent, glyph, cmd, statekey, tip):
        b=tk.Label(parent,text=glyph,bg=BG,fg=ICON_FG,font=(SG_M,12),padx=8,pady=3,cursor="hand2",
                   highlightthickness=1,highlightbackground=ICON_BORD,highlightcolor=ICON_BORD)
        def _act(): return st.get(statekey)
        b.bind("<Button-1>",lambda e: cmd())
        b.bind("<Enter>",lambda e: b.config(fg=GOLD2 if _act() else GOLD,highlightbackground="#3A434F"))
        b.bind("<Leave>",lambda e: b.config(fg=GOLD if _act() else ICON_FG,highlightbackground=ICON_ON if _act() else ICON_BORD))
        add_tip(b,tip)
        return b
    bar=tk.Frame(root,bg=BG); bar.pack(fill="x",padx=15,pady=(9,11))
    tbtn(bar,"Gallery",open_gallery,gold=True).pack(side="left")
    tbtn(bar,"Open folder",open_folder).pack(side="left",padx=(8,0))
    log_btn=ibtn(bar,"\u25A4",toggle_log,"log","Log"); log_btn.pack(side="right")
    set_btn=ibtn(bar,"\u2699",toggle_settings,"settings","Settings"); set_btn.pack(side="right",padx=(0,8))
    root.protocol("WM_DELETE_WINDOW",_on_close); _make_tray()

    def _prep_and_run():
        global FFMPEG
        try:
            if not FFMPEG: FFMPEG=ensure_ffmpeg()
        except Exception as e:
            log(f"Tool setup issue: {e}")
        if not FFMPEG:
            log("\u26a0 ffmpeg setup failed \u2014 check your internet connection and restart."); return
        recorder_loop(cfg)
    threading.Thread(target=_prep_and_run,daemon=True).start()

    _rec={"since":None,"blink":False}
    def poll():
        appended=False
        for _ in range(150):
            try: line=GUI_Q.get_nowait()
            except Exception: break
            if st["log"]:
                logtxt.config(state="normal"); logtxt.insert("end",line+"\n"); appended=True
        if appended:
            n=int(logtxt.index("end-1c").split(".")[0])
            if n>300: logtxt.delete("1.0",f"{n-300}.0")
            logtxt.see("end"); logtxt.config(state="disabled")
        # 트레이 메뉴(다른 스레드)에서 온 요청을 tkinter 스레드인 여기서 안전하게 처리
        if _TRAY.get("quit"): do_quit()
        if _TRAY.get("show"):
            _TRAY["show"]=False
            try: root.deiconify(); root.lift()
            except Exception: pass
            if _TRAY.pop("gallery", False): open_gallery()
        _rng=REC_STATE.get("recording"); _now=time.time(); _up=REC_STATE.get("uploaded_at",0)
        topacc.config(bg=REC if _rng else BG)   # 녹화 중 상단 빨간 라인
        if _rng:
            if _rec["since"] is None: _rec["since"]=_now
            _rec["blink"]=not _rec["blink"]
            dot.itemconfig(did,fill=(REC if _rec["blink"] else BG))
            _el=int(_now-_rec["since"]); _mm,_ss=divmod(_el,60)
            status_lbl.config(text="Recording",fg=REC); sub_lbl.config(text="%d:%02d"%(_mm,_ss),fg=INK2)
        elif _up and (_now-_up < 5):   # 업로드 완료 토스트(5초)
            _rec["since"]=None; _rec["blink"]=False
            dot.itemconfig(did,fill=TEAL); status_lbl.config(text="Uploaded \u2713",fg=TEAL); sub_lbl.config(text="\u00b7 added to your gallery",fg=INK2)
        else:
            _rec["since"]=None; _rec["blink"]=False
            dot.itemconfig(did,fill=GOLD)
            if REC_STATE.get("ready"):
                status_lbl.config(text="Ready",fg=INK); sub_lbl.config(text="\u00b7 auto-records",fg=INK2)
            else:
                status_lbl.config(text="Preparing\u2026",fg=INK); sub_lbl.config(text="\u00b7 setting up tools",fg=INK2)
        ea=(REC_STATE.get("encoder") or "").lower()
        if "nvenc" in ea: enc="NVENC"; is_sw=False
        elif ("x264" in ea) or ("264" in ea): enc="x264"; is_sw=True
        else:
            ec=str(cfg.get("encoder","auto")).lower()
            if ec=="x264": enc="x264"; is_sw=True
            else: enc="NVENC"; is_sw=False
        try: _sh=root.winfo_screenheight()
        except Exception: _sh=1080
        _scl=str(cfg.get("scale","auto")).lower().rstrip("p")
        if _scl in ("source","native","full","off","0"): th=_sh
        elif _scl in ("1080","720","480","1440"): th=int(_scl)
        else: th=(720 if is_sw else _sh)
        if th>_sh: th=_sh
        opt_lbl.config(text=f"{th}p \u00b7 {enc}")
        if LAST_ERR.get("msg") and (time.time()-LAST_ERR.get("t",0)<8):
            if not st["log"]: set_log(True)
            else: errbar.config(text="\u26a0 "+LAST_ERR["msg"])
        root.after(500,poll)

    try: root.update()
    except Exception: pass
    try:  # 내용에 맞춰 창 높이 자동 — 푸터(Settings/Log/Quit)가 빈 공간 없이 바로 아래 붙도록
        root.update_idletasks(); _rh=root.winfo_reqheight()
        if _rh>=60: BASE_H=_rh; root.geometry(f"{W}x{BASE_H}")
    except Exception: pass
    if sys.platform=="win32": _hide_console()
    poll()
    try: root.mainloop()
    except Exception as ex: log(f"GUI closed: {ex}")


def _print_status():
    s = sb_cfg(); st = cloud_state()
    print("\n" + "=" * 50)
    print("  myPENTA 상태 점검")
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
    print("=" * 56); print(f"  myPENTA — 리그 오브 레전드 자동 녹화 — 모드: {mode}"); print("=" * 56)
    _cst = cloud_state()
    if _cst == "cloud":
        log(f"☁ Cloud ON — saving & sharing via Supabase({_sb_base()}).")
    elif _cst == "readonly":
        log("⚠ Cloud read-only — supabase.service_key in config.json is empty. Fill it and restart to enable uploads.")
    else:
        log("● Local mode — saved on this PC only. (Fill supabase in config.json to enable cloud)")
    if mode in ("all", "recorder"):
        if not use_gui:               # GUI면 창부터 띄우고 백그라운드에서 받음(첫 실행이 멈춘 듯 안 보이게)
            FFMPEG = ensure_ffmpeg()
            if not FFMPEG:
                _safe_input("\nffmpeg가 없어 녹화를 할 수 없어요. 엔터로 종료..."); return
    if mode in ("all", "server") and not use_gui:
        if not FFMPEG: FFMPEG = ensure_ffmpeg()
    url = (cfg.get("gallery_url") or "https://mypenta.netlify.app/").rstrip("/")
    if mode == "all":
        log(f"Gallery → {url}")
        try: open_app(url)
        except Exception: pass
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
