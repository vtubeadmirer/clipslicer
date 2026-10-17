"""브라우저 확장 연결: 요청 검사 · 로컬 서버(Origin 확인) · 브라우저 헤더 그대로 녹화/받기 (인증 헤더가 필요한 HLS)."""
import http.server
import json
import os
import socket
import subprocess
import sys
import threading
import urllib.error
import urllib.request

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import bridge  # noqa: E402
from app import live_record as lr  # noqa: E402
from app.paths import find_tool  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
needs_ffmpeg = pytest.mark.skipif(not find_tool("ffmpeg"), reason="ffmpeg 없음")


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# --------------------------------------------------------------------------- 순수 함수
def test_extension_id_matches_manifest_key():
    import base64
    import hashlib
    m = json.load(open(os.path.join(ROOT, "browser_extension", "manifest.json"), encoding="utf-8"))
    der = base64.b64decode(m["key"])
    eid = "".join(chr(ord("a") + int(c, 16)) for c in hashlib.sha256(der).hexdigest()[:32])
    assert eid == bridge.EXTENSION_ID
    js = open(os.path.join(ROOT, "browser_extension", "popup.js"), encoding="utf-8").read()
    assert f"127.0.0.1:{bridge.PORT}" in js


def test_clean_headers():
    h = bridge.clean_headers({"Authorization": "Bearer x", "Cookie": "a=1", "Range": "bytes=0-", "Host": "h",
                              "Accept-Encoding": "br", "X-Bad": "a\r\nInjected: 1", "Bad Name": "v", ":path": "/",
                              "User-Agent": "UA", "n": 3})
    assert h == {"Authorization": "Bearer x", "Cookie": "a=1", "User-Agent": "UA"}
    assert bridge.clean_headers("nope") == {}


def test_parse_request():
    ok = bridge.parse_request(json.dumps({
        "kind": "page", "url": "https://example.com/v/1", "title": "t",
        "cookies": [{"domain": ".example.com", "path": "/", "secure": True, "expiry": 2147483647, "name": "s", "value": "1"},
                    {"domain": ".example.com", "name": "bad", "value": "a\tb"},
                    {"domain": "", "name": "x", "value": "1"}, "junk"]}).encode())
    assert ok["kind"] == "page" and [c["name"] for c in ok["cookies"]] == ["s"] and ok["headers"] == {}
    for bad in (b"not json", b"[]", json.dumps({"kind": "x", "url": "https://a"}).encode(),
                json.dumps({"kind": "stream", "url": "file:///C:/x"}).encode(),
                json.dumps({"kind": "stream", "url": "javascript:alert(1)"}).encode()):
        with pytest.raises(bridge.BridgeError):
            bridge.parse_request(bad)


def test_browser_headers_for_ffmpeg():
    h = lr.browser_headers({"Authorization": "Bearer t"})
    assert h["User-Agent"] == lr.UA
    ua, hdr = lr.split_user_agent({"User-Agent": "MyUA", "Authorization": "Bearer t", "Cookie": "a=1"})
    assert ua == "MyUA" and hdr == "Authorization: Bearer t\r\nCookie: a=1\r\n"
    cmd = lr.LiveRecorder("https://x/a.m3u8", "o.ts", headers={"User-Agent": "MyUA", "Authorization": "Bearer t"}).command()
    assert cmd[cmd.index("-user_agent") + 1] == "MyUA"
    assert cmd[cmd.index("-headers") + 1] == "Authorization: Bearer t\r\n"


# --------------------------------------------------------------------------- 로컬 서버
@pytest.fixture()
def running_bridge():
    from PySide6.QtCore import QCoreApplication
    QCoreApplication.instance() or QCoreApplication([])
    b = bridge.Bridge(port=_free_port())
    got = []
    b.received.connect(lambda d: got.append(d))  # GUI 스레드로 큐잉된다 → _pump 로 처리
    assert b.start()
    yield b, got
    b.stop()


def _pump(until=None, timeout=3.0):
    import time
    from PySide6.QtCore import QCoreApplication
    t0 = time.time()
    while time.time() - t0 < timeout:
        QCoreApplication.processEvents()
        if until and until():
            return
        time.sleep(0.02)


def _call(port, path, origin, body=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=body, method="POST" if body else "GET",
                                 headers={"Content-Type": "application/json", **({"Origin": origin} if origin else {})})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read()), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}"), dict(e.headers)


def test_bridge_server_checks_origin(running_bridge):
    b, got = running_bridge
    body = json.dumps({"kind": "stream", "url": "https://cdn/x.m3u8", "headers": {"Authorization": "Bearer t"},
                       "page": "https://site/live/1", "title": "방송"}).encode()
    for origin in (None, "https://evil.example", "chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"):
        assert _call(b.port, "/ping", origin)[0] == 403
        assert _call(b.port, "/send", origin, body)[0] == 403
    assert not got
    code, j, h = _call(b.port, "/ping", bridge.ALLOWED_ORIGIN)
    assert code == 200 and j["app"] == "ClipSlicer" and h.get("Access-Control-Allow-Origin") == bridge.ALLOWED_ORIGIN
    _pump()
    assert not got
    code, j, _ = _call(b.port, "/send", bridge.ALLOWED_ORIGIN, body)
    assert code == 200 and j == {"ok": True}
    _pump(lambda: got)
    assert len(got) == 1 and got[0]["headers"] == {"Authorization": "Bearer t"} and got[0]["page"] == "https://site/live/1"
    assert _call(b.port, "/send", bridge.ALLOWED_ORIGIN, b"{bad")[0] == 400
    assert _call(b.port, "/nope", bridge.ALLOWED_ORIGIN)[0] == 404


def test_clip_request(running_bridge):
    """확장 단축키(Alt+Shift+C) → /clip → clipRequested(page). 확장이 아니면 거부, 이상한 주소는 비움."""
    b, _ = running_bridge
    got = []
    b.clipRequested.connect(lambda d: got.append(d))
    assert _call(b.port, "/clip", "https://evil.example", b'{"page": "https://x"}')[0] == 403
    assert _call(b.port, "/clip", bridge.ALLOWED_ORIGIN, json.dumps({"page": "https://chzzk.naver.com/live/abc"}).encode())[0] == 200
    assert _call(b.port, "/clip", bridge.ALLOWED_ORIGIN, json.dumps({"page": "javascript:alert(1)"}).encode())[0] == 200
    _pump(lambda: len(got) >= 2)
    assert got == [{"page": "https://chzzk.naver.com/live/abc"}, {"page": ""}]


def test_bridge_port_in_use_is_reported():
    from PySide6.QtCore import QCoreApplication
    QCoreApplication.instance() or QCoreApplication([])
    a, b = bridge.Bridge(port=_free_port()), None
    assert a.start()
    try:
        b = bridge.Bridge(port=a.port)
        assert not b.start() and not b.running
    finally:
        a.stop()


# --------------------------------------------------------------------------- 끝까지: 확장 → 서버 → 녹화
class _AuthHandler(http.server.SimpleHTTPRequestHandler):
    """Authorization 헤더와 쿠키가 둘 다 맞아야 응답 (localStorage 토큰을 헤더로 보내는 사이트 흉내)."""
    root = ""

    def translate_path(self, path):
        return os.path.join(self.root, path.split("?")[0].lstrip("/").replace("/", os.sep))

    def do_GET(self):
        if self.headers.get("Authorization") != "Bearer secret" or "sess=ok" not in (self.headers.get("Cookie") or ""):
            self.send_error(403)
            return
        return super().do_GET()

    def log_message(self, *a):
        pass


@pytest.fixture(scope="module")
def auth_hls(tmp_path_factory):
    ff = find_tool("ffmpeg")
    if not ff:
        pytest.skip("ffmpeg 없음")
    d = tmp_path_factory.mktemp("authhls")
    vod = d / "vod"
    vod.mkdir()
    subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30:duration=10",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=10", "-c:v", "libx264", "-preset", "ultrafast",
                    "-g", "60", "-c:a", "aac", "-shortest", "-f", "hls", "-hls_time", "2", "-hls_playlist_type", "vod",
                    str(vod / "index.m3u8")], check=True, capture_output=True)
    live = d / "live"
    live.mkdir()
    for f in vod.glob("*.ts"):
        (live / f.name).write_bytes(f.read_bytes())
    text = (vod / "index.m3u8").read_text(encoding="utf-8")
    (live / "index.m3u8").write_text("\n".join(l for l in text.splitlines() if "ENDLIST" not in l and "PLAYLIST-TYPE" not in l) + "\n",
                                     encoding="utf-8")
    _AuthHandler.root = str(d)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _AuthHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


_E2E_SCRIPT = r"""
import json, os, sys, urllib.request
sys.path.insert(0, sys.argv[1])
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from app import bridge
from app.workers import DownloadWorker
url, out_dir, port, stop_after = sys.argv[2], sys.argv[3], int(sys.argv[4]), float(sys.argv[5])
app = QApplication([])
res = {}
b = bridge.Bridge(port=port)
workers = []

def on_request(req):
    w = DownloadWorker(req["url"], out_dir, "best", None, None, headers=req["headers"], title=req["title"])
    workers.append(w)
    w.done.connect(lambda p, e: (res.update(path=p, err=e), app.quit()))
    if stop_after >= 0:
        w.liveStarted.connect(lambda: (res.update(live=True), QTimer.singleShot(int(stop_after * 1000), w.stop_recording)))
    w.start()

b.received.connect(on_request)
assert b.start()

def send():
    body = json.dumps({"kind": "stream", "url": url, "page": "https://site.example/live/1", "title": "테스트 방송",
                       "headers": {"Authorization": "Bearer secret", "Cookie": "sess=ok", "Range": "bytes=0-"}}).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{port}/send", data=body, method="POST",
                                 headers={"Content-Type": "application/json", "Origin": bridge.ALLOWED_ORIGIN})
    import threading
    threading.Thread(target=lambda: urllib.request.urlopen(req, timeout=10).read(), daemon=True).start()

QTimer.singleShot(100, send)
QTimer.singleShot(90000, app.quit)
app.exec()
for w in workers:
    w.wait(5000)
b.stop()
print("RESULT=" + json.dumps(res, ensure_ascii=True))
"""


def _run_e2e(url, out_dir, stop_after=None):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", QT_QPA_PLATFORM="offscreen")
    r = subprocess.run([sys.executable, "-c", _E2E_SCRIPT, ROOT, url, str(out_dir), str(_free_port()),
                        str(-1 if stop_after is None else stop_after)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=150, env=env)
    line = next((l for l in r.stdout.splitlines() if l.startswith("RESULT=")), None)
    assert line, (r.returncode, r.stdout[-800:], r.stderr[-1500:])
    return json.loads(line[len("RESULT="):])


@needs_ffmpeg
def test_probe_endpoint(running_bridge, auth_hls):
    """팝업의 '무엇인지' 확인: 확장이 잡은 헤더로 받아 보고 종류를 알려 준다. 확장이 아니면 거부."""
    b, got = running_bridge
    body = json.dumps({"url": auth_hls + "/live/index.m3u8",
                       "headers": {"Authorization": "Bearer secret", "Cookie": "sess=ok"}}).encode()
    code, j, _ = _call(b.port, "/probe", bridge.ALLOWED_ORIGIN, body)
    assert code == 200 and j["kind"] == "media" and j["live"] is True and not j["error"], j
    body = json.dumps({"url": auth_hls + "/vod/index.m3u8", "headers": {}}).encode()
    code, j, _ = _call(b.port, "/probe", bridge.ALLOWED_ORIGIN, body)
    assert code == 200 and j["error"] and not j["kind"]          # 헤더 없음 → 거부당함을 알려 줌
    assert _call(b.port, "/probe", "https://evil.example", body)[0] == 403
    _pump()
    assert not got                                                   # 확인은 받기를 시작하지 않는다


@needs_ffmpeg
def test_auth_server_rejects_without_headers(auth_hls):
    with pytest.raises(lr.LiveError):
        lr.resolve(auth_hls + "/vod/index.m3u8", lr.request_headers())


@needs_ffmpeg
def test_e2e_vod_with_browser_headers(auth_hls, tmp_path):
    from app import ffmpeg_tools as ft
    res = _run_e2e(auth_hls + "/vod/index.m3u8", tmp_path)
    assert res.get("path") and not res.get("err"), res
    assert os.path.basename(res["path"]).startswith("테스트 방송 ")
    assert abs(ft.probe(res["path"])["duration"] - 10) < 1.0


@needs_ffmpeg
def test_e2e_live_with_browser_headers(auth_hls, tmp_path):
    from app import ffmpeg_tools as ft
    res = _run_e2e(auth_hls + "/live/index.m3u8", tmp_path, stop_after=4)
    assert res.get("live") and res.get("path", "").endswith(".mp4") and not res.get("err"), res
    assert ft.probe(res["path"])["duration"] > 1.0
