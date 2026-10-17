"""ClipSlicer.exe --selftest <결과.json> : 빌드된 exe 가 실제 환경에서 핵심 기능을 쓸 수 있는지 스스로 점검.

GitHub Actions 가 릴리즈 전에 한글이 들어간 폴더에 exe 를 복사해 돌린다 (0.9.5~0.9.7 의 한글 경로 업데이트 오류 같은 것을
릴리즈 전에 잡기 위해). 창은 띄우지 않고 결과를 JSON 으로 남긴 뒤 종료 코드(0 = 모두 통과)로 끝낸다.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import traceback

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def _check(results: dict, name: str, fn):
    try:
        detail = fn()
        results[name] = {"ok": True, "detail": str(detail)[:300]}
    except Exception as ex:  # 점검은 하나가 실패해도 나머지를 계속한다
        results[name] = {"ok": False, "detail": f"{type(ex).__name__}: {ex}"[:500],
                         "trace": traceback.format_exc()[-1500:]}


def _tool_version(name: str) -> str:
    from .paths import find_tool
    exe = find_tool(name)
    if not exe:
        raise FileNotFoundError(name)
    out = subprocess.run([exe, "-version"], capture_output=True, timeout=30, creationflags=CREATE_NO_WINDOW)
    if out.returncode != 0:
        raise RuntimeError(f"{name} exit {out.returncode}")
    return out.stdout.decode("utf-8", "replace").splitlines()[0]


def _mpv() -> str:
    from .paths import prepare_libmpv
    d = prepare_libmpv()
    if not d:
        raise FileNotFoundError("libmpv-2.dll")
    import mpv  # noqa: F401  (libmpv-2.dll 로드)
    return d


def _webengine() -> str:
    from PySide6.QtWebEngineCore import QWebEngineProfile  # noqa: F401
    from .paths import base_dir
    exe = os.path.join(getattr(sys, "_MEIPASS", base_dir()), "PySide6", "QtWebEngineProcess.exe")
    if getattr(sys, "frozen", False) and not os.path.isfile(exe):
        raise FileNotFoundError(exe)
    return "QtWebEngine ok"


def _bridge() -> str:
    import socket
    import urllib.request
    from .bridge import Bridge, ALLOWED_ORIGIN
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    b = Bridge(port=port)
    if not b.start():
        raise RuntimeError("bridge start failed")
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/ping", data=b"", method="POST", headers={"Origin": ALLOWED_ORIGIN})
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())["version"]
    finally:
        b.stop()


def _updater() -> str:
    from . import updater
    others = updater.other_instances()   # 한글 경로 + 콘솔 없는 PowerShell 출력 디코딩 (0.9.8 에서 고친 오류)
    lock = updater.update_in_progress()
    return f"others={others} lock={lock}"


def _settings() -> str:
    from .paths import settings_file
    p = settings_file()   # 프로그램 폴더에 쓸 수 있으면 settings.ini (포터블), 아니면 레지스트리
    return p or "registry"


def _extension() -> str:
    from .paths import base_dir
    m = os.path.join(base_dir(), "browser_extension", "manifest.json")
    if getattr(sys, "frozen", False) and not os.path.isfile(m):
        raise FileNotFoundError(m)
    return "browser_extension ok"


def run(out_path: str) -> int:
    from . import __version__
    from .paths import base_dir
    results: dict = {}
    _check(results, "ffmpeg", lambda: _tool_version("ffmpeg"))
    _check(results, "ffprobe", lambda: _tool_version("ffprobe"))
    _check(results, "libmpv", _mpv)
    _check(results, "webengine", _webengine)
    _check(results, "bridge", _bridge)
    _check(results, "updater", _updater)
    _check(results, "settings", _settings)
    _check(results, "extension", _extension)
    ok = all(r["ok"] for r in results.values())
    report = {"version": __version__, "frozen": bool(getattr(sys, "frozen", False)), "dir": base_dir(),
              "ok": ok, "checks": results}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return 0 if ok else 1
