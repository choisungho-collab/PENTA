#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
myPENTA — 리그 오브 레전드 자동 녹화 (한 번 실행하면 다 됨)
=====================================================
이 파일 하나만 실행하면:
  · 필요한 파이썬 패키지 자동 설치
  · ffmpeg(레코더) 자동 다운로드 (처음 한 번)
  · 게임을 감지해 판마다 자동 녹화, Riot 공식 기록으로 전적 분석
  · 영상+전적을 Supabase에 업로드 → 웹 갤러리에 자동 등록, 브라우저 자동 오픈

그 다음부턴 리그 오브 레전드를 켜서 게임하면 → 판마다 자동 녹화 → 영상+전적이 갤러리에 자동 등록.
OBS 필요 없음. NVIDIA NVENC 하드웨어 인코딩이라 게임 성능 저하 거의 없음.

실행:  penta_recorder.exe 더블클릭
"""
import os, sys, json, time, socket, subprocess, datetime, traceback, threading, hashlib, secrets

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
        print(f"[setup] Installing Python packages: {', '.join(need)} …")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", *need])
        except Exception as e:
            print("[!] Automatic package install failed. Please run this manually:")
            print(f"    {sys.executable} -m pip install {' '.join(need)}")
            print("Details:", e); _safe_input("\nPress Enter to exit...")
            sys.exit(1)
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
APP_VERSION = "dev"   # 빌드 시 GitHub Actions 가 릴리즈 태그(vX.Y.Z)로 치환. 소스 실행(dev)이면 업데이트 확인 생략.
_PENTA_ICON = "iVBORw0KGgoAAAANSUhEUgAAAIAAAACACAYAAADDPmHLAAAcs0lEQVR42u19eXRc5ZXn737fe7WrZEm2FluWwQJJGGM7bDEYcFjCJGeyT5v0OU3mzEmf4EmHmSwz00tCEkgmPZnTk4ROIAlwSCbpPgngdAhhS9IOXmgTkyEEB9vYBhsveDeWZUtV9d77vu/OH9+rUknWVpIsVcl1dT6OLIlX77177+8u3733A6pUpSpVqUpVqlKVqnTeEY32B4899phcBWBN9V1VHK0CgFW3GSJw9W1UaewIwAwiAh9dd1/qlIitdCNaKhYsx/EBxhjK5nwppahKYQmktaGI6xjXdcy4mWuI/EC/0HXj6hPMTER0Fg+cof/XLxNwD592Y1c5gr8PyJyAEaUxHsIYFtGYk6uflepVSjtsSrvG+UpMxBHXCfpyXiKXDeJExELAlKbZpFmYWieCTwN4BGvWCAC6JB+AeZ2z+8U3lkqwy8xj0mCliDw/EBfOr8smW5r8X65ZP/dHj/9+1bHunn/PxsQAqiLBqNwTqj4dW3fbey//59tvv2m/39Mnd+05nohGXOM4PMb354DZcPcJs/XKD6zOhLzmkp3ACdBsGW+6MxqRfwGgHWCqcrY0y0zgt3xt/iXoPXovgL3TEgUwf3lMsL169WH50EMPBjfcsDK2fddbn2VjPktCzGE2ecGran7p7CEiAWbTKwTun5Vy/8/rr+868YlP3OE+8ECLHtsV7jETEoAxCpEAoOubLryaCPcCuIaZAWYFQJ5jpJnR7gDAGiCHhATYvMasP33y2IF/Dd85T1SxaJIQhOubLrwTxF8nIMlsNECiyvjJFQQi4QCAYb6n++i+u8PfCQBmOgQgL4FU17zgm5LEp40xCCVWVnl2TshYH1EIZvMofPeOkyffOD0RIaAJCo6ob7rg/wpBtxujq1o/dYCghHAcw2Yde+LD3d17eobz8s+FAORtPuqbLviREPQXbLQCyKkyZqqFQDqseZ0OxIe7u/ec7jcXpcH4eKBfNzRecK8Qosr86YsQHGO0Ikk3ioj5AbBKhLwpSalLtdUSgG5oXvBXQsh72Kgq86dXCASzUSTEpfHUQTfbe2ptyKMxowCVqPlmdkv7Fcx6I8AxMKhq88shQoAhEhKM9584+uZTeUWdTBNAANDa2ho3Rn2PQIlQxqrMLwMYsIvBMPelmpvnhBEBTaYACAAmGzj/RQh5FbNRocdfpbIxBaxIyAURE7k7RAUxZs0eS7xfXz9vHrmRPwJcPwEHskrn1hQwgEAZXt5zfN8rY8kPiDEKCYuI819JiNkAc5X5ZWsKmISIOlL83VgVnMZy0VRz85wox7cA3DyB/EGVpgwJKMdkrjh5ZN9ro6HAaJosASDCkY+SEC0AmxnBfArRkrjo+5JzKOXKf0OC4gLiP41FWUcTAA1AEOQqEDOICj5nZS7ur0chgIhA+WfKCwFxhT8jEYNhwB9uaWlJjBYOitGcv4aWBR0gXs7G0DgSR2XmIxWBAAFKawSBskIwwt9WGAnYAsCLfe1eU4zk4xEAwPDNRCJid/lmBvMFEbJZH53trbhqycXIZHKQQswgIWBNRCAhbhntL53R3hoJ+c5wn4lnAvMBQEqBvkwOH33/9ZjfMhu/3fQK0qnEEFjJFerykLAmjZaHDzAuJ1ADcBm0zEZ+MyPxQwRobdBQV4Mbr1mCa69ahLZ5jfADBUEzJrghNgAzL6qpmVs/kiSLkQSjvrW1kYxZwBWb9uUB8SwBcKRENpfD8iu60H5BCxrq0rhpxRJkczk4jhxiO61STQGDQA2RZHThSNHAyFodOK1ElLQvj4hQ2V9CEKQQYAN86NbliLoOtFb40L+7BhHXtcyv+KekPK+YSEgBtI1HAMj+UswGkaxMNRik/QQIElBKYf7c2bhxxVJkcx6yWR/Lr+hE10Wt8PwAUopQCCoeBQxAUIYb7D9Xli4ABD0H1i4aVDBRaPxdRyCX83HjtUswf+5seH4ArTXqa2vw7uuXwfcDOFLaHEHlJ4QYAKRA0zjyACtDuRdyRmR9CRBh4icacfC+d18No7UNbAjw/ADvvekqpGsSYLB1BmeIQ8g8coHuDN3UGQj/AEFKCc8PcEnHfFy19CL0ZXKQRBBEyGRzWNzZhmWXLoTn+XCkKCQ9K90ZHKoh9DwQgIFhnyCCIwWCQOHWGy7HrJokAqVDDWFobRCLunjPjVfAGAPpiNCVwownMaO1P/T+hASYDepqk3j3DcuQ9XwQWeYj3OLIZD3cdO1laJ4zC1obCGnNwEAhqDAUoIkKgECFb4xYIZBSIucHuGLpRehqb0U254VJH7sTKAjI5XwsaG3E8iu7rBlwRH+XQyWv8w8BitNh9h1IYZn9nnddAceRMIbBYW67f9lk2a03XA4pBURRPqBqAirV+RMEKQWU1pjX1IDrr16EbDYHKw88YEkCMtksrr28Exe2NSJQClLSjHEGzz8EIPtwee//uqsXYW5jPXJeUHD+BiwAvq/QUJfGDVcvhucrOFIOIQDnJQJUirELk9Z56CYL5VHXxXtWXg7bvDqcFltnMFABbr3hHUjEo/ZaJAASoSk4+7Mq3QkQMxcAbOjnBwE62ufiHYsXoi+TgxAUov4gBGCbKMpkfVzWtQCXdrTZzKAQMxoCZogA8NnwLwDHEQgCjZtXLMWsmgSU0vZveZgFhlYayUQUt1y3BEppSEdYn4FG+cyqAEwX4/ksYyXC/TA2jFm1Sdy84jLkPB9CjMI3BoQg5HIe3rX8UjTU18AYhhQ2YyjG8PlVAZgQI0tdQ3gpZJnoOhJ+EODyxQvRceFcZHJe2EBlRlwgRjbno31BM668rN2aAcexeQMxnGWd+P2XrQCcG9eEB63Jua4gu98vQwEgItx6w1K4jgAbHjNfmK3W33LdEkhBcCRBCkAinx8o7/dQeB/lhwCTJ/kDGW+ZbwWAwmSPQWtLPVZc2YVM1gMJGsLxG3qRIPRlPVx7RSfmz20AG4bjOJDSFpXYzyop4Tbl76cMTQCXhjSUZ+xQyzKBKM8QASFDTZUC0YiE0hrXXXkJWubUwfNVyKSxQQCFOYGmObNw/VWXQGmNaMSBlAKOJAgZfqYgUEEgaNj7HaqdYiLvajLJGbOqTTLzi6Ppwn+KXhQGVeUU/519oQQmhgwFgcgy33EEoq7V1ptXLIHW/Z4/l6iJWmm869rL8PS6l+E6DkgAShloY8DGooVmBjHZ1HJ+HCIPfGL74/7Usy1DGPh3POQ90MRhUkxUACYzPRtqbJ7BItT0fHcOFcXwyO/W5a+Sh2cCjGEYY0ACCMKX6AiCNgRmCc8LsLhjPpZessDCPxGYS9MqmxPwsLRrAdrbmrB11wEIQQiUBhuGMlxAKmNgkSDMMZCgAc0mRBQym4sEAoX8gykSEBMK1qQJAaZdACjMshF8X6Evk4MjRWGrVVB/sSaFzpsjrdhGIw4cxwEzIxZ1EI1EwMyIx1wk4lEYw0glokil4mDDSNckMCudgOcFWP6ODkSjLrJZD0KIcd21MQbxeBQf+8hKbH7ldcQiDrpP9+H0mSxIEHp7c+gNk0uZrIdsLgARwfN95DzbcaSUgucrAIDSpiBA2hgryKEQgBlKGyQTMUQiTigEVAYmYBJsABHBDxQ6F87Fiis7cLK7Fw11NUin4lDaoKEuiZpEHMoY1KUTSMZj0MYgnYojHotAaYNEPIJEPAKtGbGIi0jEhTGMiCsKQiIEQQhhbXigkM07f+MsaSRByGZtTuDW65eGGmoZl2euHxgIQfD9ADk/gJQ2m5jJ2sqibM7H6d4spBDoy+bQfToDRwicyWTxdncfHClwujeLt7vPoL4uhU0v7cLONw8j4jpgngzlE9ONAJakFDh8rBudC1vwiT+/Gb2ZHLQ2tkw7rwUADJtCD7LRBmYA7Nv9XQuTBkSW0Z4fFJAmf528uZnYW7Sfnc35yGS98LoDUS1vXiIRB7GYCzBQm0oUzIEggpBho46wlckoMn3aGEgpkErE8NAjv8XPnnkRUk6dbz4lPgAzIIVAb8bDp774Q7z4xzfw5c/8BzhSIpP14Diy31UIHbyC/aNip5GK/mYgwhS8h6JfME9SyEkYooGUBnyGYYbWRc880AMMo34e8JxKaSTiUSit8Zl7foQf//x5pGsScBxZdO8V7wP0M8N1JBpn1+Knv3wBew8exze/cDva5s3GqZ4MHEcAxYwfcvBl+aZdaRCvaMA34iyfSCmDhroU9h88gc997Z/xuz+8jsbZtdAh6s3IVDAzQymNhroU/vDqm7jtzn/E+s3b0TAraR/cmCLvmIfds6m8FXr2bH0IrQ0aZiWxfvN23HbnP+IPr76JhroUlNKThlplJAB0lv4GSqMmGUPPmQw+edcP8OAjzyGdikMQQelRduwqdYGhtIYgQjoVx4OPPIdP3vUD9JzJoCYZ669SHubdVbwJGGwSA6XhSAdCEP7Xd5/AG3uP4POf+hDisYj1C+TMKlVQyiARj8IPFD7/D49gzTMvIpmIwRi2oSFPj4GbIgEYaM/zQqCMgQNCOpXAz579Pfa+dRxf+ewqtC9oxKnTmUK+oDL79MN7DuP7WekEdu87hi99aw1eevVNpFMJBEpBGR6G+VPzvNOqZswMbRh+ECBdE8eWHfvxl3/7INZv3o762qQN90K/oPJgH+AwZ1Bfa+39X/7tg9iyYz/SNXH4QQA9IOs3PTRM39gFAthnEjV1l5MQHwjvUkwcBWgYXCAYbRCNuMj5Pn618U9wHIF3LmuH1laDKq1LRxuGIyWSiQgeXrMeX/3OL+AHAVzHge8rGLahI3i4yoYJkyESgpnXZ86c3JDnaYkmQIZFked2OpzNhxP8QMN1bSr4mw//Crv3HcPfrH4fkrEIejNhvqCsw0EK7b1GKhFFJufjrm/8Ak+sfRnJeBTaGPiBhmHqT/XSUGoxSXczZBXTNDuBRccMDfIJGIaAINAw0iCViOKJtS9j9/6j+Mpn/gwdFzSj+0yfLdUuQxHIj1FSWqOuJolde4/gS/f+DFt3HUQqYZ0/rW3d0XTa/DLyAc5ut2Bj07xKM3K+QjIRxY7dh7H6roex9oWtqE8nw1y8Ka9QEVy4r/p0Emtf2IrVdz2MHbsPI5mIIucrKM2hT1M+zJ8mBBglOsinVw3geQoR10FvxsPf/MOj2HPgGD7+Zyvh+T4CZSAFTWt8kP9srRmuIxCNRPDAI8/hgUfWQRAh4jrwPAXDXMjulRPzy0AAhg8RDTOYAM9XcF0BV0rc/09r8cbeI/jr1e9DOhmzfoGURbvsNMWsBwJt7f3pvhzu+fbj+PXzW8MdTB3aexQ6j1BmzC8TAThbCAb4BSAEysAwkEzE8K+btuGtI9344p0fRMeFzTjTmy3a7+cp1X9jDGpr4tj15hF89b4n8NruQ0gmYsj5QZjTL2/mT3seYLQwMW8OjGFozfC8AIl4DHsOHMfn/v4nWLd5O+LxCIwxYy74nKxli0UiWLd5Oz739z/BngPHkYjH4HmBdfaGjfHL65SdMsy3Dtw7yOeAjDHQzPD8AK4jkfMCfO3+J/GbjVuRiEUKG0lTsYwxSMQi+M3Grfja/U8i59l78vwAOhQO5uG6F8qLyvTEr6H9grzm+YFGJOJAKY1AaTsYlRlMUzPMzJaO2/0Mwzbh4wdBERKVn7NXQQgw/Auz40+tNHiBQjIZxdKuVvi+mtJMIZEtG1/a1YpkMgovUMgXvrApX3tf+QKAvAAQPC9AW3M9mman++v+pyjuJ9jopGl2Gm3N9fA8W5I2/I5exQrAdA7JAQY3URWnOIPA4NKL5yEacWCMHqbl+1wtwBjbLHLpxfMQBGZAyRiP8ixTu0SlIsBQOhQWYQJwXYllXfOhtS7q+pm6ENAmgDSWdc2H69pchBWCypoqNLITKMsnauHQ9pKwJ320zE5j4fzZ8ML6+6neViUieJ7Cwvmz0dRQg8MnTtupYqaM9ilobBhfMQhAxBDCDn24pL0FDbNS8JUaFDNO0QLgK4WGWSlc0t6CINC2J4G4ohCgouquCFQ41GFJV6sN/4wBsxm173/SFxtw2J62pKsVCGcMV9pYOWcsFmD6QH+gpObHu6VTUSzpmIfAH+rAp9LieQDjvgYRIfAVlnTMQzoVg+9rCApPcz7bgJVBHFXJJoAAIQUCpdHWUo/W5jp4flAY+VrKQjgf2A5/ELaDOPx5KdehcNJ4a3Md2lrqESgNEQ6arpqAcxABSBJQxmBxxzwkwx230uoFYTt7tS046e3L4eSpPqSTMSht6/dKvZ7SGslYBIs75kEZAxnOl6WqAEyyEIQFwo4UWNbVansDSwz/tNYQglCbiuHlbfvwpe88hS/c+wTW/34XapJROA6F8wRKCweZDZZ1tfaPma8gz6pM9wLOPuRRhI2Us+tS6FjQiGwh+8ZjupoxBjWJGM705XDfzzfhyfWvhlM+gK99/1m88MpufPwjK9DUkEJPr1c4YGIs+JT1AnQsaMTsuhS6ezJh0ygP6kstz9L2itgMsgc+CfiBwsVtjWhqqEEm59uIgEe+jNYGriORTsWwectefO/R5/HG/uOFIk2lbOfyMxu24ZXXDuITq1bg5uWdyHkB/ED1d+ry8HcaBApNDTW4uK0Rm17eDdd1YPTgvUCqVASY/FFIY0z79L+2cPSbMYwlnXPhSGF79OVQL5YLyGC0QU0yhjN9Hh5asw6Pr90Cw3a+QM4L+lvJAURcF0dOnMbd9z2N3/1xD+647To0NqTQ05srzCMa0Npb9HnGMBwpsKRzLja+9Aai+YknTNO8HUyViAA8ZLjFDCRiERv+qeLdPx7S1rtSIl0Tx+Yte3H/Tzdi197jSMYjYGOQ8wKY/p0l2NO17KyCiOvg6Y3b8MrOg1h92wrcsrwTOT+A79upocOZqEDZcDARixSlhXlYwa6agJIygIQg0GibW4cFc+sLu3/F9j8/AV4bg5pk1Gr9jzfh8bV/gjaMRMyF7ytozlfmDhzjRAYwZEe3xKMujr99Bvfc/yw2b3kTd6xagcb6GpzuyxX8kcHg7vkKC+bWo3lOGvsPd4dHz5X/ebtlLwAQ9sCHjBfg0ouaUVsTw+ne8LDnQRrsOhKpRAyb/7QP333keezaewzJUCNzvjqrWIMHexzMYM3IhZAejUg8vWE7Xtl5EP857xv4AfxAFx02bbU6UBq1NTEsuqgZr++zaKMFyv7APWfUIHE6NoO4H1qL3ZClnfMGzfvrrxJKJ2M4eTqD+3+6EU9v2AbDjGQ8Ai+wQ5nMcJU6+Z+Fn6UZEGAE2o6Di8ddHD/Zi7u/9yx+t2Uv7lh1DZrqa9DTN9g3sCHhss55+OVzr/YPM6EBclp2qUCnbHG/yL4qbZBOxbCovclm/5BvLM1rfQQbX9qN7z/2b9h76CQSsQigDXKeAoORPyaAR0obFDGJw5FuzBbaHWFnDz79/DZs2fEW7rjtWtyyvCv0DWykYM1AgEXtTUinYsiFVUqFYV9ctgBbvsRhCJjzFC6Y24B5c2rtyDW2jl46GUM26+PrD/8WX/j2Uzh4tAfxWAR+oOErHQ6WGoL5I9WgFCcDARhtBdDzFeKxCI519+Hu7/4aX33gVzjdm0VtKgatba2a5yvMm1OLC+bW2zFxKPIVqBIFoHDCBk0954umffmBwpLOFkSjjj3mXdps3ob/9wY++T/X4OdrtyDiSpAgeL4q1OQbFJWRFY8eGvaIsSJt5X4kMPk2ds86n7HQN1h9z2P49aYdSCejkI6A7ytEow6WdM6FHxRtVJXxVPlhTMAGqzCOPE5sADBN126WCYdLLeucB88PUJuKoftMBt/68Xo8tWE7pCSk4tGwC6e/946HgPbRhTnkfrEQDJg0Z6d5KENIxiN4u7sPX7zvGfzbH/fgrz66Ao31Kfi+wrLOeXAdOaXDnoZ4FlsmSebYuH0Ax+CEsadQi2kJYsNu4YbaJC5Z2Ih41MVvXtiJ7/zkeew/cgrpZAwcQi8PLsosifFDOCD5E1eLrhOOKQQZwAsUpBBIxCN4euN2/GH7W/jUn6/A+1ZeiksWNqK+NolTZ7JwHIFpkgOypz+Lt0OlLskE2PG1TvAWGNkpPPd+wJckiUxO4erL2pCIurjr28/gr7/xFI6c6EU6YXfwlGIwU8GVJw5XWD9ov8Q4Pl0MvEZ43UL1ryFozQgCu8dwsieLL3z7WfyPbzyJiCPxziVtyOYUBMlB9zIlX0yAYGbDvjhQzNOSEOCw1sea4B4QRF1TWnMXQjCHo2CzuQAf/9JjePX1w2iYlQQzI1Dm7JzcuLW+BDTIfxuaBgIQKANHCtQko3hq42t4ff8JtDXPQsSV9qCKaXLvmM0p0sFujLCbQaM4iKa5retRQXSbMVoBNEVhY/8LJyLkfDuEOR5zrcc9WUHweFPUI8T1UgrkPAVjDGIR12Yr6Vzd0/DuOwkh2PALRw7suB4jTKUfIQpYaX/H5sVpi2HCap9YxEXUdaCVGcPRO+cqc1V0XRoUrRQtrQwijhyC+VMaRpnw5f3eQv9KORwCjKDRGwwAKCHXOVb75ZTbgIIrw2f9eGiFoqm7NxoJIHiI25lKSSABMJjwnP13I48XJwmAbGnregHAlTwp08ImAL1TBveTeX9Tfm9MIDLgA35vcFl3956ekXKRozBzpQSgAPwLTXz2+gShdwJnpE/r/U317bAhKSAgngyZL0eS0lEEwJoBUvInhk03EYlzcr5ZdU1mS6UwRgcM+cOxQNRocG4AyEOHth0gNo+RkATmMt/gPK9Jk5BEoLVHDmx9KR/JTUQA8hJEpOhbhs0ZGrrUpUplQszQLOjrY3VAxiIABoA4dGjnTjDfT0KGUkXVt102RABDCyEk2Dx2ZO9rG0PejlrjPtbEjgEgohT7357xP0IkOpjZVFYF/MxWfBJCGMbbEOLvSvE+x8pABoB9+7acMsCnrGRx5R+dPXNwX5MQxMb89yN7X9s3Ftufp1KSOwxA9vWc2J2qbSQh5U3MRldRYNqZr4R0HMP64aP7d34FWCWB7WNubxpHdm+V7O3ZsCFVO2eRkPIyZqOqQjBt3FdCOo5ms8kkxe2Z48cVsL0kVB6HAGwHAESd+l8JB8uFkO1sTACaylRxlQBWJKQDxjZfqw++vXvn2xhH9eF4XXkCwHULF9bGVORxIeSNRisFIqfKmCnSfCEdw2YbBfK9hw5tO1CK3Z8gAvQ7kLnu7pzbkP6FNPJiIeViZtYTFKwqjeaHMZs87Isg+PChQzsPhHwcV4JOTuhmQiHo7TmxpiY9xyWilbYhhpU9aqRKk+nsEZEU0hHMeMjvNf/x2LHXj49X8zGJmlrYHZ97Yef7weJbRKLdGI1QEGQVESYW4tnmaEnMfARMnz+0b/sPi8L4CaXmJ9Nxk2dOvb0jXlfzKLGMA7RMSOEycx4RqqahJHRlDZAQ0hFh9cFPpRYfO7h/+3NFfOPJ0t5JolUSWKMBoPnCjqvIOP8N4A8IKePhNC+GTU8KDGyeOg9lY0DLkE2q2eMRJBERkYAxRoPoWcP6m0f37VxXpLR6su7iXNVOFfLQTa1di6UUH2Pgg0ToJBJhV29+nr5tPKiARtrJfUP93SgC1F81bIdYmf1M9JRm80/H9u3YXAT3k559PZdql3cCDQA0NS1JykRwjWHcLEDLDfMiQdRARHKIs9NmvvKHr8aeh2F6iMRrAL1IpJ9zdGbT/v37u4t4RDhHfcZT8doFsIrypiFP6dZF9WmX2pVGGwluYJgmZpZENPORwIBBdEwQThI7+5WkPUf3/OnEICbnK3lmTP0F2YdaWU0WDUsrHUzxfE6aZoEI18rzNDrYMGKBe5WqVKUqValKVapSlap0Tuj/A+fc7FCYmCl2AAAAAElFTkSuQmCC"
REC_STATE  = {"rec": False, "text": "Idle", "game": None}   # 실시간 녹화 상태(웹 표시용)
for d in (DATA_DIR, UPLOAD_DIR, REC_DIR): os.makedirs(d, exist_ok=True)
FFMPEG = None
CFG    = {}

import queue as _queue
GUI_Q = _queue.Queue(maxsize=4000)
REC_STATE = {"recording": False, "encoder": "", "ready": False}
LAST_ERR = {"msg": "", "t": 0.0}
_LOGFILE = {"p": None}
RECORDER_LOG = os.path.join(DATA_DIR, "recorder.log")
_log_lock = threading.Lock()
_log_n = [0]
def _log_to_file(line):
    """모든 로그를 파일에 남긴다 — 창이 꺼져도(증발) 마지막까지의 흐름을 볼 수 있게. 2MB 넘으면 뒤 절반만 유지."""
    try:
        with _log_lock:
            _log_n[0] += 1
            if _log_n[0] % 200 == 1:
                try:
                    if os.path.isfile(RECORDER_LOG) and os.path.getsize(RECORDER_LOG) > 2097152:
                        _old = open(RECORDER_LOG, encoding="utf-8", errors="replace").read()
                        open(RECORDER_LOG, "w", encoding="utf-8").write(_old[-1048576:])
                except Exception: pass
            with open(RECORDER_LOG, "a", encoding="utf-8", errors="replace") as f:
                f.write(line + "\n")
    except Exception:
        pass

def log(m):
    line = f"[{datetime.datetime.now():%H:%M:%S}] {m}"
    try: print(line, flush=True)
    except Exception: pass
    _log_to_file(line)
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

# ===================== 크래시 로그 (전역 excepthook) =====================
CRASH_LOG = os.path.join(DATA_DIR, "crash.log")

# 네이티브(C/Rust) 크래시도 스택을 남긴다 — windowed 빌드는 stderr 가 없어 세그폴트/패닉이 로그 없이 증발하므로 파일로 덤프.
#  (windows_capture 세션 중지 등 확장 모듈 크래시는 파이썬 excepthook 이 못 잡음 → faulthandler 로만 흔적을 남길 수 있다.)
try:
    import faulthandler as _faulthandler
    _fh_file = open(CRASH_LOG, "a", encoding="utf-8", errors="replace")
    _fh_file.write("\n----- faulthandler armed | %s | %s -----\n" % (datetime.datetime.now().isoformat(timespec="seconds"), APP_VERSION))
    _fh_file.flush()
    _faulthandler.enable(file=_fh_file)
except Exception:
    pass

def _write_crash(exc_type, exc, tb, where="main"):
    try:
        txt = "".join(traceback.format_exception(exc_type, exc, tb))
    except Exception:
        txt = "%s: %s" % (getattr(exc_type, "__name__", "?"), exc)
    try:
        try:   # 1MB 넘으면 뒤 절반만 남김(무한 성장 방지)
            if os.path.isfile(CRASH_LOG) and os.path.getsize(CRASH_LOG) > 1048576:
                _old = open(CRASH_LOG, encoding="utf-8", errors="replace").read()
                open(CRASH_LOG, "w", encoding="utf-8").write(_old[-524288:])
        except Exception: pass
        with open(CRASH_LOG, "a", encoding="utf-8", errors="replace") as f:
            f.write("\n===== %s | %s | thread=%s =====\n%s" %
                    (datetime.datetime.now().isoformat(timespec="seconds"), APP_VERSION, where, txt))
    except Exception:
        pass
    try:
        log("CRASH (%s): %s - details saved to crash.log" % (where, getattr(exc_type, "__name__", "?")))
    except Exception:
        pass

def _hook_main(exc_type, exc, tb):
    _write_crash(exc_type, exc, tb, "main")
    try: sys.__excepthook__(exc_type, exc, tb)
    except Exception: pass

def _hook_thread(args):
    _write_crash(args.exc_type, args.exc_value, args.exc_traceback,
                 getattr(getattr(args, "thread", None), "name", "thread"))

sys.excepthook = _hook_main
try: threading.excepthook = _hook_thread   # 데몬 스레드가 조용히 죽는 것 방지 — 전부 crash.log 에 남김
except Exception: pass

# ===================== 1. 설정 (자동 생성/탐지) =====================

def free_port(pref=8000):
    s = socket.socket()
    try:
        s.bind(("0.0.0.0", pref)); s.close(); return pref
    except OSError:
        s2 = socket.socket(); s2.bind(("0.0.0.0", 0)); p = s2.getsockname()[1]; s2.close(); return p

def _screen_size():
    """기본 모니터 작업영역(작업표시줄 제외) (left, top, width, height) px. 실패하면 None."""
    try:
        import ctypes
        u = ctypes.windll.user32
        class _R(ctypes.Structure):
            _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long), ("r", ctypes.c_long), ("b", ctypes.c_long)]
        rc = _R()
        if u.SystemParametersInfoW(0x0030, 0, ctypes.byref(rc), 0):   # SPI_GETWORKAREA
            return (rc.l, rc.t, rc.r - rc.l, rc.b - rc.t)
        return (0, 0, u.GetSystemMetrics(0), u.GetSystemMetrics(1))
    except Exception:
        return None

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
                _args = [_exe, "--app=" + url, "--user-data-dir=" + _prof,
                         "--no-first-run", "--no-default-browser-check"]
                _wa = _screen_size()
                if _wa:
                    _wl, _wt, _ww, _wh = _wa
                    _W = min(1280, _ww)                       # 콘텐츠(최대 1160px)에 맞춘 너비
                    _X = _wl + max(0, (_ww - _W) // 2)        # 가로 중앙
                    _args += ["--window-size=%d,%d" % (_W, _wh),   # 세로는 작업영역 꽉
                              "--window-position=%d,%d" % (_X, _wt)]
                else:
                    _args.append("--start-maximized")         # 화면 크기 못 읽으면 최대화로 폴백
                subprocess.Popen(_args)
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
            log(f"config.json was corrupt — recreating with defaults (old file backed up as config.json.broken): {e}")
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
            "scale": "auto",     # auto | source | 1080 | 720 | 480  (auto: NVENC면 1080p, 소프트웨어면 720p로 낮춰 끊김 방지. 원본 그대로는 "source")
            "preset": "auto",    # auto | ultrafast | superfast | veryfast | fast ...  (libx264 속도/품질)
            "output_idx": "auto",   # auto | 0 | 1 | 2  (멀티모니터면 게임 있는 모니터 번호)
            "capture_target": "window",  # window(게임 창만·Alt+Tab 안전) | monitor(모니터 전체). 창 캡처 실패 시 자동으로 모니터 폴백.
            "capture": "auto",   # auto | wgc | ddagrab | gdigrab   (wgc=OBS식, 전체화면도 잡힘)
            "postgame_tail": 6,  # (GameEnd 미감지 시 폴백) 프로세스 종료 후 결과 화면을 몇 초 더 녹화할지(초)
            "result_tail": 8,  # 승리/패배(GameEnd) 화면을 몇 초 담고 정지할지(초) - 끝나고 늘어지는 것 방지
            "audio": "system",   # system = 시스템 전체 소리 | game-only = 롤 소리만(실험적, 실패 시 시스템으로 폴백)
            "port": free_port(8000),
            "fps": FPS,
            "poll_seconds": 4,
            "min_game_sec": 300,
            "keep_games": 20,    # 원본 자동 정리: 최근 N판만 보관 (0 = 무제한)
            "keep_gb": 30,       # 원본 총 용량 상한(GB). 초과분은 오래된 판부터 정리 (0 = 무제한)
            "audio_device": "",  # 녹음할 출력장치 이름(부분일치). 빈 값 = 기본 출력장치. 특정 장치를 고르면 그 장치 소리만 녹음.
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

def _bin_dir():
    """ffmpeg/ffprobe 고정 저장소. exe 를 새 폴더에 풀어도(=업데이트) 재다운로드 안 하도록
    데이터 폴더(ReplayCast) 아래에 둔다."""
    d = os.path.join(DATA_DIR, "bin")
    try: os.makedirs(d, exist_ok=True)
    except Exception: pass
    return d

def ffprobe_path():
    """ffprobe 실행 경로. 고정 폴더 우선 → 예전 exe 폴더(레거시) → PATH."""
    p = os.path.join(_bin_dir(), "ffprobe.exe")
    if os.path.isfile(p): return p
    legacy = os.path.join(HERE, "ffprobe.exe")
    if os.path.isfile(legacy):
        try: shutil.copy2(legacy, p); return p   # 다음부터 고정 폴더에서 사용
        except Exception: return legacy
    return shutil.which("ffprobe") or "ffprobe"

def ensure_ffmpeg():
    bindir = _bin_dir()
    local = os.path.join(bindir, "ffmpeg.exe")
    if os.path.isfile(local): return local                  # 고정 폴더에 이미 있음 → 재사용(업데이트해도 유지)
    # 레거시: 예전 버전이 exe 폴더에 받아둔 것 → 고정 폴더로 이관(한 번만) 후 재사용
    legacy = os.path.join(HERE, "ffmpeg.exe")
    if os.path.isfile(legacy):
        try:
            shutil.copy2(legacy, local)
            lp = os.path.join(HERE, "ffprobe.exe")
            if os.path.isfile(lp): shutil.copy2(lp, os.path.join(bindir, "ffprobe.exe"))
            log("Reusing existing ffmpeg (moved to shared folder - no re-download on future updates).")
            return local
        except Exception:
            return legacy
    found = shutil.which("ffmpeg")
    if found: return found
    log("Downloading ffmpeg\u2026 (~80MB, first run only, 1\u20133 min) \u2014 kept in a shared folder, so updates won't re-download.")
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
                        raise IOError(f"Incomplete download {got}/{total} bytes")
                    return buf.getvalue()
            except Exception as e:
                last = e
                if _i < tries - 1:
                    log(f"    Retrying {_i+1}/{tries-1} ({type(e).__name__})\u2026"); time.sleep(2.0 * (_i + 1))
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
                    with z.open(pm) as src, open(os.path.join(bindir, "ffprobe.exe"), "wb") as dst:
                        shutil.copyfileobj(src, dst)
            except Exception:
                pass
            log(f"ffmpeg ready. (source: {label})")
            return local
        except Exception as e:
            log(f"    {label} failed: {e} \u2192 trying next source")
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
class _ProgressReader:
    """업로드되는 동안 read마다 진행률 콜백 호출. requests가 Content-Length를 잡도록 __len__ 제공."""
    def __init__(self, f, total, cb):
        self._f = f; self._total = total; self._read = 0; self._cb = cb
    def read(self, n=-1):
        chunk = self._f.read(n)
        if chunk:
            self._read += len(chunk)
            try: self._cb(self._read, self._total)
            except Exception: pass
        return chunk
    def __len__(self):
        return self._total

def _gallery_origin():
    return (CFG.get("gallery_url") or "https://mypenta.netlify.app").strip().rstrip("/")

def sb_upload(local, path, ctype, on_progress=None, ident=None):
    """Storage 업로드 v2 → 공개 URL.
    ident=(puuid, device_secret) 가 있으면 Netlify 서명 프록시(/api/storage)로 1회용 URL 을 받아 업로드
    — service_key 가 클라이언트에 전혀 필요 없는 경로. 서명 실패 시 레거시 직접 업로드로 폴백
    (anon 정책 차단 전까지 동작; security_pass.sql 적용 후엔 서명 경로만 유효)."""
    if ident and ident[0] and ident[1]:
        try:
            return _upload_signed(local, path, ctype, ident, on_progress)
        except Exception as e:
            log("Signed upload unavailable (%s) - falling back to direct upload." % e)
    return _upload_direct(local, path, ctype, on_progress)

def _upload_signed(local, path, ctype, ident, on_progress=None):
    """서명 업로드: 시도마다 새 1회용 URL 발급(서명 토큰은 단발성) → PUT. 일시 오류만 백오프 재시도."""
    import requests
    org = _gallery_origin()
    total = os.path.getsize(local)
    _RETRYABLE = (408, 429, 500, 502, 503, 504)
    last = None
    for attempt in range(3):
        if attempt:
            wait = 3 if attempt == 1 else 8
            log("Upload retry %d/2 in %ds... (%s)" % (attempt, wait, last))
            time.sleep(wait)
        try:
            r = requests.post(org + "/api/storage",
                              json={"action": "sign-upload", "puuid": ident[0], "secret": ident[1],
                                    "paths": [path], "bytes": total},
                              timeout=25)
            if r.status_code == 401:
                raise RuntimeError("sign 401: identity not registered or bad secret")
            if r.status_code == 429:
                _rj = {}
                try: _rj = r.json() or {}
                except Exception: pass
                raise RuntimeError("upload limit reached (%s) - try again later" % (_rj.get("reason") or "quota"))
            if r.status_code != 200:
                if r.status_code in _RETRYABLE:
                    last = "sign %s" % r.status_code; continue
                raise RuntimeError("sign %s: %s" % (r.status_code, (r.text or "")[:160]))
            items = (r.json() or {}).get("items") or []
            if not items or not items[0].get("uploadUrl"):
                raise RuntimeError("sign: empty response")
            up = items[0]["uploadUrl"]; pub = items[0].get("publicUrl") or ""
            with open(local, "rb") as f:
                body = _ProgressReader(f, total, on_progress) if (on_progress and total) else f
                r2 = requests.put(up, data=body,
                                  headers={"Content-Type": ctype, "x-upsert": "true"},
                                  timeout=(10, 3600))
            if r2.status_code in (200, 201):
                return pub or ("%s/storage/v1/object/public/%s/%s" % (_sb_base(), _sb_bucket(), path))
            if r2.status_code not in _RETRYABLE:
                raise RuntimeError("put %s: %s" % (r2.status_code, (r2.text or "")[:160]))
            last = "put %s" % r2.status_code
        except requests.RequestException as e:
            last = e.__class__.__name__
    raise RuntimeError("signed upload failed after retries: %s" % last)

def _upload_direct(local, path, ctype, on_progress=None):
    """레거시 직접 업로드(anon/service 키). security_pass.sql 적용 후에는 차단됨 — 서명 경로가 표준."""
    import requests
    base = _sb_base(); bk = _sb_bucket()
    _hh = _sb_h(write=True, body_json=False); _hh["Content-Type"] = ctype; _hh["x-upsert"] = "true"
    total = os.path.getsize(local)
    _RETRYABLE = (408, 429, 500, 502, 503, 504)   # 일시 오류만 재시도(4xx 권한 문제는 즉시 실패)
    last_err = None
    for attempt in range(3):                      # 즉시 1회 + 백오프(3s, 8s) 2회
        if attempt:
            wait = 3 if attempt == 1 else 8
            log("Upload retry %d/2 in %ds... (%s)" % (attempt, wait, last_err))
            time.sleep(wait)
        try:
            with open(local, "rb") as f:          # 재시도마다 파일을 처음부터 다시 읽음
                body = _ProgressReader(f, total, on_progress) if (on_progress and total) else f
                r = requests.post("%s/storage/v1/object/%s/%s" % (base, bk, path), data=body,
                                  headers=_hh, timeout=(10, 3600))
            if r.status_code in (200, 201):
                return "%s/storage/v1/object/public/%s/%s" % (base, bk, path)
            if r.status_code not in _RETRYABLE:
                raise RuntimeError("storage %s: %s" % (r.status_code, r.text[:200]))
            last_err = "storage %s" % r.status_code
        except requests.RequestException as e:
            last_err = e.__class__.__name__       # 타임아웃/연결 끊김 등
    raise RuntimeError("storage upload failed after retries: %s" % last_err)
def cloud_selftest():
    """업로드 경로 자가진단. 현재 표준 경로(서명 프록시 /api/storage) 응답을 먼저 확인하고,
    프록시가 없으면(구 배포) 레거시 직접 업로드로 폴백 진단. security_pass.sql 이후
    직접 업로드가 정책으로 막힌 것은 '정상'이므로 더 이상 에러로 표시하지 않는다."""
    import tempfile, requests
    # 1) 표준 경로: Netlify 서명 프록시 헬스체크 (알 수 없는 action -> 400 JSON = 함수 살아있음)
    try:
        r = requests.post(_gallery_origin() + "/api/storage", json={"action": "ping"}, timeout=10)
        if r.status_code in (200, 400, 401, 405) and "error" in (r.text or ""):
            log("Cloud upload self-test: OK \u2713  (signed route /api/storage is live - game uploads ready)")
            return
        # 404 HTML 등 -> 함수 미배포로 간주하고 폴백 진단으로
        log("Signed route check: unexpected response %s - trying legacy direct upload..." % r.status_code)
    except Exception as e:
        log("Signed route check: unreachable (%s) - trying legacy direct upload..." % e.__class__.__name__)
    # 2) 폴백: 레거시 직접 업로드 (보안 패스 이전 배포에서만 성공)
    p = os.path.join(tempfile.gettempdir(), "penta_selftest.txt")
    try:
        with open(p, "w", encoding="utf-8") as _f: _f.write("penta")
        _upload_direct(p, "_selftest/ping.txt", "text/plain")   # x-upsert 라 매번 같은 파일 덮어씀(누적 없음)
        log("Cloud upload self-test: OK \u2713  (legacy direct upload)")
    except Exception as e:
        _em = str(e)
        if ("row-level security" in _em) or (" 403" in _em) or ("403" in _em) or ("Unauthorized" in _em):
            # 직접 업로드 차단 + 서명 프록시도 없음 -> 진짜 문제 (functions 미배포)
            log("Cloud upload self-test failed: direct upload is blocked by policy AND the signed route is not deployed.")
            log("\u2192 Fix: push netlify/functions/storage.js + netlify.toml, and set SUPABASE_SERVICE_KEY in Netlify env.")
        else:
            log(f"Cloud upload self-test failed: {e}")
    finally:
        try: os.remove(p)
        except Exception: pass
# ===================== Tier 1 신뢰성: 로컬 원본 정리 + 업로드 재시도 큐 =====================
RETRY_QUEUE_PATH = os.path.join(DATA_DIR, "upload_retry.json")
UPDATE_INFO = {}   # 새 버전 발견 시 {"tag": "vX.Y.Z", "url": 다운로드 페이지} — GUI 배너가 읽음

def _busy_now():
    return bool(REC_STATE.get("recording") or REC_STATE.get("uploading") or REC_STATE.get("preparing"))

def disk_free_gb(path=None):
    """대상 경로 드라이브의 여유 공간(GB). 실패 시 None."""
    try:
        import shutil as _sh
        return _sh.disk_usage(path or REC_DIR).free / 1073741824
    except Exception:
        return None

def _parse_ver(v):
    """'v1.2.3' / '1.2.3' → (1,2,3). 형식이 아니면 None (dev 포함)."""
    try:
        parts = str(v).strip().lstrip("vV").split(".")
        if len(parts) != 3: return None
        return tuple(int(p) for p in parts)
    except Exception:
        return None

def check_update():
    """GitHub Releases 최신 태그와 비교 → 새 버전이면 UPDATE_INFO 채움 + 로그. 실패는 조용히 무시(오프라인 등)."""
    cur = _parse_ver(APP_VERSION)
    if not cur:
        return   # 소스 실행/버전 미주입 → 확인 생략
    try:
        import requests
        r = requests.get("https://api.github.com/repos/choisungho-collab/PENTA/releases/latest",
                         headers={"Accept": "application/vnd.github+json"}, timeout=8)
        if r.status_code != 200:
            return
        j = r.json() or {}
        tag = str(j.get("tag_name") or "")
        new = _parse_ver(tag)
        if new and new > cur:
            UPDATE_INFO["tag"] = tag
            UPDATE_INFO["url"] = (CFG.get("gallery_url") or "https://mypenta.netlify.app").rstrip("/") + "/download.html"
            log("Update available: %s (you have %s). Get it from the download page." % (tag, APP_VERSION))
    except Exception:
        pass

def _rq_load():
    try:
        q = json.load(open(RETRY_QUEUE_PATH, encoding="utf-8"))
        return q if isinstance(q, list) else []
    except Exception:
        return []

def _rq_save(q):
    try: _atomic_write_json(RETRY_QUEUE_PATH, q)
    except Exception: pass

def enqueue_failed_upload(entry):
    """업로드 실패분을 큐에 저장 → 다음 실행 때 자동 재시도. 같은 id는 최신으로 갱신."""
    q = [e for e in _rq_load() if e.get("id") != entry.get("id")]
    entry["attempts"] = 0; entry["queued_at"] = time.time()
    q.append(entry); _rq_save(q)
    log("Upload saved to retry queue - will retry on next launch. (pending: %d)" % len(q))

def process_retry_queue():
    """시작 시 실패 큐 처리: 재업로드 성공 → 제거 / 파일 없음·6회째 실패 → 포기."""
    q = _rq_load()
    if not q:
        return
    if not sb_writable():
        log("Retry queue: %d pending, but cloud is not configured - keeping for later." % len(q)); return
    log("Retry queue: %d pending upload(s). Retrying now..." % len(q))
    rest = []
    for e in q:
        vid = e.get("video_file"); row = e.get("row") or {}; eid = e.get("id") or "?"
        e["attempts"] = int(e.get("attempts") or 0) + 1
        if not (vid and os.path.isfile(vid)):
            log("Retry dropped (file missing): %s" % eid); continue
        if e["attempts"] > 5:
            log("Retry dropped (too many attempts): %s" % eid); continue
        try:
            safe = e.get("safe") or ""
            safe = "".join(ch if (ch.isascii() and (ch.isalnum() or ch in "._-")) else "_" for ch in safe)   # 구버전 큐의 한글/특수문자 파일명 → ASCII (InvalidKey 재실패 방지)
            rid = e.get("riot_id") or ""
            _ident = riot_key(rid); _sec = device_secret() if _ident else None
            _idp = (_ident, _sec) if (_ident and _sec) else None
            if _idp:   # 서명 업로드 전 identities 등록(멱등) — verify_device 통과 조건
                try:
                    sb_rpc("register_identity", {"p_puuid": _ident, "p_secret": _sec, "p_name": rid, "p_icon": None})
                except Exception:
                    pass
            row["video"] = sb_upload(vid, "videos/%s.mp4" % safe, "video/mp4", ident=_idp)
            th = e.get("thumb_file")
            if th and os.path.isfile(th):
                row["thumb"] = sb_upload(th, "thumbs/%s.jpg" % safe, "image/jpeg", ident=_idp)
            done = False
            if _idp:   # 소유자 행 등록 우선, 실패 시 익명 RPC 폴백
                try:
                    sb_rpc("upload_match", {"p_puuid": _ident, "p_secret": _sec, "p_row": row})
                    done = True
                except Exception:
                    pass
            if not done:
                sb_insert_match(row)
            log("Retry upload OK: %s" % eid)
        except Exception as ex:
            log("Retry upload failed (%s): %s" % (eid, ex))
            rest.append(e)
    _rq_save(rest)

def cleanup_recordings(manual=False):
    """원본 보관 정책: 최근 keep_games판 + 총 keep_gb GB 상한 초과분을 오래된 순으로 삭제.
    안전장치: 녹화/업로드 중이면 건너뜀 / 30분 내 파일 보존 / 재시도 큐가 참조하는 파일 보존."""
    if _busy_now():
        if manual: log("Cleanup skipped: recording or upload in progress. Try again later.")
        return
    keep_n = int(CFG.get("keep_games", 20) or 0)
    keep_gb = float(CFG.get("keep_gb", 30) or 0)
    if keep_n <= 0 and keep_gb <= 0:
        if manual: log("Cleanup skipped: auto-clean is off (keep_games=0, keep_gb=0).")
        return
    protected = set()   # 재시도 큐가 참조하는 파일·폴더는 절대 삭제 금지
    for e in _rq_load():
        for k in ("video_file", "thumb_file"):
            v = e.get(k)
            if v:
                protected.add(os.path.normcase(os.path.abspath(v)))
                protected.add(os.path.normcase(os.path.abspath(os.path.dirname(v))))
    def _prot(p):
        return os.path.normcase(os.path.abspath(p)) in protected
    now = time.time(); removed = 0; freed = 0
    def _rm(p):
        nonlocal removed, freed
        if _prot(p): return
        try:
            if os.path.isdir(p):
                sz = 0
                for dp, _dns, fns in os.walk(p):
                    for fn in fns:
                        try: sz += os.path.getsize(os.path.join(dp, fn))
                        except OSError: pass
                import shutil as _sh
                _sh.rmtree(p, ignore_errors=True)
            else:
                sz = os.path.getsize(p); os.remove(p)
            removed += 1; freed += sz
        except OSError:
            pass
    try:
        vids = []
        for n in os.listdir(REC_DIR):
            p = os.path.join(REC_DIR, n)
            if n.lower().endswith(".mp4") and os.path.isfile(p):
                m = os.path.getmtime(p)
                if now - m > 1800: vids.append((m, p))   # 30분 내 파일은 집계에서 제외(=보존)
        vids.sort(reverse=True)                          # 최신 먼저
        drop = vids[keep_n:] if keep_n > 0 else []
        keep = vids[:keep_n] if keep_n > 0 else list(vids)
        if keep_gb > 0:                                  # 남긴 것도 총량 초과분은 오래된 것부터(최신 1판은 항상 보존)
            cap = keep_gb * 1073741824
            tot = 0
            for _m, p in keep:
                try: tot += os.path.getsize(p)
                except OSError: pass
            while len(keep) > 1 and tot > cap:
                m, p = keep.pop()                        # 끝 = 가장 오래된 판
                try: tot -= os.path.getsize(p)
                except OSError: pass
                drop.append((m, p))
        for _m, p in drop: _rm(p)
        for n in os.listdir(REC_DIR):                    # 하루 지난 임시 오디오/로그 정리
            p = os.path.join(REC_DIR, n)
            if os.path.isfile(p) and n.lower().endswith(".wav") and now - os.path.getmtime(p) > 86400:
                _rm(p)
        subs = []                                        # 업로드 산출물(preview/thumb) 폴더도 같은 N 기준
        for n in os.listdir(UPLOAD_DIR):
            p = os.path.join(UPLOAD_DIR, n)
            if os.path.isdir(p):
                m = os.path.getmtime(p)
                if now - m > 1800: subs.append((m, p))
        subs.sort(reverse=True)
        for _m, p in (subs[keep_n:] if keep_n > 0 else []):
            _rm(p)
    except Exception as e:
        log("Cleanup error: %s" % e); return
    if removed or manual:
        log("Cleanup done: %d item(s) removed, %.2f GB freed. (keep: %s games / %s GB cap)"
            % (removed, freed / 1073741824,
               (str(keep_n) if keep_n > 0 else "all"),
               (("%g" % keep_gb) if keep_gb > 0 else "no")))

def sb_insert_match(row):
    """익명 행 등록: 검증 RPC(upload_match_anon) 우선 — anon 직접 insert 는 security_pass.sql 이후 차단됨."""
    try:
        return sb_rpc("upload_match_anon", {"p_row": row})
    except Exception as e:
        log("Anon RPC insert unavailable (%s) - trying legacy direct insert." % str(e)[:120])
    return _insert_match_direct(row)

def _insert_match_direct(row):
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


# ===================== 소유권/로그인 (기기 비밀키 + RPC) =====================
# 신원 = 라이엇 PUUID. 인증 = 이 기기가 생성/보관하는 비밀키(서버엔 sha256 해시만 저장).
# PUUID 는 게임 후 Riot 프록시(resolve_match)에서 얻어 한 번 등록하면 영구 보관된다.
DEVICE_PATH = os.path.join(DATA_DIR, "penta_device.json")

def _device_load():
    try:
        if os.path.isfile(DEVICE_PATH):
            d = json.load(open(DEVICE_PATH, encoding="utf-8"))
            if isinstance(d, dict): return d
    except Exception: pass
    return {}

def _device_save(d):
    try: _atomic_write_json(DEVICE_PATH, d)
    except Exception: pass

def device_secret():
    """기기 비밀키(없으면 생성, 영구보관). 서버엔 sha256 해시만 올라간다."""
    d = _device_load()
    s = (d.get("secret") or "").strip()
    if len(s) < 20:
        s = secrets.token_urlsafe(32)
        d["secret"] = s; _device_save(d)
    return s

def device_get(key, default=None):
    return _device_load().get(key, default)

def device_set(**kw):
    d = _device_load(); d.update(kw); _device_save(d)

def riot_key(rid):
    """Riot ID(gameName#tagline)를 계정 신원 키로 정규화 — 대소문자/공백 차이를 무시한다.
    이 키가 곧 계정. PC를 가리지 않고, 같은 Riot ID면 어느 기기에서 올려도 한 계정으로 묶인다."""
    return (rid or "").strip().lower()

def _bind_account(rid):
    """게임에서 Riot ID를 확인하면 즉시 계정으로 묶는다 — riot_id 저장 + (클라우드면) 신원 등록.
    업로드를 끝까지 안 해도 게임 시작 직후 Archive 로그인이 되도록 한다."""
    if not rid: return
    try: device_set(riot_id=rid)
    except Exception: pass
    if cloud_state() == "cloud":
        def _reg():
            try: sb_rpc("register_identity", {"p_puuid": riot_key(rid), "p_secret": device_secret(), "p_name": rid, "p_icon": None})
            except Exception: pass
        threading.Thread(target=_reg, daemon=True).start()

def sb_rpc(fn, payload, timeout=30):
    """Supabase RPC(/rest/v1/rpc/{fn}) 호출 → 결과(JSON). 실패 시 예외."""
    import requests
    r = requests.post(_sb_base() + "/rest/v1/rpc/" + fn,
                      headers=_sb_h(write=True),
                      data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), timeout=timeout)
    if r.status_code not in (200, 201, 204):
        raise RuntimeError("rpc %s %s: %s" % (fn, r.status_code, r.text[:200]))
    try: return r.json()
    except Exception: return None


def _trim_front(video_path, cut_sec):
    """영상 앞 cut_sec 초를 잘라낸다(로딩 구간 제거). 분석이 없어 끝에서 역산할 수 없을 때 쓰는 폴백.
    잘라낸 초를 반환(멀티뷰 정렬용). -ss 를 입력 앞에 둬 빠르게 컷하고 -c copy 로 재인코딩 없음."""
    if not (FFMPEG and video_path and cut_sec and cut_sec > 0): return 0.0
    try:
        tmp = video_path + ".front.mp4"
        r = _run([FFMPEG, "-y", "-loglevel", "error", "-ss", f"{float(cut_sec):.2f}",
                  "-i", video_path, "-c", "copy", "-avoid_negative_ts", "make_zero", tmp],
                 capture_output=True)
        if r.returncode == 0 and os.path.isfile(tmp) and os.path.getsize(tmp) > 1024:
            os.replace(tmp, video_path)
            log("Trimmed the loading intro (no analysis) so it starts near the countdown")
            return float(cut_sec)
        else:
            try: os.remove(tmp)
            except OSError: pass
    except Exception as e:
        log(f"Skipped front-trim (keeping original): {e}")
    return 0.0


def _trim_lead(video_path, game_len_sec, lead=6.0):
    """로비/로딩 구간을 잘라 카운트다운(게임 시작 ~6초 전)부터 시작하게. 게임은 영상 끝에서 game_len_sec 길이라 끝에서 역산(-sseof). 앞에서 잘라낸 초를 반환(멀티뷰 정렬용)."""
    if not (FFMPEG and video_path and game_len_sec): return 0.0
    try:
        keep = float(game_len_sec) + lead
        orig = _video_dur(video_path) or 0.0
        tmp = video_path + ".trim.mp4"
        r = _run([FFMPEG, "-y", "-loglevel", "error", "-sseof", f"-{keep:.2f}",
                  "-i", video_path, "-c", "copy", "-avoid_negative_ts", "make_zero", tmp],
                 capture_output=True)
        if r.returncode == 0 and os.path.isfile(tmp) and os.path.getsize(tmp) > 1024:
            os.replace(tmp, video_path)
            log("Trimmed the lobby/loading intro so it starts at the countdown")
            return max(0.0, orig - keep) if orig else 0.0
        else:
            try: os.remove(tmp)
            except OSError: pass
    except Exception as e:
        log(f"Skipped trimming (keeping original): {e}")
    return 0.0


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


# ===================== 6. 레코더 (ffmpeg) =====================
_ENC_CACHE = None
_ENC_IS_SW = False   # 소프트웨어(libx264) 인코딩 여부 → 다운스케일 판단에 사용
_HW_ENCODERS = [   # 자동 선택 우선순위: NVIDIA → AMD → Intel. pix_fmt 은 인코더별로 다름(QSV 는 nv12 필수).
    ("nvenc", "h264_nvenc", ["-c:v", "h264_nvenc", "-preset", "p6", "-rc", "vbr", "-cq", "18", "-b:v", "0", "-pix_fmt", "yuv420p"], "NVENC"),
    ("amf",   "h264_amf",   ["-c:v", "h264_amf", "-quality", "quality", "-rc", "vbr_peak", "-b:v", "12M", "-maxrate", "20M", "-pix_fmt", "yuv420p"], "AMD AMF"),
    ("qsv",   "h264_qsv",   ["-c:v", "h264_qsv", "-global_quality", "20", "-pix_fmt", "nv12"], "Intel QSV"),
]
def _hw_ok(disp, args):
    """실제 사용할 것과 동일한 인자로 720p 1초 인코딩 테스트 — 목록에 있어도 런타임 실패면 다음 후보로."""
    try:
        r = _run([FFMPEG, "-hide_banner", "-loglevel", "error",
                  "-f", "lavfi", "-i", "color=c=black:s=1280x720:r=30:d=1",
                  *args, "-f", "null", "-"],
                 capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            errs = [l for l in (r.stderr or "").splitlines() if l.strip()]
            if errs: log("  %s error: %s" % (disp, "  /  ".join(errs[-2:])))
            return False
        return True
    except Exception as e:
        log("  %s test exception: %s" % (disp, e))
        return False

def _encoder_args():
    """인코더 자동 선택 — GPU 후보(NVENC→AMF→QSV)를 실제 인코딩 테스트로 검증, 전부 실패하면 x264."""
    global _ENC_CACHE, _ENC_IS_SW
    if _ENC_CACHE is not None: return _ENC_CACHE
    pref = (CFG.get("encoder") or "auto").lower()
    have = ""
    try:
        have = _run([FFMPEG, "-hide_banner", "-encoders"],
                              capture_output=True, text=True, timeout=15).stdout or ""
    except Exception: pass
    chosen = None
    if pref in ("x264", "libx264", "software", "cpu"):
        pass                                              # 명시적 CPU 선택
    elif pref in ("nvenc", "amf", "qsv"):                 # 명시적 GPU 선택 — 테스트 없이 존중(실패 시 에러가 그대로 보임)
        for key, codec, args, disp in _HW_ENCODERS:
            if key == pref:
                chosen = (list(args), disp); break
    else:                                                 # auto — 순서대로 실제 인코딩 테스트
        for key, codec, args, disp in _HW_ENCODERS:
            if codec not in have:
                continue
            if _hw_ok(disp, args):
                chosen = (list(args), disp); break
            log("  %s is listed but failed the encode test - trying next encoder." % disp)
    if chosen:
        _ENC_IS_SW = False
        _ENC_CACHE, name = chosen
    else:
        _ENC_IS_SW = True
        preset = (CFG.get("preset") or "auto").lower()
        if preset in ("auto", ""): preset = "superfast"   # 소프트웨어는 게임 끊김 방지 위해 가벼운 프리셋
        _ENC_CACHE = ["-c:v", "libx264", "-preset", preset, "-crf", "21", "-pix_fmt", "yuv420p"]; name = f"x264 ({preset})"
    log(f"Encoder: {name}")
    return _ENC_CACHE

def _probe_height(src):
    """ffprobe로 소스 영상 세로 해상도(px). 실패하면 0(안전하게 스케일 적용)."""
    try:
        fp = ffprobe_path()
        r = _run([fp, "-v", "error", "-select_streams", "v:0",
                  "-show_entries", "stream=height", "-of", "csv=p=0", src],
                 capture_output=True, text=True, timeout=20)
        out = (r.stdout or "").strip()
        return int(out.splitlines()[0]) if out else 0
    except Exception:
        return 0


def _ffmpeg_progress(args, dur, timeout):
    """ffmpeg 를 -progress 로 실행하며 압축 진행률(%)을 REC_STATE['prep_pct'] 에 갱신. returncode 반환."""
    full = list(args) + ["-progress", "pipe:1", "-nostats"]
    cf = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        p = subprocess.Popen(full, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1, creationflags=cf)
    except Exception:
        return 1
    t0 = time.time()
    try:
        for line in p.stdout:
            line = line.strip()
            if dur and line.startswith("out_time_us="):
                try:
                    sec = int(line.split("=", 1)[1]) / 1000000.0
                    pct = int(sec / dur * 100)
                    REC_STATE["prep_pct"] = 0 if pct < 0 else (99 if pct > 99 else pct)
                except Exception: pass
            elif line == "progress=end":
                REC_STATE["prep_pct"] = 100
            if timeout and (time.time() - t0) > timeout:
                try: p.kill()
                except Exception: pass
                break
    except Exception:
        pass
    try: p.wait(timeout=30)
    except Exception:
        try: p.kill()
        except Exception: pass
    return p.returncode if p.returncode is not None else 1


def make_preview(src, dst, dur=0):
    """원본을 갤러리용으로 재인코딩 — 최대 1080p(초과분만 다운스케일, 업스케일 안 함) + '또렷한' 화질.
    화질 노브: config.json 의 preview_cq(NVENC, 낮을수록 고화질, 기본 24) / preview_crf(x264, 기본 24).
    값을 더 낮추면(예: cq18/crf19) 더 선명·용량↑. 성공 시 dst, 실패 시 None(원본 업로드로 폴백)."""
    if not (FFMPEG and src and os.path.isfile(src)): return None
    enc = _encoder_args() or []
    cq  = str(CFG.get("preview_cq", 24))    # NVENC 품질(0~51, 낮을수록 고화질). 기본 24 = 한타 등 복잡한 장면도 또렷(용량↑ ~60%)
    crf = str(CFG.get("preview_crf", 24))   # x264/QSV 품질(0~51, 낮을수록 고화질). 기본 24
    if "h264_nvenc" in enc:
        # p6(고품질 프리셋) + VBR 기반 CQ. maxrate 로 최대 비트레이트만 막아 용량 폭주 방지.
        venc = ["-c:v", "h264_nvenc", "-preset", "p6", "-rc", "vbr", "-cq", cq,
                "-b:v", "0", "-maxrate", "20M", "-bufsize", "40M", "-pix_fmt", "yuv420p"]
    elif "h264_amf" in enc:
        venc = ["-c:v", "h264_amf", "-quality", "quality", "-rc", "vbr_peak",
                "-b:v", "10M", "-maxrate", "20M", "-pix_fmt", "yuv420p"]
    elif "h264_qsv" in enc:
        venc = ["-c:v", "h264_qsv", "-global_quality", crf, "-pix_fmt", "nv12"]
    else:
        venc = ["-c:v", "libx264", "-preset", "veryfast", "-crf", crf, "-pix_fmt", "yuv420p"]
    sh = _probe_height(src)
    vf = [] if (sh and sh <= 1080) else ["-vf", "scale=-2:'min(1080,ih)':flags=lanczos"]
    hws = ([["-hwaccel", "cuda"], []] if "h264_nvenc" in enc else [[]])   # NVENC: GPU decode first, CPU fallback
    try:
        log("Compressing for gallery (1080p, sharper)\u2026")
        REC_STATE["prep_pct"] = 0
        rc = 1
        for _hw in hws:
            REC_STATE["prep_pct"] = 0
            rc = _ffmpeg_progress([FFMPEG, "-y", "-loglevel", "error", *_hw, "-i", src,
                      *venc, *vf,
                      "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", dst],
                     dur, 5400)
            if rc == 0 and os.path.isfile(dst) and os.path.getsize(dst) > 0:
                return dst
            if _hw: log("GPU-decode attempt failed (code %s) - retrying with CPU decode." % rc)
        log("Gallery re-encode returned code %s \u2014 uploading original instead." % rc)
    except Exception as e:
        log("Gallery re-encode failed (%s) \u2014 uploading original instead." % e)
    return None


def _target_height(src_h=0):
    """소프트웨어 인코딩이면 부하를 줄이려 다운스케일할 목표 높이. None이면 원본 유지."""
    _encoder_args()  # _ENC_IS_SW 확정
    pref = str(CFG.get("scale") or "auto").lower()
    if pref in ("source", "원본", "full", "native", "off", "0"): return None
    if pref in ("1080", "1080p"): th = 1080
    elif pref in ("720", "720p"): th = 720
    elif pref in ("480", "480p"): th = 480
    elif pref in ("1440", "1440p"): th = 1440
    else:  # auto: 인코더 무관 1080p (가독성 우선 — 720p로 안 떨어뜨림; 원본 그대로는 scale="source", CPU 부하 크면 수동 720p 선택)
        th = 1080
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
        tail = [*enc, "-movflags", "+faststart", out]   # pix_fmt 은 인코더 인자에 포함(QSV=nv12)
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
        _gameonly = str(CFG.get("audio", "system")).lower() in ("game-only", "game", "gameonly", "game_only", "lol", "\ub86c\ub9cc")
        box = {"stop": threading.Event(), "t0": None, "thread": None, "ok": False, "path": self.audio_path,
               "pid": (_lol_game_pid() if _gameonly else None)}
        def worker():
            if box.get("pid"):
                try:
                    _capture_process_audio(box["pid"], box); return   # 게임 소리만 캡처 성공 → 끝까지 녹음
                except Exception as e:
                    log(f"  (audio) game-only capture failed \u2192 using system sound ({e})")
                    box["ok"] = False; box["t0"] = None
                    try:
                        if os.path.isfile(box["path"]): os.remove(box["path"])
                    except Exception: pass
                    # ↓ 시스템 사운드(디바이스 루프백)로 폴백
            try:
                import pyaudiowpatch as pa, wave
            except Exception as e:
                log(f"  (audio) pyaudiowpatch not installed \u2192 recording without sound. Install: pip install pyaudiowpatch ({e})"); return
            p = stream = wf = None
            try:
                p = pa.PyAudio()
                dev = None
                _want = str(CFG.get("audio_device") or "").strip()
                if _want:   # 사용자가 고른 장치(이름 부분일치) — 예: LoL 만 나오는 출력장치를 골라 '게임 소리만' 녹음
                    try:
                        for lb in p.get_loopback_device_info_generator():
                            if _want.lower() in str(lb.get("name","")).lower(): dev = lb; break
                    except Exception: dev = None
                    if dev is None: log("  (audio) chosen device not found - falling back to default output")
                if dev is None:
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
        # windows_capture는 import 시 cv2(OpenCV)를 부르지만, 우리는 frame.frame_buffer(numpy)만 쓰고 cv2는 안 쓴다.
        # OpenCV(수십 MB) 번들을 피하려고, 진짜 cv2가 없으면 빈 스텁을 끼워 import만 통과시킨다(→ GPU 캡처로 CPU 절감).
        if "cv2" not in sys.modules:
            try:
                import cv2  # noqa: F401  (진짜 OpenCV가 있으면 그대로 사용)
            except Exception:
                import types as _types
                sys.modules["cv2"] = _types.ModuleType("cv2")
        try:
            from windows_capture import WindowsCapture
        except ImportError:
            try:
                log("Installing WGC engine (windows-capture)…")
                _run([sys.executable, "-m", "pip", "install", "-q", "windows-capture", "--break-system-packages"], timeout=240)
                from windows_capture import WindowsCapture
            except Exception as e:
                log("  WGC engine not installed here \u2014 using GPU desktop capture (ddagrab) instead."); return False
        try:
            import numpy as _np
        except Exception as e:
            log(f"  WGC unavailable (numpy missing: {e})"); return False
        self.path = os.path.join(REC_DIR, f"clip_{datetime.datetime.now():%Y%m%d_%H%M%S}.mp4")
        enc = _encoder_args(); pathx = self.path; fps = self.fps
        shared = {"buf": None, "wh": None, "n": 0, "err": None}
        stop_ev = threading.Event(); proc_box = {"p": None}
        # Pick the monitor from config.output_idx (ddagrab is 0-based; windows-capture is 1-based → +1). "auto" → primary (1).
        _ci = CFG.get("output_idx", "auto")
        midx = (int(_ci) + 1) if (isinstance(_ci, int) or (isinstance(_ci, str) and _ci.isdigit())) else 1
        def _build_and_start(border, win_title=None):
            """주어진 draw_border로 캡처 세션 생성+이벤트 등록+시작. (cap, control) 반환.
            win_title 이 있으면 그 창만 캡처(Alt+Tab 해도 게임만 녹화), 없으면 모니터 전체."""
            if win_title:
                cap = WindowsCapture(cursor_capture=None, draw_border=border, monitor_index=None, window_name=win_title)
            else:
                cap = WindowsCapture(cursor_capture=None, draw_border=border, monitor_index=midx, window_name=None)
            @cap.event
            def on_frame_arrived(frame, capture_control):
                if stop_ev.is_set():
                    try: capture_control.stop()
                    except Exception: pass
                    return
                try:
                    _fb = frame.frame_buffer
                    # 즉시 복사: windows-capture 가 이 버퍼를 다음 프레임에 재사용하면, 참조만 들고 있던
                    # 피더가 읽는 도중 내용이 바뀌어 '위/아래가 다른 순간'으로 찢어짐(tearing). copy 로 스냅샷 고정.
                    _w = frame.width
                    _h = frame.height
                    # 진단: 버퍼 형태/방향(strides)이 바뀔 때만 1줄 로그 → 간헐적 위아래 반전/노이즈 원인 추적.
                    try:
                        _sig = (_fb.ndim, tuple(_fb.shape), tuple(getattr(_fb, "strides", ()) or ()))
                        if shared.get("_dbgshp") != _sig:
                            shared["_dbgshp"] = _sig
                            log("WGC buf: shape=%s strides=%s w=%d h=%d" % (_fb.shape, getattr(_fb, "strides", None), _w, _h))
                    except Exception: pass
                    # 스트라이드(행 패딩) 보정: GPU 버퍼는 한 행이 width*4 보다 넓을 수 있음(정렬 패딩).
                    #  → 패딩을 제거해 정확히 (h, w, 4) 로 만들어야 대각선 노이즈가 안 생긴다. 버퍼 형태별 처리.
                    if _fb.ndim == 3:
                        if _fb.shape[1] != _w: _fb = _fb[:, :_w, :]                 # (h, padded_w, 4) → (h, w, 4)
                    elif _fb.ndim == 2:
                        if _fb.shape[1] > _w * 4: _fb = _fb[:, :_w * 4]             # (h, padded_bytes) → (h, w*4)
                        _fb = _fb.reshape(_h, _w, 4)
                    elif _fb.ndim == 1 and _fb.size >= _w * _h * 4:
                        _st = _fb.size // _h                                        # 행당 실제 바이트(패딩 포함)
                        _fb = _fb.reshape(_h, _st)[:, :_w * 4].reshape(_h, _w, 4)   # 패딩 제거 후 재구성
                    shared["buf"] = _np.ascontiguousarray(_fb).copy()   # .copy() 필수 — 원본 frame_buffer 는 다음 프레임에 재사용/해제됨. 참조만 두면 피더가 해제된 메모리를 tobytes() 로 읽어 access violation(즉시 크래시) → 반드시 독립 메모리로 복사한다.
                    shared["wh"] = (_w, _h)
                    shared["n"] = shared.get("n", 0) + 1
                except Exception as e:
                    if shared.get("err") is None: shared["err"] = repr(e)
            @cap.event
            def on_closed():
                pass
            return cap, cap.start_free_threaded()

        def feeder():
            t0 = time.time()
            while shared["buf"] is None and time.time() - t0 < 3.0 and not stop_ev.is_set():
                time.sleep(0.05)
            if shared["buf"] is None: return            # 프레임이 하나도 안 옴 = 캡처 실패
            w, h = shared["wh"]
            vf, _chain = _scale_vf(h)
            cmd = [FFMPEG, "-y", "-loglevel", "error",
                   "-f", "rawvideo", "-pixel_format", "bgra", "-video_size", f"{w}x{h}", "-framerate", str(fps),
                   "-i", "pipe:", *vf, *enc, "-movflags", "+faststart", pathx]
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
            interval = 1.0 / max(1, fps); nxt = time.time(); last_good = None
            while not stop_ev.is_set():
                b = shared["buf"]
                if b is not None:
                    # Alt+Tab/해상도 변경으로 프레임 크기가 초기 w×h 와 달라지면 → 노이즈·파이프 깨짐(에러/크래시).
                    #  크기가 맞는 프레임만 인코더에 쓰고, 안 맞으면 직전 정상 프레임을 반복(해상도 복귀 시 자동 정상화).
                    if b.shape[1] == w and b.shape[0] == h:
                        bb = b.tobytes(); last_good = bb
                    else:
                        bb = last_good
                    if bb is not None:
                        try: p.stdin.write(bb)   # 콜백에서 복사·스트라이드보정된 연속버퍼(크기검증 통과) → 그대로 안전
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

        # 1순위: 테두리 없는 WGC(가장 가볍고 깔끔). 일부 OS(Win10/구버전 Win11)는 이 토글을 미지원해 예외가 난다.
        # ★ 성능 우선: ddagrab(GPU)은 hwdownload 로 매 프레임을 GPU→CPU 로 복사해 WGC보다 무겁다(인게임 FPS 저하 가능).
        #   따라서 borderless 가 안 되면 ddagrab 으로 떨어뜨리지 말고, WGC 기본(None)으로 — 여전히 GPU 기반이라 가볍다.
        #   (그 대신 일부 빌드는 노란 테두리가 남을 수 있음. 노란선이 싫고 부하를 감수하면 config.json "capture":"ddagrab".)
        # 캡처 대상: 게임 창을 우선(Alt+Tab 해도 게임만 녹화). 창을 못 잡으면 모니터 전체로 폴백.
        #   config "capture_target": "window"(기본) | "monitor" 로 강제 가능.
        _tgt = str(CFG.get("capture_target", "window")).lower()
        _wtitle = _lol_window_title() if _tgt != "monitor" else None
        try:
            if _wtitle:
                cap, control = _build_and_start(False, _wtitle)   # 게임 창만 캡처
                log("  WGC target: game window (\"%s\") - Alt+Tab won't be recorded." % _wtitle[:40])
            else:
                cap, control = _build_and_start(False)            # 모니터 전체(폴백)
        except Exception:
            # 창 캡처 실패(전체화면 등) → 모니터 전체로 안전 폴백
            try:
                if _wtitle:
                    cap, control = _build_and_start(False)
                    log("  WGC: window capture failed - fell back to full monitor.")
                else:
                    raise RuntimeError("monitor capture also failed")
            except Exception:
                try:
                    cap, control = _build_and_start(None)     # WGC 기본(가벼움) — 빌드에 따라 노란 테두리가 남을 수 있음
                    log("  WGC: this build keeps the default capture border (kept WGC for low overhead).")
                except Exception:
                    log("  WGC not usable here \u2014 using GPU desktop capture (ddagrab) instead.")
                    return False
        ft = threading.Thread(target=feeder, daemon=True); ft.start()
        self._wgc_control = control
        self._wgc_state = {"stop": stop_ev, "feeder": ft, "proc_box": proc_box}
        self.backend = "wgc"
        if not verify:
            log(f"● Recording started (WGC · Monitor {midx})"); return True
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
            log(f"● Recording started (WGC · Monitor {midx} — capture verified)"); return True
        if ok:                                       # 파일이 아직 작으면(정적 화면) 잠깐 더 대기 후 재확인
            time.sleep(2.5)
            if _sz() >= 8000:
                log(f"● Recording started (WGC · Monitor {midx} — capture verified)"); return True
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
            except Exception:
                log("  WGC not usable here \u2014 using GPU desktop capture (ddagrab) instead.")
            if capmode == "wgc":
                log("  WGC unavailable \u2014 falling back to ddagrab/gdigrab.")
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
            time.sleep(0.05)   # on_frame_arrived 가 마지막 프레임을 마무리하고 stop_ev 로 스스로 멈출 여유 → 세션 파괴와 경쟁(네이티브 크래시) 방지
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

def _lol_game_pid():
    """League of Legends.exe(게임 인스턴스) PID. 없으면 None."""
    try:
        for p in psutil.process_iter(["name", "pid"]):
            try:
                if (p.info["name"] or "").lower() == "league of legends.exe":
                    return int(p.info["pid"])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except Exception:
        pass
    return None

def _lol_window_title(pid=None):
    """League of Legends.exe 게임 창의 제목을 찾는다(WGC 창 캡처용). 보통 'League of Legends (TM) Client'.
    PID 로 그 프로세스의 보이는 창을 찾고, 실패하면 알려진 제목으로 폴백. 못 찾으면 None(→ 모니터 캡처)."""
    if sys.platform != "win32":
        return None
    want_pid = pid or _lol_game_pid()
    found = {"title": None}
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        EnumWindows = user32.EnumWindows
        EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def _cb(hwnd, _l):
            try:
                if not user32.IsWindowVisible(hwnd): return True
                _p = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(_p))
                if want_pid and _p.value != want_pid: return True
                n = user32.GetWindowTextLengthW(hwnd)
                if n <= 0: return True
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                t = buf.value or ""
                if "league of legends" in t.lower():   # 게임 창 (런처/로비 제외 목적)
                    found["title"] = t; return False
            except Exception:
                pass
            return True
        EnumWindows(EnumWindowsProc(_cb), 0)
    except Exception:
        pass
    return found["title"]


def _capture_process_audio(pid, box):
    """Win10(2004+) 프로세스 루프백 API로 특정 PID 오디오만 box['path'] WAV에 녹음.
    성공 시 box['ok']=True 로 두고 box['stop'] 까지 녹음. 실패하면 예외를 던져
    호출부가 시스템 사운드(디바이스 루프백)로 폴백하게 한다. (실험적)"""
    import ctypes, wave, time as _t
    import ctypes.wintypes as wt
    from ctypes import (POINTER, byref, c_void_p, c_uint32, c_int32, c_uint64,
                        Structure, HRESULT, c_wchar_p, c_byte, c_uint16, c_ulong, cast, WINFUNCTYPE, sizeof)

    ole32 = ctypes.windll.ole32
    mmd = ctypes.windll.mmdevapi
    ole32.CoInitializeEx(None, 0)   # MTA
    try:
        class GUID(Structure):
            _fields_ = [("a", c_uint32), ("b", c_uint16), ("c", c_uint16), ("d", c_byte * 8)]
        def G(sg):
            g = GUID(); ole32.CLSIDFromString(c_wchar_p(sg), byref(g)); return g
        IID_AC  = G("{1CB9AD4C-DBFA-4c32-B178-C2F568A703B2}")   # IAudioClient
        IID_CAP = G("{C8ADBD64-E71E-48a0-A4DE-185C395CD317}")   # IAudioCaptureClient

        def call(p, idx, rest, argt, *a):   # vtable 인덱스로 COM 호출
            vt = cast(p, POINTER(c_void_p))[0]
            fn = cast(vt, POINTER(c_void_p))[idx]
            return WINFUNCTYPE(rest, c_void_p, *argt)(fn)(p, *a)

        class PROC_LB(Structure):
            _fields_ = [("pid", wt.DWORD), ("mode", c_int32)]
        class ACTP(Structure):
            _fields_ = [("atype", c_int32), ("plb", PROC_LB)]
        class BLOB(Structure):
            _fields_ = [("cb", c_uint32), ("p", c_void_p)]
        class PROPV(Structure):
            _fields_ = [("vt", c_uint16), ("r1", c_uint16), ("r2", c_uint16), ("r3", c_uint16),
                        ("blob", BLOB), ("pad", c_byte * 8)]
        class WFX(Structure):
            _fields_ = [("tag", c_uint16), ("ch", c_uint16), ("sps", c_uint32),
                        ("abps", c_uint32), ("ba", c_uint16), ("bps", c_uint16), ("cb", c_uint16)]

        # 완료 핸들러 (IActivateAudioInterfaceCompletionHandler): QI/AddRef/Release/ActivateCompleted
        done = {"f": False}
        QIp = WINFUNCTYPE(HRESULT, c_void_p, POINTER(GUID), POINTER(c_void_p))
        ULp = WINFUNCTYPE(c_ulong, c_void_p)
        ACp = WINFUNCTYPE(HRESULT, c_void_p, c_void_p)
        def _qi(this, riid, ppv): ppv[0] = this; return 0
        def _au(this): return 1
        def _re(this): return 1
        def _ac(this, op): done["f"] = True; return 0
        _f = (QIp(_qi), ULp(_au), ULp(_re), ACp(_ac))   # 참조 유지
        VT = (c_void_p * 4)(cast(_f[0], c_void_p), cast(_f[1], c_void_p), cast(_f[2], c_void_p), cast(_f[3], c_void_p))
        class HOBJ(Structure):
            _fields_ = [("vtbl", c_void_p)]
        hobj = HOBJ(); hobj.vtbl = cast(byref(VT), c_void_p)

        ap = ACTP(); ap.atype = 1   # PROCESS_LOOPBACK
        ap.plb.pid = pid; ap.plb.mode = 0   # INCLUDE_TARGET_PROCESS_TREE
        pv = PROPV(); pv.vt = 65   # VT_BLOB
        pv.blob.cb = sizeof(ACTP); pv.blob.p = cast(byref(ap), c_void_p)

        op = c_void_p()
        hr = mmd.ActivateAudioInterfaceAsync(c_wchar_p("VAD\\Process_Loopback"),
                                             byref(IID_AC), byref(pv), cast(byref(hobj), c_void_p), byref(op))
        if hr != 0: raise RuntimeError("Activate 0x%X" % (hr & 0xffffffff))
        for _ in range(600):
            if done["f"]: break
            _t.sleep(0.005)
        if not done["f"]: raise RuntimeError("activation timeout")

        hres = HRESULT(); iface = c_void_p()
        call(op, 3, HRESULT, [POINTER(HRESULT), POINTER(c_void_p)], byref(hres), byref(iface))   # GetActivateResult
        if (hres.value & 0xffffffff) != 0 or not iface.value: raise RuntimeError("GetActivateResult 0x%X" % (hres.value & 0xffffffff))
        acl = iface

        SPS = 48000
        fmt = WFX(1, 2, SPS, SPS * 4, 4, 16, 0)   # PCM 48k 2ch 16bit
        hr = call(acl, 3, HRESULT,
                  [c_int32, c_uint32, c_uint64, c_uint64, c_void_p, c_void_p],
                  0, 0x00020000, c_uint64(3000000), c_uint64(0), cast(byref(fmt), c_void_p), None)   # Initialize(SHARED, LOOPBACK)
        if hr != 0: raise RuntimeError("Initialize 0x%X" % (hr & 0xffffffff))

        cap = c_void_p()
        hr = call(acl, 14, HRESULT, [POINTER(GUID), POINTER(c_void_p)], byref(IID_CAP), byref(cap))   # GetService
        if hr != 0 or not cap.value: raise RuntimeError("GetService 0x%X" % (hr & 0xffffffff))
        hr = call(acl, 10, HRESULT, [])   # Start
        if hr != 0: raise RuntimeError("Start 0x%X" % (hr & 0xffffffff))

        wf = wave.open(box["path"], "wb"); wf.setnchannels(2); wf.setsampwidth(2); wf.setframerate(SPS)
        box["t0"] = _t.time(); box["ok"] = True
        log("  \u266a Audio (game only) started \u2014 League of Legends \u00b7 48000Hz 2ch")
        BPF = 4
        try:
            while not box["stop"].is_set():
                pkt = c_uint32(0); call(cap, 5, HRESULT, [POINTER(c_uint32)], byref(pkt))   # GetNextPacketSize
                if pkt.value == 0:
                    _t.sleep(0.008); continue
                while pkt.value > 0:
                    pdata = c_void_p(); nfr = c_uint32(); fl = c_uint32()
                    hr = call(cap, 3, HRESULT,
                              [POINTER(c_void_p), POINTER(c_uint32), POINTER(c_uint32), POINTER(c_uint64), POINTER(c_uint64)],
                              byref(pdata), byref(nfr), byref(fl), None, None)   # GetBuffer
                    if hr != 0: break
                    n = nfr.value
                    if n:
                        if fl.value & 0x2:   # SILENT
                            wf.writeframes(b"\x00" * (n * BPF))
                        elif pdata.value:
                            wf.writeframes(bytes((c_byte * (n * BPF)).from_address(pdata.value)))
                    call(cap, 4, HRESULT, [c_uint32], nfr)   # ReleaseBuffer
                    pkt = c_uint32(0); call(cap, 5, HRESULT, [POINTER(c_uint32)], byref(pkt))
        finally:
            try: call(acl, 11, HRESULT, [])   # Stop
            except Exception: pass
            try: wf.close()
            except Exception: pass
    finally:
        try: ole32.CoUninitialize()
        except Exception: pass


def sc_running(name):
    n = name.lower()
    for p in psutil.process_iter(["name"]):
        try:
            if (p.info["name"] or "").lower() == n: return True
        except (psutil.NoSuchProcess, psutil.AccessDenied): pass
    return False


_LCU = {"port": None, "token": None, "t": 0.0, "warned": False}
def _lcu_creds():
    """LeagueClientUx.exe 명령줄에서 LCU 포트/토큰을 읽는다(30초 캐시). 실패하면 (None, None)."""
    now = time.time()
    if _LCU["port"] and (now - _LCU["t"] < 30): return _LCU["port"], _LCU["token"]
    try:
        for p in psutil.process_iter(["name"]):
            try:
                if (p.info["name"] or "").lower() != "leagueclientux.exe": continue
                cl = p.cmdline()
            except (psutil.NoSuchProcess, psutil.AccessDenied): continue
            port = token = None
            for a in cl:
                if a.startswith("--app-port="): port = a.split("=", 1)[1]
                elif a.startswith("--remoting-auth-token="): token = a.split("=", 1)[1]
            if port and token:
                _LCU.update(port=port, token=token, t=now); return port, token
    except Exception: pass
    _LCU.update(port=None, token=None, t=now); return None, None

def lcu_in_champ_select():
    """LCU API로 챔피언 선택 중인지 확인. 실패/아니면 False (→ 게임 프로세스 감지로 폴백)."""
    port, token = _lcu_creds()
    if not (port and token): return False
    try:
        import requests, base64
        try:
            requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)
        except Exception: pass
        auth = base64.b64encode(("riot:" + token).encode()).decode()
        r = requests.get("https://127.0.0.1:%s/lol-champ-select/v1/session" % port,
                         headers={"Authorization": "Basic " + auth}, verify=False, timeout=2)
        return r.status_code == 200   # 챔프셀럭이면 200, 아니면 404
    except Exception:
        return False


def _sec_mmss(s):
    s = int(s or 0)
    return f"{s//60}:{s%60:02d}"

def _video_dur(video_path):
    """ffprobe로 영상 실제 길이(초)를 잰다. 분석을 못 했을 때 길이 판단용. 실패하면 0."""
    try:
        fp = ffprobe_path()
        out = subprocess.run([fp, "-v", "error", "-show_entries", "format=duration",
                              "-of", "default=nw=1:nk=1", video_path],
                             capture_output=True, text=True, timeout=30).stdout.strip()
        return float(out) if out else 0.0
    except Exception:
        return 0.0

def _discard(video_path, reason):
    REC_STATE["preparing"] = False
    REC_STATE["skipped_at"] = time.time()   # GUI 상태바에 몇 초간 '저장 안 함' 알림
    REC_STATE["skipped_why"] = reason
    log(f"  Discarding (not saving) - {reason}")
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


def ingest_lol(video_path, riot_id, start_ts, end_ts, proxy_url, platform="kr", live_data=None, started_cs=False, vt0=None):
    # 화면 녹화 + (게임 종료 후) Riot 매치를 연결해 분석·업로드한다.
    # Riot 매치 연결이 안 되더라도(개발키 만료/레이트리밋/타이밍 등) 영상은 업로드하고 아카이브에 올린다.
    if not video_path or not os.path.isfile(video_path) or os.path.getsize(video_path) < 10000:
        log("Video is empty → skipping registration."); return
    if not riot_id:
        return _discard(video_path, "Couldn't verify your Riot ID (may not be a game)")

    # --- Riot 매치 연결 시도 (실패해도 영상은 올린다; 분석만 비움) ---
    REC_STATE["preparing"] = True   # 업로드 준비중: 분석·트림·썸네일·인코딩 (업로드 직전까지)
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
    # 시점별 고유 행 id — 스토리지 키로도 쓰이므로 반드시 ASCII (한글/특수문자 → Supabase InvalidKey 방지)
    if puuid:
        _viewer = puuid
    else:
        _nm = "".join(ch for ch in (riot_id or "") if ch.isascii() and ch.isalnum())[:24]
        _viewer = (_nm + "_" if _nm else "") + hashlib.sha1((riot_id or "").encode("utf-8")).hexdigest()[:10]
    row_id = gid + "__" + _viewer
    safe = "".join(ch if (ch.isascii() and (ch.isalnum() or ch in "._-")) else "_" for ch in row_id)   # 키 안전망: 무조건 ASCII
    size = os.path.getsize(video_path)
    base = os.path.join(UPLOAD_DIR, safe); os.makedirs(base, exist_ok=True)
    # ── 영상 t=0 의 gameTime 을 먼저 구한다(snaps 기반). 이걸로 로딩 길이를 알 수 있음. ──
    _snaps0 = (live_data or {}).get("snaps") or []
    _anchor0 = vt0 if (vt0 and start_ts and vt0 >= start_ts) else start_ts
    _g0_raw = None   # 영상 t=0 시점의 gameTime(초). 음수면 그만큼 로딩/카운트다운.
    try:
        _cs0 = [float(s.get("t") or 0) - (float(s["w"]) - _anchor0) for s in _snaps0 if s.get("w") and _anchor0]
        if _cs0:
            _cs0.sort(); _g0_raw = _cs0[len(_cs0)//2]
    except Exception:
        _g0_raw = None

    trimmed = 0.0
    try:
        # 로비/로딩/챔프선택 구간을 잘라 '게임 시작 카운트다운' 근처에서 시작하도록.
        if dur and analysis:
            # (1순위) 분석 성공: 영상 끝에서 게임 길이만큼 역산해 정확히 컷
            trimmed = _trim_lead(video_path, dur) or 0.0
        elif _g0_raw is not None and _g0_raw < -8:
            # (폴백) 분석 실패해도 snaps 로 로딩을 안다 → 앞에서 잘라 카운트다운 ~2초 전부터.
            #        _g0_raw=-60 이면 영상 앞 60초가 로딩 → 58초 잘라냄. (게임 감지 녹화만: 챔프선택은 g0 가 더 큰 음수라 과다 컷 방지 위해 캡)
            _cut = min(-_g0_raw - 2.0, 90.0)   # 최대 90초까지만(오검출 안전장치)
            if _cut > 3:
                trimmed = _trim_front(video_path, _cut) or 0.0
    except Exception: pass
    if not sb_writable():
        REC_STATE["preparing"] = False
        log("Cloud (Supabase) not configured → keeping locally only."); return
    tmp_thumb = os.path.join(base, "thumb.jpg"); has_thumb = make_thumb(video_path, tmp_thumb)
    # 갤러리용 프리뷰(최대 1080p, 또렷한 화질)만 업로드. 원본(고화질)은 PC에 그대로 보관(다운로드 없음).
    preview = os.path.join(base, "preview.mp4")
    up_src = make_preview(video_path, preview, dur) or video_path
    up_size = os.path.getsize(up_src)
    if up_src != video_path:
        log("Gallery video ready (1080p) \u2014 %d MB. Full-quality original kept on your PC." % (up_size // 1048576))
    REC_STATE["preparing"] = False; REC_STATE["uploading"] = True; REC_STATE["upload_pct"] = 0
    def _up_cb(done, total):
        p = int(done * 100 / total) if total else 0
        if p != REC_STATE.get("upload_pct"): REC_STATE["upload_pct"] = p
    try:
        players = analysis.get("players") or []
        me = next((p for p in players if puuid and p.get("puuid") == puuid), None)
        if not me and riot_id:
            _mn2 = riot_id.split("#")[0]
            me = next((p for p in players if p.get("name") == _mn2), None)
        won = (me or {}).get("win")
        saver = (me or {}).get("name") or riot_id.split("#")[0]
        try:
            if _g0_raw is not None:
                analysis["g0"] = round(_g0_raw + (trimmed or 0.0), 2)   # 영상 t=0의 gameTime(멀티뷰 정밀 정렬용) — 트림한 만큼 보정
        except Exception: pass
        _row = {
            "id": row_id, "match_id": gid, "uploader": saver,
            "uploaded": datetime.datetime.now().isoformat(timespec="seconds"),
            "video": None, "thumb": None, "replay": None,   # URL은 업로드 성공 후 채움(실패 시 재시도 큐에 그대로 저장)
            "video_size": up_size or 0,
            "map": "Summoner's Rift", "matchup": None,
            "length": _sec_mmss(dur), "length_sec": int(dur or 0),
            "type": str(analysis.get("queue") or ""),
            "winner": analysis.get("win_team"), "saver": saver,
            "np": len(players), "players": players, "won": won,
            "analysis": analysis,
        }
        log("Uploading video to cloud\u2026 (%s)" % (("%.1f GB" % (up_size / 1073741824)) if up_size >= 1073741824 else ("%d MB" % (up_size // 1048576))))
        _idp = None   # 서명 업로드용 신원 (로그인 필요 없음 — 기기 비밀키로 증명)
        try:
            _ik = riot_key(riot_id)
            if _ik:
                _idp = (_ik, device_secret())
                try:   # verify_device 가 통과하려면 identities 에 등록돼 있어야 함(멱등)
                    sb_rpc("register_identity", {"p_puuid": _ik, "p_secret": _idp[1], "p_name": riot_id, "p_icon": None})
                except Exception:
                    pass
        except Exception:
            _idp = None
        video_url = sb_upload(up_src, f"videos/{safe}.mp4", "video/mp4", on_progress=_up_cb, ident=_idp)
        thumb_url = sb_upload(tmp_thumb, f"thumbs/{safe}.jpg", "image/jpeg", ident=_idp) if has_thumb else None
        _row["video"] = video_url; _row["thumb"] = thumb_url
        _ident = riot_key(riot_id)   # 계정 = Riot ID. PC 안 가리고 같은 ID면 한 계정.
        if _ident:   # 이 PC를 인가 기기로 등록하고 소유자(riot_key) 박아 업로드. 실패 시에만 익명 폴백.
            try:
                _sec = device_secret()
                sb_rpc("register_identity", {"p_puuid": _ident, "p_secret": _sec, "p_name": riot_id, "p_icon": None})
                device_set(riot_id=riot_id)
                sb_rpc("upload_match", {"p_puuid": _ident, "p_secret": _sec, "p_row": _row})
            except Exception as _e:
                log(f"  Owner upload failed ({_e}) \u2014 falling back to anonymous upload."); sb_insert_match(_row)
        else:
            sb_insert_match(_row)
        log(f"Upload complete \u2713 \u2014 now in your gallery. ({('matchId ' + gid) if mid else 'video only, no analysis'})")
    except Exception as e:
        _em = str(e)
        log(f"Upload failed: {e}")          # ← 원본 Supabase 응답을 항상 표시(진단용; 더 이상 가리지 않음)
        if ("row-level security" in _em) or ("Unauthorized" in _em) or (" 403" in _em) or ("403:" in _em):
            log("\u2192 Upload blocked by storage policy. Check: Netlify env SUPABASE_SERVICE_KEY + storage.js deployed (signed route /api/storage). Video is kept locally and queued for retry.")
        try:   # 실패분은 큐에 저장 → 다음 실행 때 자동 재업로드 (파일은 정리 대상에서 보호됨)
            enqueue_failed_upload({"id": row_id, "safe": safe, "riot_id": riot_id or "",
                                   "video_file": up_src, "thumb_file": (tmp_thumb if has_thumb else None),
                                   "row": _row})
        except Exception as _qe:
            log("Retry-queue save failed: %s" % _qe)
    finally:
        REC_STATE["uploading"] = False; REC_STATE["preparing"] = False; REC_STATE["upload_pct"] = 0
        try: cleanup_recordings()   # 업로드 사이클이 끝날 때마다 보관 정책 적용
        except Exception: pass

def recorder_loop(cfg):
    proc = cfg.get("league_process", "League of Legends.exe")
    proxy = (cfg.get("proxy_url") or "").strip() or PROXY_DEFAULT; platform = cfg.get("platform", "kr")
    poll = float(cfg.get("poll_seconds", 4)); rec = Recorder(int(cfg.get("fps", FPS)))
    active = False; riot_id = None; start_ts = None; last_hb = 0.0; saw_game = False; cs_grace = 0.0; started_cs = False; ended_at = 0.0
    live_snaps = []; live_evts = []; last_snap_t = -999.0   # 게임 중 Live Client 스냅샷 수집용
    try: ensure_audio()
    except Exception: pass
    if not proxy:
        log("Note: proxy_url in config.json is empty. Set your Netlify proxy URL to connect analysis.")
    def _startup_maintenance():   # 준비를 막지 않도록 백그라운드에서: 버전 확인 → 실패 큐 재업로드 → 보관 정책 정리
        if _parse_ver(APP_VERSION): log("Version: %s" % APP_VERSION)
        try: check_update()
        except Exception: pass
        try: process_retry_queue()
        except Exception as e: log("Retry queue error: %s" % e)
        try: cleanup_recordings()
        except Exception: pass
    threading.Thread(target=_startup_maintenance, daemon=True).start()
    log("Ready. Start a League of Legends game and it records automatically. (Keep this window open.)")
    while True:
        try:
            run = sc_running(proc)   # 게임 인스턴스(League of Legends.exe) = 인게임
            try: in_cs = lcu_in_champ_select()   # LCU: 챔피언 선택 중? (실패하면 False → 게임 감지로 폴백)
            except Exception: in_cs = False

            # ── 녹화 시작: 게임(로딩 화면)부터. 밴픽(챔피언 선택)은 녹화하지 않음 ──
            if run and not active:
                if run:
                    log("Game detected. Checking your info\u2026")
                    for _ in range(20):
                        if penta_lol.game_active():
                            riot_id = penta_lol.my_riot_id() or riot_id; break
                        time.sleep(1)
                    _bind_account(riot_id)
                    started_cs = False
                else:
                    log("Champion select detected \u2014 recording from draft.")
                    started_cs = True
                _free = disk_free_gb()
                if _free is not None and _free < 3.0:
                    log("WARNING: low disk space - %.1f GB free. Recording may fail. Cleaning old originals..." % _free)
                    try: cleanup_recordings()
                    except Exception: pass
                start_ts = time.time(); active = rec.start(); last_hb = time.time()
                REC_STATE["skipped_at"] = 0; REC_STATE["uploaded_at"] = 0   # 새 녹화 시작 → 이전 알림 지움
                saw_game = run; cs_grace = 0.0; ended_at = 0.0
                live_snaps = []; live_evts = []; last_snap_t = -999.0

            if active and run:
                saw_game = True; cs_grace = 0.0
                if not rec._recording():
                    log("Recording stream dropped \u2192 restarting automatically.")
                    active = rec.start()
                if not riot_id and penta_lol.game_active():
                    riot_id = penta_lol.my_riot_id(); _bind_account(riot_id)
                # Live Client 스냅샷(약 25초 간격) + 이벤트(매 루프) 수집
                try:
                    snap = penta_lol.live_snapshot()
                    if snap and (float(snap.get("t") or 0) - last_snap_t) >= 25:
                        snap["w"] = time.time(); live_snaps.append(snap); last_snap_t = float(snap.get("t") or 0)
                    _ev = penta_lol.live_events()      # 매 루프(4초) 폴링 → 게임 끝 GameEnd(승패) 안 놓침
                    if _ev:
                        if len(_ev) >= len(live_evts): live_evts = _ev   # 누락 방지: 가장 긴(누적) 이벤트 목록 유지 → 타워/전령 등 오브젝트 안 놓침
                        if not ended_at and any((e.get("EventName") == "GameEnd") for e in _ev):
                            ended_at = time.time(); log("Victory/Defeat screen detected - finishing recording.")
                except Exception: pass

            # 게임 종료: "계속" 클릭(프로세스 종료) 또는 GameEnd(승리/패배 화면) 후 잠깐 - 둘 중 먼저. 늘어짐 방지.
            _game_over = active and saw_game and ((not run) or (ended_at and (time.time()-ended_at) >= float(cfg.get("result_tail", 8))))
            if _game_over:
                # 승패(GameEnd)를 아직 못 받았으면 — 결과 화면이 살아있는 동안 몇 번 더 폴링해 확보(미확인 방지).
                if not any((e.get("EventName") == "GameEnd") for e in live_evts):
                    for _ in range(6):   # 최대 ~3초, 0.5초 간격 — 결과 화면이면 GameEnd 잡힘, 게임 종료됐으면 즉시 중단
                        try:
                            _elast = penta_lol.live_events()
                        except Exception:
                            break
                        if not _elast: break                 # Live API 응답 없음(게임 인스턴스 종료) → 더 못 받음
                        if len(_elast) >= len(live_evts): live_evts = _elast
                        if any((e.get("EventName") == "GameEnd") for e in _elast): break
                        time.sleep(0.5)
                # GameEnd로 결과 화면을 이미 담았으면 추가 tail 생략, 아니면(감지 실패) 기존처럼 잠깐 더.
                _tail = (0.0 if ended_at else float(cfg.get("postgame_tail", 6)))
                if _tail > 0:
                    log("Game over \u2014 capturing post-game screen\u2026")   # (매직 문자열 없음 → 녹화 상태 유지)
                    time.sleep(_tail)
                log("Game ended \u2014 recorded %d:%02d." % divmod(int(time.time()-(start_ts or time.time())),60))
                _vt0 = rec._vt0; vid = rec.stop(); active = False; rec.verified = False; saw_game = False; cs_grace = 0.0; ended_at = 0.0
                end_ts = time.time()
                if vid and os.path.isfile(vid):
                    threading.Thread(target=ingest_lol, args=(vid, riot_id, start_ts, end_ts, proxy, platform), kwargs={"live_data": {"snaps": list(live_snaps), "events": list(live_evts)}, "started_cs": started_cs, "vt0": _vt0}, daemon=True).start()
                riot_id = None; start_ts = None; started_cs = False; log("Idle.")

            elif active and not run and in_cs:
                cs_grace = 0.0   # 아직 챔피언 선택 → 계속 녹화
                if not rec._recording(): active = rec.start()

            elif active and not run:
                # 챔피언 선택은 끝났는데 게임 프로세스가 아직 없음 = 로딩 중 or 닷지/취소
                cs_grace += poll
                if cs_grace > 120:   # 2분간 게임이 안 뜨면 닷지로 보고 클립 폐기(ingest 안 함)
                    log("Champion select ended without a game (dodge?) \u2014 discarding clip.")
                    _v = rec.stop(); active = False; saw_game = False; cs_grace = 0.0; started_cs = False
                    try:
                        if _v and os.path.isfile(_v): os.remove(_v)
                    except Exception: pass
                    riot_id = None; start_ts = None; log("Idle.")
                elif not rec._recording():
                    active = rec.start()

            # ── 웹 표시용 실시간 상태 갱신 ──
            if active and rec._recording():
                REC_STATE.update(rec=True, text=("Recording" if saw_game else "Recording (champ select)"))
                if start_ts and (time.time()-last_hb)>=300:    # 녹화 중 5분마다 진행 로그(타임라인에 살아있음)
                    last_hb=time.time(); log("Recording\u2026 %d:%02d elapsed." % divmod(int(time.time()-start_ts),60))
            elif run:
                REC_STATE.update(rec=False, text="Game detected")
            elif in_cs:
                REC_STATE.update(rec=False, text="Champion select (recording starts at game)")
            else:
                REC_STATE.update(rec=False, text="Idle \u2014 auto-records when a game starts")
            time.sleep(poll)
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
    """더 이상 시작프로그램에 자동 등록하지 않는다. 이전 버전이 등록해 둔 항목이 있으면 제거한다."""
    if not getattr(sys, "frozen", False): return
    try:
        if is_autostart():
            set_autostart(False)
            log("Removed PENTA from Windows startup programs.")
    except Exception:
        pass

def _hide_console():
    if sys.platform != "win32": return
    try:
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd: ctypes.windll.user32.ShowWindow(hwnd, 0)   # SW_HIDE
    except Exception: pass

def _load_recorder_fonts():
    """Register bundled .ttf fonts so Tkinter can use Sora / IBM Plex Mono (Windows only)."""
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


def start_login_bridge(url):
    """127.0.0.1 미니 서버: 웹의 [이 PC의 레코더로 로그인] 버튼이 여기로 코드를 받아 즉시 로그인."""
    import http.server
    allowed = {"https://mypenta.netlify.app"}
    try:
        from urllib.parse import urlparse
        _u = urlparse(url if "://" in (url or "") else "https://" + (url or ""))
        if _u.scheme and _u.netloc: allowed.add(_u.scheme + "://" + _u.netloc)
    except Exception: pass
    class _H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_GET(self):
            if not self.path.startswith("/login"):
                self.send_response(404); self.end_headers(); return
            body = {}
            try:
                _pu = riot_key(device_get("riot_id")); _sec = device_secret()
                if _pu and _sec and cloud_state() == "cloud":
                    _code = secrets.token_urlsafe(24)
                    sb_rpc("issue_login_code", {"p_puuid": _pu, "p_secret": _sec, "p_code": _code})
                    body = {"code": _code}
                elif not _pu:
                    body = {"error": "no identity yet - play one game first"}
                else:
                    body = {"error": "cloud not configured"}
            except Exception as e:
                body = {"error": str(e)}
            data = json.dumps(body).encode("utf-8")
            _o = self.headers.get("Origin") or ""
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", _o if _o in allowed else "null")
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            try: self.wfile.write(data)
            except Exception: pass
    for _port in (47821, 47822, 47823):
        try:
            _srv = http.server.ThreadingHTTPServer(("127.0.0.1", _port), _H)
            threading.Thread(target=_srv.serve_forever, daemon=True).start()
            log("Web login bridge ready on 127.0.0.1:%d" % _port)
            return _srv
        except Exception:
            continue
    log("Web login bridge could not start (ports busy) - Archive button still works")
    return None


def run_gui(cfg, url):
    """Champagne card UI (v9): status orb + progress ring, Archive|Folder duo, log drawer."""
    import tkinter as tk
    import tkinter.font as _tkfont
    import math as _math
    # ── palette (champagne midnight) ──
    BG="#0A090E"; CARD="#14111A"; CARDHI="#2B2433"; HRLN="#2E2921"
    OUT_RDY="#4A4132"
    INK="#F2EFE5"; SSUB="#7A7366"; DIM="#8B8474"; FAINT="#59533F"
    GOLD="#DEC79C"; GOLD2="#F0E2C0"; ARCH="#E9D8AC"; SEGFG="#CFC8B4"
    DUOF="#191521"; DUOOUT="#3B3527"; DUODIV="#332D22"; ICOFG="#847D6E"
    RDY1,RDY2="#F6E8CC","#C9A661"
    REC1,REC2="#FF9282","#EE4560"
    PRL1,PRL2="#F4EFE0","#C8BC9B"
    SKY1,SKY2="#BFD8FB","#7BA5EC"
    EMR1,EMR2="#93F2C2","#2FBF83"
    HNY1,HNY2="#F8D28A","#EC9A50"
    def _mix(a,b,t):
        av=[int(a[i:i+2],16) for i in (1,3,5)]; bv=[int(b[i:i+2],16) for i in (1,3,5)]
        return "#%02x%02x%02x"%tuple(int(av[i]+(bv[i]-av[i])*t) for i in range(3))
    OUT_REC=_mix(REC2,CARD,0.45); OUT_SKY=_mix(SKY2,CARD,0.5); OUT_EMR=_mix(EMR2,CARD,0.5); OUT_HNY=_mix(HNY2,CARD,0.45)
    # 온보딩 캐러셀 호환 별칭(구 팔레트 이름 → 샴페인 등가색)
    SUB="#C9C2B0"; INK2="#C6BFAF"; REC=REC2; TEAL=EMR2; BLUE=SKY2; SURF="#1A1622"; LINE2="#332D22"
    W=376
    _load_recorder_fonts()
    root=tk.Tk(); root.title("myPENTA"); root.configure(bg=BG)
    # windowed(콘솔 없음) 빌드에서 tkinter 콜백 예외가 stderr 부재로 창을 통째로 닫는 것 방지 → crash.log 기록 후 계속.
    try: root.report_callback_exception = lambda et, e, tb: _write_crash(et, e, tb, "tk-callback")
    except Exception: pass
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
    SG  =_pick("Geist","Sora","Segoe UI")
    SG_S=_pick("Geist SemiBold","Sora SemiBold","Segoe UI Semibold","Segoe UI")
    PLEX=_pick("Geist Mono","IBM Plex Mono","Consolas","Segoe UI")
    UI=SG; SEMI=SG_S; MON=PLEX
    BASE_H, SET_H, LOG_H = 138, 246, 210
    root.geometry(f"{W}x{BASE_H}"); root.resizable(False, True)
    st={"log":False,"settings":False}

    # ── champagne card canvas ──
    M=8; CH=121
    HEAD_H=54
    cv=tk.Canvas(root,width=W,height=CH,bg=BG,highlightthickness=0,bd=0); cv.pack(fill="x")
    x1,y1,x2,y2=M,M,W-M,M+CH-2*M+4
    R=16
    def _rr(a,b,c,d,r,**kw):
        return cv.create_polygon([a+r,b,c-r,b,c,b,c,b+r,c,d-r,c,d,c-r,d,a+r,d,a,d,a,d-r,a,b+r,a,b],smooth=True,**kw)
    card=_rr(x1,y1,x2,y2,R,fill=CARD,outline=OUT_RDY)
    cv.create_line(x1+R+14,y1+1,x2-R-14,y1+1,fill=CARDHI)     # top hairline highlight

    # ── row 1: orb + status ──
    OX,OY=x1+27,y1+27
    IT={}
    IT["bloom"]=cv.create_oval(OX-12,OY-12,OX+12,OY+12,fill=_mix(RDY2,CARD,0.72),outline="")
    IT["ring_tr"]=cv.create_arc(OX-12,OY-12,OX+12,OY+12,style="arc",outline="#2A2620",width=2,start=90,extent=359.0,state="hidden")
    IT["ring_fg"]=cv.create_arc(OX-12,OY-12,OX+12,OY+12,style="arc",outline=PRL2,width=2,start=90,extent=0,state="hidden")
    IT["ripple"]=cv.create_oval(OX-8,OY-8,OX+8,OY+8,outline="",width=1)
    IT["core"]=cv.create_oval(OX-6,OY-6,OX+6,OY+6,fill=RDY2,outline="")
    IT["corein"]=cv.create_oval(OX-5,OY-5,OX+1,OY+1,fill=RDY1,outline="")
    IT["spec"]=cv.create_oval(OX-3,OY-4,OX-1,OY-2,fill="#FFFFFF",outline="")
    IT["chk1"]=cv.create_line(OX-3.4,OY+0.2,OX-0.9,OY+2.9,fill="#0D2A1D",width=2,capstyle="round",state="hidden")
    IT["chk2"]=cv.create_line(OX-0.9,OY+2.9,OX+3.8,OY-2.8,fill="#0D2A1D",width=2,capstyle="round",state="hidden")
    sname=cv.create_text(x1+48,y1+19,anchor="w",text="Starting\u2026",fill=INK,font=(SG_S,12))
    ssub =cv.create_text(x1+48,y1+37,anchor="w",text="",fill=SSUB,font=(UI,9))
    num  =cv.create_text(x2-18,OY,anchor="e",text="",fill="#D8CFBB",font=(MON,11))
    cv.create_line(x1+14,y1+HEAD_H,x2-14,y1+HEAD_H,fill=HRLN)

    # ── row 2: Archive|Folder duo + icons ──
    AY=y1+HEAD_H+27
    def _seg_icon_grid(cx,cy,col):
        s=2.6; out=[]
        for dx in (-(s+0.9),0.9):
            for dy in (-(s+0.9),0.9):
                out.append(cv.create_rectangle(cx+dx,cy+dy,cx+dx+s,cy+dy+s,fill=col,outline=""))
        return out
    def _seg_icon_folder(cx,cy,col):
        return [cv.create_polygon([cx-5,cy+4,cx-5,cy-4,cx-1,cy-4,cx,cy-2,cx+5,cy-2,cx+5,cy+4],fill=col,outline="")]
    dx0=x1+14
    t_arc=cv.create_text(dx0+30,AY,anchor="w",text="Archive",fill=ARCH,font=(SG_S,10))
    aw=cv.bbox(t_arc)[2]+13
    ic_arc=_seg_icon_grid(dx0+18,AY,ARCH)
    t_fld=cv.create_text(aw+31,AY,anchor="w",text="Folder",fill=SEGFG,font=(SG_S,10))
    fw=cv.bbox(t_fld)[2]+13
    ic_fld=_seg_icon_folder(aw+19,AY,SEGFG)
    duo=_rr(dx0,AY-15,fw,AY+15,10,fill=DUOF,outline=DUOOUT)
    duodiv=cv.create_line(aw,AY-15+5,aw,AY+15-5,fill=DUODIV)
    cv.tag_lower(duo,t_arc)
    for _it in ic_arc+ic_fld: cv.tag_raise(_it)
    def _hover(items, on_fill, off_fill, group_items=None, outline_on=None):
        g="hg%d"%items[0]
        for it in items+(group_items or []): cv.addtag_withtag(g,it)
        def _en(_e):
            for it in items: cv.itemconfig(it,fill=on_fill)
            if outline_on: cv.itemconfig(duo,outline=outline_on)
            cv.config(cursor="hand2")
        def _lv(_e):
            for it in items: cv.itemconfig(it,fill=off_fill)
            if outline_on: cv.itemconfig(duo,outline=DUOOUT)
            cv.config(cursor="")
        cv.tag_bind(g,"<Enter>",_en); cv.tag_bind(g,"<Leave>",_lv)
        return g
    _ICONS={}
    ICON_ON="#4A4131"

    # ── log/settings/quit callbacks defined before bindings that use them ──
    def open_gallery():
        def _go():
            try:
                _pu = riot_key(device_get("riot_id")); _sec = device_secret()
                if _pu and _sec and cloud_state() == "cloud":
                    _code = secrets.token_urlsafe(24)
                    sb_rpc("issue_login_code", {"p_puuid": _pu, "p_secret": _sec, "p_code": _code})
                    open_app(url + "/#code=" + _code); return
                else:
                    log("Login skipped: riot_id=" + ("set" if _pu else "MISSING (play one game first)") + ", cloud=" + cloud_state())
            except Exception as e:
                log(f"Login code skipped (gallery still opens): {e}")
            try: open_app(url)
            except Exception: pass
        threading.Thread(target=_go, daemon=True).start()
    def open_folder():
        try:
            if sys.platform=="win32": os.startfile(REC_DIR)
        except Exception: pass
    def do_quit():
        try:   # 녹화/업로드 중 실수로 닫아 판을 날리는 것 방지
            if REC_STATE.get("recording") or REC_STATE.get("uploading") or REC_STATE.get("preparing"):
                from tkinter import messagebox
                _what = "Recording" if REC_STATE.get("recording") else "Upload"
                if not messagebox.askyesno("myPENTA",
                        _what + " is in progress.\nQuit anyway? The current game may be lost.",
                        parent=root):
                    return
        except Exception:
            pass
        try: root.destroy()
        except Exception: pass
        os._exit(0)
    def _save_cfg():
        try: _atomic_write_json(CONFIG_PATH, cfg)
        except Exception as e: log(f"Failed to save settings: {e}")

    ga=_hover([t_arc]+ic_arc,"#F4E7C4",ARCH,outline_on="#4E4530")
    cv.tag_bind(ga,"<Button-1>",lambda e: open_gallery())
    gf=_hover([t_fld]+ic_fld,"#F0EADA",SEGFG,outline_on="#4E4530")
    cv.tag_bind(gf,"<Button-1>",lambda e: open_folder())

    def _ctip(item,text):
        tip={"w":None}
        def show(_e):
            if tip["w"] or not text: return
            try:
                bx=cv.bbox(item); x=cv.winfo_rootx()+(bx[0]+bx[2])//2-len(text)*3; y=cv.winfo_rooty()+bx[1]-23
                w=tk.Toplevel(cv); w.wm_overrideredirect(True); w.configure(bg=DUOOUT)
                tk.Label(w,text=text,bg="#1D1926",fg=INK,font=(SG,8),padx=7,pady=2).pack(padx=1,pady=1)
                w.wm_geometry("+%d+%d"%(max(0,x),max(0,y))); tip["w"]=w
            except Exception: pass
        def hide(_e):
            if tip["w"]:
                try: tip["w"].destroy()
                except Exception: pass
                tip["w"]=None
        cv.tag_bind(item,"<Enter>",show,add="+"); cv.tag_bind(item,"<Leave>",hide,add="+")
    def _cicon(glyph,xr,cmd,statekey,tip):
        t=cv.create_text(xr,AY,text=glyph,fill=ICOFG,font=(SG_S,12))
        g="ci%d"%t; cv.addtag_withtag(g,t)
        def _act(): return statekey and st.get(statekey)
        cv.tag_bind(g,"<Button-1>",lambda e: cmd())
        cv.tag_bind(g,"<Enter>",lambda e:(cv.itemconfig(t,fill=GOLD2 if _act() else ARCH),cv.config(cursor="hand2")))
        cv.tag_bind(g,"<Leave>",lambda e:(cv.itemconfig(t,fill=GOLD if _act() else ICOFG),cv.config(cursor="")))
        _ctip(t,tip)
        return (t,)
    _ICONS["set"]=_cicon("\u2699",x2-26,lambda: toggle_settings(),"settings","Settings")
    _ICONS["log"]=_cicon("\u25A4",x2-56,lambda: toggle_log(),"log","Log")
    cld=cv.create_text(x2-86,AY,text="\u2601",fill=ICOFG,font=(SG_S,12))
    cdot=cv.create_oval(x2-80,AY-9,x2-75,AY-4,fill="#3BC489",outline="")
    _ctip(cld,"Cloud")

    # ── Log area (hidden until needed) ──
    logwrap=tk.Frame(root,bg=BG)
    errbar=tk.Label(logwrap,text="",bg="#2E2213",fg="#F3CE8F",font=(UI,9),anchor="w",padx=11,pady=6,justify="left",wraplength=W-44)
    logtxt=tk.Text(logwrap,bg="#0E0C12",fg=DIM,font=(MON,9),bd=0,padx=11,pady=8,height=8,wrap="word",state="disabled")

    # ── Update banner ──
    UPD_H=34
    updbar=tk.Label(root,text="",bg="#241D0E",fg=GOLD,font=(UI,9,"bold"),anchor="w",padx=12,pady=7,cursor="hand2")
    updbar.bind("<Button-1>",lambda e: open_app(UPDATE_INFO.get("url") or url))

    # ── Settings panel ──
    PANEL="#0F0D14"; PLINE="#332D22"; PSURF="#1A1622"
    optwrap=tk.Frame(root,bg=PANEL,highlightbackground=PLINE,highlightthickness=1)
    _hdrow=tk.Frame(optwrap,bg=PANEL); _hdrow.pack(fill="x",padx=15,pady=(12,6))
    tk.Label(_hdrow,text="RECORDING SETTINGS",bg=PANEL,fg="#B8AF9C",font=(SEMI,8,"bold")).pack(side="left")
    now_lbl=tk.Label(_hdrow,text="",bg=PANEL,fg=FAINT,font=(MON,8)); now_lbl.pack(side="right")
    SCALE_OPTS=[("Auto (best)","auto"),("Source","source"),("1080p","1080"),("720p","720"),("480p","480")]
    ENC_OPTS=[("Auto (GPU first)","auto"),("GPU \u00b7 NVIDIA NVENC","nvenc"),("GPU \u00b7 AMD AMF","amf"),("GPU \u00b7 Intel QSV","qsv"),("CPU \u00b7 x264","x264")]
    def opt_row(label, opts, key):
        row=tk.Frame(optwrap,bg=PANEL); row.pack(fill="x",padx=15,pady=3)
        tk.Label(row,text=label,bg=PANEL,fg=DIM,font=(UI,9),width=8,anchor="w").pack(side="left")
        cur=str(cfg.get(key,"auto")); m={l:v for l,v in opts}
        curlbl=next((l for l,v in opts if v==cur), opts[0][0])
        var=tk.StringVar(value=curlbl)
        def on_sel(lbl,k=key,mp=m,lb=label):
            cfg[k]=mp[lbl]; _save_cfg(); log(f"Setting: {lb} \u2192 {lbl} (applies to next recording)")
        om=tk.OptionMenu(row,var,*[l for l,_ in opts],command=on_sel)
        om.config(bg=PSURF,fg=INK,font=(UI,9),activebackground="#241E2E",activeforeground=INK,relief="flat",bd=0,highlightthickness=1,highlightbackground=PLINE,anchor="w",padx=11,pady=4,cursor="hand2")
        try: om["menu"].config(bg=PSURF,fg=INK,activebackground=GOLD,activeforeground="#0A090E",font=(UI,9),bd=0,activeborderwidth=0)
        except Exception: pass
        om.pack(side="left",fill="x",expand=True)
    opt_row("Quality",SCALE_OPTS,"scale")
    opt_row("Encoder",ENC_OPTS,"encoder")
    KEEP_OPTS=[("Last 20 games","20"),("Last 10 games","10"),("Last 50 games","50"),("Keep all (no cleanup)","0")]
    opt_row("Keep",KEEP_OPTS,"keep_games")
    # 오디오 소스: 기본은 '기본 출력장치' 루프백(스피커로 나오는 전부). 특정 장치를 고르면 그 장치 소리만 녹음.
    AUD_OPTS=[("Auto (default output)","")]
    try:
        import pyaudiowpatch as _pa
        _pp=_pa.PyAudio()
        try:
            _seen=set()
            for _lb in _pp.get_loopback_device_info_generator():
                _nm=str(_lb.get("name","")).replace(" [Loopback]","").strip()
                if _nm and _nm not in _seen:
                    _seen.add(_nm); AUD_OPTS.append((_nm[:34], _nm))
        finally:
            try: _pp.terminate()
            except Exception: pass
    except Exception:
        pass
    opt_row("Audio",AUD_OPTS,"audio_device")
    tk.Label(optwrap,text="Auto = best quality, GPU-accelerated so your game stays smooth",bg=PANEL,fg=FAINT,font=(UI,8),wraplength=W-50,justify="left").pack(anchor="w",padx=15,pady=(6,4))
    _cleanrow=tk.Frame(optwrap,bg=PANEL); _cleanrow.pack(fill="x",padx=15,pady=(0,12))
    def _do_clean():
        threading.Thread(target=cleanup_recordings,kwargs={"manual":True},daemon=True).start()
    tk.Button(_cleanrow,text="Clean up originals now",command=_do_clean,bg=PSURF,fg=INK,font=(UI,9),relief="flat",bd=0,highlightthickness=1,highlightbackground=PLINE,activebackground="#241E2E",activeforeground=INK,cursor="hand2",padx=11,pady=4).pack(side="left")
    _fr=disk_free_gb()
    tk.Label(_cleanrow,text=("Disk free: %.0f GB" % _fr) if _fr is not None else "",bg=PANEL,fg=FAINT,font=(UI,8)).pack(side="left",padx=10)

    # ── Panel toggle + resize ──
    def _resize():
        h=BASE_H+(SET_H if st["settings"] else 0)+(LOG_H if st["log"] else 0)+(UPD_H if st.get("upd") else 0)
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
        _li=_ICONS.get("log")
        if _li:
            try: cv.itemconfig(_li[0],fill=GOLD if open_ else ICOFG)
            except Exception: pass
        _resize()
    def set_settings(open_):
        if open_ and st["log"]: set_log(False)
        st["settings"]=open_
        if open_: optwrap.pack(fill="x",padx=13,pady=(3,2))
        else: optwrap.pack_forget()
        _si=_ICONS.get("set")
        if _si:
            try: cv.itemconfig(_si[0],fill=GOLD if open_ else ICOFG)
            except Exception: pass
        _resize()
    def toggle_log(): set_log(not st["log"])
    def toggle_settings(): set_settings(not st["settings"])
    root.protocol("WM_DELETE_WINDOW", do_quit)   # X → 종료. 최소화(_)는 일반 작업표시줄.

    def _prep_and_run():
        global FFMPEG
        try:
            if not FFMPEG: FFMPEG=ensure_ffmpeg()
        except Exception as e:
            log(f"Tool setup issue: {e}")
        if not FFMPEG:
            log("\u26a0 ffmpeg setup failed \u2014 check your internet connection and restart."); return
        if cloud_state()=="cloud": cloud_selftest()    # 시작 시 업로드 권한 즉시 진단(게임 없이)
        recorder_loop(cfg)
    threading.Thread(target=_prep_and_run,daemon=True).start()

    # ── state machinery: orb colors / ring / sleep / animations ──
    _rec={"since":None,"blink":False,"psince":None,"stk":"","sleep":False,"act":time.time(),"ph":0.0,"rip":-1,"spin":0.0}
    _SLEEPABLE=[(sname,INK),(ssub,SSUB),(t_arc,ARCH),(t_fld,SEGFG),(cld,ICOFG),(_ICONS["log"][0],ICOFG),(_ICONS["set"][0],ICOFG)]
    def _wake(_e=None):
        _rec["act"]=time.time()
        if _rec["sleep"]: _apply_sleep(False)
    def _apply_sleep(on):
        if on==_rec["sleep"]: return
        _rec["sleep"]=on
        try:
            for it,col in _SLEEPABLE: cv.itemconfig(it,fill=(FAINT if on else col))
            for it in ic_arc: cv.itemconfig(it,fill=(FAINT if on else ARCH))
            for it in ic_fld: cv.itemconfig(it,fill=(FAINT if on else SEGFG))
            cv.itemconfig(duo,outline=(_mix(DUOOUT,CARD,0.5) if on else DUOOUT))
            cv.itemconfig(card,outline=(_mix(OUT_RDY,CARD,0.55) if on else OUT_RDY))
            cv.itemconfig(num,fill=("#3A362C" if on else "#D8CFBB"))
        except Exception: pass
    root.bind_all("<Motion>",_wake,add="+"); root.bind_all("<Button>",_wake,add="+"); root.bind_all("<Key>",_wake,add="+")

    def _orb(c1,c2,outline):
        try:
            cv.itemconfig(IT["core"],fill=c2); cv.itemconfig(IT["corein"],fill=c1)
            cv.itemconfig(IT["bloom"],fill=_mix(c2,CARD,0.72))
            if not _rec["sleep"]: cv.itemconfig(card,outline=outline)
        except Exception: pass
    def _ring(show,pct,color):
        try:
            cv.itemconfig(IT["ring_tr"],state=("normal" if show else "hidden"))
            cv.itemconfig(IT["ring_fg"],state=("normal" if show else "hidden"),outline=color)
            if show and pct>0:
                cv.itemconfig(IT["ring_fg"],start=90,extent=-max(1.0,min(359.0,pct*3.59)))
        except Exception: pass
    def _check(show):
        try:
            stt="normal" if show else "hidden"
            cv.itemconfig(IT["chk1"],state=stt); cv.itemconfig(IT["chk2"],state=stt)
            cv.itemconfig(IT["spec"],state=("hidden" if show else "normal"))
            cv.itemconfig(IT["corein"],state=("hidden" if show else "normal"))
            r=7 if show else 6
            cv.coords(IT["core"],OX-r,OY-r,OX+r,OY+r)
        except Exception: pass

    def _anim():
        root.after(90,_anim)
        try:
            k=_rec["stk"]
            # breathe (ready) — sleep 중엔 더 느리게
            if k in ("ready","prep"):
                _rec["ph"]+= (0.045 if _rec["sleep"] else 0.09)
                d=1.0+0.09*_math.sin(_rec["ph"])
                r1=6*d; r2=12*d
                cv.coords(IT["core"],OX-r1,OY-r1,OX+r1,OY+r1)
                cv.coords(IT["bloom"],OX-r2,OY-r2,OX+r2,OY+r2)
            # ripple (recording enter)
            if _rec["rip"]>=0:
                s=_rec["rip"]; r=8+s*1.5
                cv.coords(IT["ripple"],OX-r,OY-r,OX+r,OY+r)
                cv.itemconfig(IT["ripple"],outline=_mix(REC2,CARD,min(1.0,s/10.0)))
                _rec["rip"]+=1
                if _rec["rip"]>10:
                    _rec["rip"]=-1; cv.itemconfig(IT["ripple"],outline="")
            # indeterminate spin (processing, pct 0)
            if k=="processing" and (REC_STATE.get("prep_pct") or 0)<=0:
                _rec["spin"]=(_rec["spin"]-14)%360
                cv.itemconfig(IT["ring_fg"],start=_rec["spin"],extent=-80)
        except Exception:
            pass

    def poll():
        root.after(500, poll)   # 다음 갱신을 먼저 예약 → 본문에서 예외가 나도 GUI 루프가 멈추지 않음
        if UPDATE_INFO.get("tag") and not st.get("upd"):
            st["upd"]=True
            updbar.config(text="New version "+UPDATE_INFO["tag"]+" is available - click here to download")
            updbar.pack(fill="x",side="bottom")
            _resize()
        appended=False
        for _ in range(150):
            try: line=GUI_Q.get_nowait()
            except Exception: break
            logtxt.config(state="normal"); logtxt.insert("end",line+"\n"); appended=True   # 패널이 닫혀 있어도 항상 기록
        if appended:
            n=int(logtxt.index("end-1c").split(".")[0])
            if n>300: logtxt.delete("1.0",f"{n-300}.0")
            logtxt.see("end"); logtxt.config(state="disabled")
        _rng=REC_STATE.get("recording"); _now=time.time(); _up=REC_STATE.get("uploaded_at",0)
        if _rng and not _rec.get("was_rec"):       # 녹화 시작 → 로그 자동 열림 + 리플 1회
            if not st["log"]: set_log(True)
            _rec["rip"]=0
        _rec["was_rec"]=_rng
        _uploading=bool(REC_STATE.get("uploading")); _preparing=bool(REC_STATE.get("preparing"))
        _doneToast=bool(_up and (_now-_up<5))
        _skip=REC_STATE.get("skipped_at") and (_now-REC_STATE.get("skipped_at",0)<6)
        _err=LAST_ERR.get("msg") and (time.time()-LAST_ERR.get("t",0)<8)

        # ── encoder/scale label (settings header) ──
        ea=(REC_STATE.get("encoder") or "").lower()
        if "nvenc" in ea: enc="NVENC"; is_sw=False
        elif "amf" in ea: enc="AMF"; is_sw=False
        elif "qsv" in ea: enc="QSV"; is_sw=False
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
        else: th=(720 if is_sw else min(1080,_sh))
        if th>_sh: th=_sh
        _optxt=f"{th}p \u00b7 {enc}"
        if _optxt!=_rec.get("opt"):
            _rec["opt"]=_optxt
            try: now_lbl.config(text=_optxt)
            except Exception: pass

        # ── cloud dot ──
        try:
            _cs=cloud_state()
            cdot_col={"cloud":"#3BC489","readonly":HNY2}.get(_cs,"#6B655A")
            cv.itemconfig(cdot,fill=cdot_col)
        except Exception: pass

        def show(k,name,sub,c1,c2,outline,numtxt="",ring=False,pct=0,ringcol=PRL2,check=False):
            if _rec["stk"]!=k:
                _rec["stk"]=k
                _orb(c1,c2,outline); _check(check)
                if not ring: _ring(False,0,ringcol)
                if k not in ("ready","prep"):   # 고정 크기 복원(브리드 중지 상태)
                    try:
                        rr=7 if check else 6
                        cv.coords(IT["core"],OX-rr,OY-rr,OX+rr,OY+rr)
                        cv.coords(IT["bloom"],OX-12,OY-12,OX+12,OY+12)
                    except Exception: pass
            if ring: _ring(True,pct,ringcol)
            try:
                cv.itemconfig(sname,text=name)
                cv.itemconfig(ssub,text=sub)
                cv.itemconfig(num,text=numtxt)
            except Exception: pass

        if _rng:
            if _rec["since"] is None: _rec["since"]=_now
            _rec["psince"]=None
            _rec["blink"]=not _rec["blink"]
            _el=int(_now-_rec["since"]); _mm,_ss=divmod(_el,60)
            _tm=("%d:%02d" if _rec["blink"] else "%d %02d")%(_mm,_ss)   # 콜론 블링크(모노 폭 동일)
            show("recording","Recording",f"{th}p \u00b7 {enc}",REC1,REC2,OUT_REC,numtxt=_tm)
            try: cv.itemconfig(num,fill="#FFB1AA")
            except Exception: pass
        elif _uploading:
            _rec["since"]=None
            _pct=REC_STATE.get("upload_pct") or 0
            show("uploading","Uploading","\ud074\ub77c\uc6b0\ub4dc \uc804\uc1a1 \uc911",SKY1,SKY2,OUT_SKY,
                 numtxt=(("%d%%"%_pct) if _pct>0 else ""),ring=True,pct=_pct,ringcol=SKY2)
            try: cv.itemconfig(num,fill="#AFCBF4")
            except Exception: pass
        elif _preparing:
            _rec["since"]=None
            _pp=REC_STATE.get("prep_pct") or 0
            show("processing","Processing","\uac24\ub7ec\ub9ac\uc6a9 \uc555\ucd95 \uc911",PRL1,PRL2,OUT_RDY,
                 numtxt=(("%d%%"%_pp) if _pp>0 else ""),ring=True,pct=_pp,ringcol=PRL2)
            try: cv.itemconfig(num,fill="#D8CFBB")
            except Exception: pass
        elif _skip:
            _rec["since"]=None
            _why=REC_STATE.get("skipped_why") or "not saved"
            show("skip","Not saved",_why[:38],HNY1,HNY2,OUT_HNY)
        elif _doneToast:
            _rec["since"]=None
            show("done","Uploaded","\uc544\uce74\uc774\ube0c\uc5d0 \ucd94\uac00\ub428",EMR1,EMR2,OUT_EMR,check=True)
        elif _err:
            _rec["since"]=None
            if not st["log"]: set_log(True)
            else:
                try: errbar.config(text="\u26a0 "+LAST_ERR["msg"])
                except Exception: pass
            show("warn","\ud655\uc778 \ud544\uc694",str(LAST_ERR.get("msg",""))[:38],HNY1,HNY2,OUT_HNY)
        else:
            _rec["since"]=None; _rec["blink"]=False
            if REC_STATE.get("ready"):
                show("ready","Ready","\uac8c\uc784 \uc2e4\ud589 \uc2dc \uc790\ub3d9 \ub179\ud654",RDY1,RDY2,OUT_RDY)
            else:
                show("prep","Preparing","\ub3c4\uad6c \uc900\ube44 \uc911",RDY1,RDY2,OUT_RDY)
        # ── sleep (ready에서 6초 무동작) ──
        if _rec["stk"]=="ready" and (time.time()-_rec["act"]>6):
            _apply_sleep(True)
        elif _rec["stk"]!="ready" and _rec["sleep"]:
            _apply_sleep(False)
    try: root.update()
    except Exception: pass
    try:  # 내용에 맞춰 창 높이 자동
        root.update_idletasks(); _rh=root.winfo_reqheight()
        if _rh>=60: BASE_H=_rh; root.geometry(f"{W}x{BASE_H}")
    except Exception: pass
    if sys.platform=="win32": _hide_console()
    poll()
    _anim()

    # ── 첫 실행 온보딩: 한 슬라이드씩 넘겨보는 캐러셀 ──
    def _show_onboarding():
        try:
            ob=tk.Toplevel(root); ob.title("myPENTA")
            ob.configure(bg=BG); ob.resizable(False,False)
            try: ob.iconphoto(True, tk.PhotoImage(data=_PENTA_ICON))
            except Exception: pass
            ob.transient(root); ob.grab_set()
            OW,OH=468,470
            try:
                root.update_idletasks()
                px,py=root.winfo_x(),root.winfo_y(); pw=root.winfo_width()
                ox=px+(pw-OW)//2; oy=max(0,py+24)
                ob.geometry("%dx%d+%d+%d"%(OW,OH,max(0,ox),oy))
            except Exception:
                ob.geometry("%dx%d"%(OW,OH))
            WRAP=OW-72

            def _close_ob():
                try: cfg["onboarded"]=True; _atomic_write_json(CONFIG_PATH, cfg)
                except Exception: pass
                try: ob.grab_release(); ob.destroy()
                except Exception: pass
            def _open_manual():
                open_app((url.rstrip("/") if url else "") + "/manual.html" if url else "https://mypenta.netlify.app/manual.html")

            # ── 각 슬라이드의 큰 아이콘(캔버스에 직접 그림) ──
            def _art(cvp, kind):
                w=int(cvp["width"]); cx=w//2; cy=70
                if kind=="welcome":
                    # 골드 5각별 (브랜드)
                    import math as _m
                    pts=[]
                    for i in range(10):
                        ang=-_m.pi/2 + i*_m.pi/5; rr=34 if i%2==0 else 14
                        pts+=[cx+rr*_m.cos(ang), cy+rr*_m.sin(ang)]
                    cvp.create_polygon(pts, fill=GOLD, outline="")
                elif kind=="record":
                    # 모니터 + 빨간 REC 점
                    cvp.create_rectangle(cx-42,cy-30,cx+42,cy+20, outline=INK2, width=2)
                    cvp.create_rectangle(cx-14,cy+20,cx+14,cy+28, fill=INK2, outline="")
                    cvp.create_oval(cx-38,cy-26,cx-26,cy-14, fill=REC, outline="")
                    cvp.create_text(cx+6,cy-4, text="REC", fill=INK2, font=(SEMI,13,"bold"))
                elif kind=="archive":
                    # 클라우드 + 위 화살표(업로드)
                    cvp.create_oval(cx-40,cy-6,cx-8,cy+26, fill=SURF, outline=BLUE, width=2)
                    cvp.create_oval(cx-16,cy-18,cx+24,cy+26, fill=SURF, outline=BLUE, width=2)
                    cvp.create_oval(cx+6,cy-2,cx+40,cy+26, fill=SURF, outline=BLUE, width=2)
                    cvp.create_rectangle(cx-38,cy+18,cx+38,cy+30, fill=BG, outline="")
                    cvp.create_line(cx,cy+22,cx,cy-8, fill=TEAL, width=3, arrow="first")
                elif kind=="multipov":
                    # 2x2 멀티 화면 + 가운데 골드 하이라이트
                    for i,(dx,dy) in enumerate([(-40,-28),(6,-28),(-40,8),(6,8)]):
                        col=GOLD if i==1 else INK2
                        cvp.create_rectangle(cx+dx,cy+dy,cx+dx+34,cy+dy+30, outline=col, width=2)
                    cvp.create_text(cx,cy+52, text="\u25B6", fill=GOLD, font=(SEMI,14,"bold"))
                elif kind=="ready":
                    # 체크 원
                    cvp.create_oval(cx-32,cy-32,cx+32,cy+32, outline=TEAL, width=3)
                    cvp.create_line(cx-15,cy+2,cx-4,cy+14, fill=TEAL, width=4, capstyle="round")
                    cvp.create_line(cx-4,cy+14,cx+17,cy-14, fill=TEAL, width=4, capstyle="round")

            # ── 슬라이드 내용 (아이콘 kind, 제목, 본문) ──
            SLIDES=[
                ("welcome","Welcome to myPENTA",
                 "League of Legends \uac8c\uc784\uc744 \uc790\ub3d9\uc73c\ub85c \ub179\ud654\ud558\uace0, \uc6f9\uc5d0\uc11c \ub2e4\uc2dc\ubcf4\uae30\ub85c \ubaa8\uc544\ubcf4\ub294 \ub3c4\uad6c\uc608\uc694.\n\n\uba87 \uac00\uc9c0\ub9cc \ubcf4\uba74 \ubc14\ub85c \uc2dc\uc791\ud560 \uc218 \uc788\uc5b4\uc694. \u2192"),
                ("record","1. \uac8c\uc784\ub9cc \ud558\uc138\uc694",
                 "\uc774 \ucc3d\uc744 \ucf1c\ub454 \ucc44\ub85c \ub86f\uc744 \ud50c\ub808\uc774\ud558\uba74, \uac8c\uc784\uc774 \ub05d\ub098\ub294 \uc21c\uac04 \uc601\uc0c1\uacfc \uc804\uc801\uc774 \uc790\ub3d9\uc73c\ub85c \uc800\uc7a5\ub3fc\uc694.\n\n\ub179\ud654 \ubc84\ud2bc\ub3c4, \uc124\uc815\ub3c4 \ud544\uc694 \uc5c6\uc5b4\uc694. \uadf8\ub0e5 \ucf1c\ub450\uae30\ub9cc \ud558\uc138\uc694."),
                ("archive","2. Archive \ub85c \ud655\uc778",
                 "\uc544\ub798 \uae08\uc0c9 Archive \ubc84\ud2bc\uc744 \ub204\ub974\uba74, \ub0b4 \uc601\uc0c1\uacfc \uc804\uc801\uc774 \ubaa8\uc778 \uc6f9\ud398\uc774\uc9c0\uac00 \uc5f4\ub824\uc694.\n\n\uadf8 \ube0c\ub77c\uc6b0\uc800\uc5d0 \uc790\ub3d9\uc73c\ub85c \ub85c\uadf8\uc778\ub418\ub2c8, \ub530\ub85c \uac00\uc785\ud560 \uac83\ub3c4 \uc5c6\uc2b5\ub2c8\ub2e4."),
                ("multipov","3. \uc5ec\ub7ec \uc2dc\uc810\u00b7\uac10\ub3c5\ud310",
                 "\uac19\uc740 \uacbd\uae30\ub97c \uce5c\uad6c\ub4e4\uacfc \uac01\uc790 \ub179\ud654\ud574 \uc62c\ub9ac\uba74, \ud55c \uad50\uc804\uc744 \uc5ec\ub7ec \uc790\ub9ac\uc5d0\uc11c \ub3d9\uc2dc\uc5d0 \ubcfc \uc218 \uc788\uc5b4\uc694.\n\n\uac10\ub3c5\ud310\uc744 \ucf1c\uba74 \ud0ac \uc21c\uac04\ub9c8\ub2e4 \uac00\uc7a5 \uc88b\uc740 \uc2dc\uc810\uc73c\ub85c \uc790\ub3d9 \uc804\ud658\ub3fc\uc694."),
                ("ready","\uc900\ube44 \ub05d!",
                 "\uc774\uc81c \ub86f\uc744 \ucf1c\uace0 \ud55c \ud310 \ud50c\ub808\uc774\ud574\ubcf4\uc138\uc694.\n\n\ucc98\uc74c \uc2e4\ud589\ud560 \ub54c Windows \uacbd\uace0\uac00 \ub73c \uc218 \uc788\ub294\ub370, \uc815\uc0c1\uc774\uc5d0\uc694 \u2014 '\ucd94\uac00 \uc815\ubcf4 \u2192 \uc2e4\ud589'\uc744 \ub204\ub974\uba74 \ub429\ub2c8\ub2e4."),
            ]
            state={"i":0}

            # 슬라이드 표시 영역
            body=tk.Frame(ob,bg=BG); body.pack(fill="both",expand=True,padx=36,pady=(26,0))
            art=tk.Canvas(body,width=OW-72,height=150,bg=BG,highlightthickness=0); art.pack()
            ttl=tk.Label(body,text="",bg=BG,fg=GOLD,font=(SEMI,17,"bold")); ttl.pack(pady=(6,0))
            txt=tk.Label(body,text="",bg=BG,fg=SUB,font=(UI,10),wraplength=WRAP,justify="center"); txt.pack(pady=(10,0))

            # 하단: 점 인디케이터 + 버튼
            foot=tk.Frame(ob,bg=BG); foot.pack(fill="x",side="bottom",padx=30,pady=18)
            dots=tk.Canvas(foot,width=OW-60,height=14,bg=BG,highlightthickness=0); dots.pack()
            navrow=tk.Frame(foot,bg=BG); navrow.pack(fill="x",pady=(12,0))
            btn_prev=tk.Button(navrow,text="\uc774\uc804",bg="#181B21",fg=INK,font=(UI,9),relief="flat",bd=0,
                      highlightthickness=1,highlightbackground=LINE2,activebackground="#23272F",activeforeground=INK,
                      cursor="hand2",padx=15,pady=7)
            btn_prev.pack(side="left")
            btn_skip=tk.Button(navrow,text="\uac74\ub108\ub6f0\uae30",bg=BG,fg=DIM,font=(UI,9),relief="flat",bd=0,
                      activebackground=BG,activeforeground=INK2,cursor="hand2",padx=8,pady=7)
            btn_skip.pack(side="left",padx=6)
            btn_next=tk.Button(navrow,text="\ub2e4\uc74c",bg=GOLD,fg="#0a0a0a",font=(SEMI,10,"bold"),relief="flat",bd=0,
                      activebackground=GOLD2,activeforeground="#0a0a0a",cursor="hand2",padx=22,pady=7)
            btn_next.pack(side="right")

            def _render():
                i=state["i"]; n=len(SLIDES)
                kind,title,bodytxt=SLIDES[i]
                art.delete("all"); _art(art, kind)
                ttl.config(text=title); txt.config(text=bodytxt)
                # 점 인디케이터
                dots.delete("all"); gap=16; total=(n-1)*gap; x0=int(dots["width"])//2-total//2
                for k in range(n):
                    x=x0+k*gap
                    if k==i: dots.create_oval(x-4,3,x+4,11, fill=GOLD, outline="")
                    else: dots.create_oval(x-3,4,x+3,10, fill="", outline=FAINT, width=1)
                # 버튼 상태
                btn_prev.pack_forget()
                if i>0: btn_prev.pack(side="left")
                if i==n-1:
                    btn_next.config(text="\uc2dc\uc791\ud558\uae30", command=_close_ob)
                    btn_skip.pack_forget()
                else:
                    btn_next.config(text="\ub2e4\uc74c \u2192", command=_go_next)
                    btn_skip.pack_forget(); btn_skip.pack(side="left",padx=6)
            def _go_next():
                if state["i"]<len(SLIDES)-1: state["i"]+=1; _render()
            def _go_prev():
                if state["i"]>0: state["i"]-=1; _render()
            btn_prev.config(command=_go_prev)
            btn_skip.config(command=_close_ob)
            ob.protocol("WM_DELETE_WINDOW", _close_ob)
            # 좌우 화살표 키로도 넘기기
            try:
                ob.bind("<Right>", lambda e:_go_next()); ob.bind("<Left>", lambda e:_go_prev())
                ob.bind("<Return>", lambda e:(_close_ob() if state["i"]==len(SLIDES)-1 else _go_next()))
                ob.bind("<Escape>", lambda e:_close_ob())
            except Exception: pass
            _render()
        except Exception as _e:
            log("onboarding skipped: %s" % _e)
    if not cfg.get("onboarded"):
        try: root.after(400, _show_onboarding)
        except Exception: pass

    try: root.mainloop()
    except Exception as ex: log(f"GUI closed: {ex}")


def _print_status():
    s = sb_cfg(); st = cloud_state()
    print("\n" + "=" * 50)
    print("  myPENTA status check")
    print("=" * 50)
    print(f"  Data folder  : {DATA_DIR}")
    print("-" * 50)
    print(f"  Supabase URL : {s.get('url') or '(none)'}")
    print(f"  anon_key     : {'set' if s.get('anon_key') else 'missing'}")
    print(f"  service_key  : {'set (legacy - no longer required)' if s.get('service_key') else 'not set (OK - uploads use signed route)'}")
    print(f"  bucket       : {s.get('bucket') or 'media'}")
    verdict = {"cloud": "\u2601 Cloud ON (uploads enabled)",
               "readonly": "\u26a0 Read-only (service_key needed)",
               "local": "\u25cf Local only"}[st]
    print(f"\n  → {verdict}")
    if s.get("url") and (s.get("service_key") or s.get("anon_key")):
        print("\n  Testing Supabase connection...")
        try:
            import requests
            r = requests.get(_sb_base() + "/rest/v1/matches?select=id&limit=1", headers=_sb_h(), timeout=12)
            if r.status_code < 300:
                print("  \u2713 Connected — read from 'matches' table OK")
                try:
                    r2 = requests.get(_sb_base() + "/rest/v1/matches?select=id",
                                      headers={**_sb_h(), "Prefer": "count=exact", "Range": "0-0"}, timeout=12)
                    cr = r2.headers.get("content-range", "")
                    if "/" in cr: print(f"    \u2601 Matches stored in the cloud: {cr.split('/')[-1]}")
                except Exception: pass
                if s.get("service_key"):
                    try:
                        rb = requests.get(_sb_base() + "/storage/v1/bucket/" + (_sb_bucket()),
                                          headers=_sb_h(write=True), timeout=12)
                        if rb.status_code < 300: print(f"  \u2713 Storage bucket '{_sb_bucket()}' reachable (uploads ready)")
                        else: print(f"  \u2717 Bucket access failed: HTTP {rb.status_code} — check bucket name/key")
                    except Exception as e: print(f"  \u2717 Bucket test error: {e}")
            else:
                print(f"  \u2717 Connection failed: HTTP {r.status_code} — {r.text[:140]}")
                print("    (Key may be wrong or the table may be missing. Make sure schema.sql has been run.)")
        except Exception as e:
            print(f"  \u2717 Connection test error: {e}")
    print("=" * 50)

def main():
    global FFMPEG, CFG
    cfg = load_or_make_config(); CFG = cfg
    try: _apply_autostart(cfg)
    except Exception: pass
    if "--status" in sys.argv or "--check" in sys.argv:
        _print_status()
        try: input("\nPress Enter to exit...")
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
    print("=" * 56); print(f"  myPENTA — League of Legends auto-recorder — mode: {mode}"); print("=" * 56)
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
                _safe_input("\nCan't record without ffmpeg. Press Enter to exit..."); return
    if mode in ("all", "server") and not use_gui:
        if not FFMPEG: FFMPEG = ensure_ffmpeg()
    url = (cfg.get("gallery_url") or "https://mypenta.netlify.app/").rstrip("/")
    try: start_login_bridge(url)
    except Exception as _e: log("Login bridge failed to start: %s" % _e)
    if mode == "all":
        log(f"Archive → {url}")
        # 시작 시 브라우저로 아카이브를 자동으로 열지 않음(번잡함). 아카이브는 GUI 버튼/트레이 메뉴로만 연다.
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
