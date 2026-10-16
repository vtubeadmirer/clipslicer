"""브라우저 확장 'ClipSlicer 연결' 과 이야기하는 아주 작은 로컬 HTTP 서버 (127.0.0.1 전용).

확장은 브라우저에서 실제로 재생 중인 m3u8 요청을 헤더(쿠키 · 인증 포함)째 보내거나,
페이지 주소를 그 사이트의 로그인 쿠키와 함께 보낸다. 내장 브라우저로 로그인할 수 없는 사이트
(구글 로그인 등)도 사용자가 평소 쓰는 브라우저의 로그인 그대로 받을 수 있다.

보안: 127.0.0.1 에만 열고, Origin 이 우리 확장(고정 ID)인 요청만 받는다. 일반 웹페이지는 Origin 을
속일 수 없으므로 다른 사이트가 이 서버에 녹화를 시키거나 정보를 넣을 수 없다.
"""
from __future__ import annotations

import json
import logging
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PySide6.QtCore import QObject, Signal

LOG = logging.getLogger("clipslicer")
PORT = 47851
EXTENSION_ID = "angekabojgplnckpfnbadhliiceinkel"   # browser_extension/manifest.json 의 key 에서 나온 고정 ID
ALLOWED_ORIGIN = f"chrome-extension://{EXTENSION_ID}"
MAX_BODY = 1 << 20
DROP_HEADERS = {"range", "if-none-match", "if-modified-since", "if-range", "accept-encoding", "content-length",
                "host", "connection", "transfer-encoding"}


class BridgeError(ValueError):
    pass


def clean_headers(headers) -> dict:
    """확장이 보낸 요청 헤더 → 그대로 다시 보낼 수 있는 것만 (줄바꿈 · 이상한 이름 · 전송 관련 헤더 제거)."""
    out: dict[str, str] = {}
    if not isinstance(headers, dict):
        return out
    for k, v in headers.items():
        if not isinstance(k, str) or not isinstance(v, str):
            continue
        k = k.strip()
        if not k or k.lower() in DROP_HEADERS or k.startswith(":") or any(c in k for c in " \r\n:"):
            continue
        if "\r" in v or "\n" in v or len(v) > 16384:
            continue
        out[k] = v
    return out


def parse_request(body: bytes) -> dict:
    """POST /send 본문 검사. 반환: {kind, url, headers, cookies, page, title}."""
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as ex:
        raise BridgeError("JSON 이 아닙니다") from ex
    if not isinstance(data, dict):
        raise BridgeError("형식이 잘못되었습니다")
    kind = data.get("kind")
    if kind not in ("stream", "page"):
        raise BridgeError("kind 는 stream 또는 page")
    url = str(data.get("url") or "").strip()
    if urllib.parse.urlparse(url).scheme not in ("http", "https") or len(url) > 8192:
        raise BridgeError("http(s) 주소가 아닙니다")
    cookies = []
    raw_cookies = data.get("cookies") or []
    for c in raw_cookies if isinstance(raw_cookies, list) else []:
        if not isinstance(c, dict):
            continue
        fields = [c.get("domain"), c.get("name"), c.get("value"), c.get("path") or "/"]
        if not all(isinstance(f, str) for f in fields) or not fields[0] or not fields[1]:
            continue
        if any(ch in f for f in fields for ch in "\t\r\n"):   # cookies.txt 한 줄을 깨뜨리는 값
            continue
        exp = c.get("expiry")
        cookies.append({"domain": fields[0], "path": fields[3], "secure": bool(c.get("secure")),
                        "expiry": int(exp) if isinstance(exp, (int, float)) and exp > 0 else 0,
                        "name": fields[1], "value": fields[2]})
    page = str(data.get("page") or "")
    return {"kind": kind, "url": url, "headers": clean_headers(data.get("headers")), "cookies": cookies,
            "page": page if urllib.parse.urlparse(page).scheme in ("http", "https") else "",
            "title": str(data.get("title") or "")[:200]}


class _Handler(BaseHTTPRequestHandler):
    server_version = "ClipSlicerBridge"
    bridge: "Bridge" = None  # type: ignore[assignment]

    def log_message(self, fmt, *args):  # 기본은 stderr 로 찍는다 → 로그 파일로
        LOG.debug("bridge: " + fmt, *args)

    def _reply(self, code: int, obj: dict):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if self.headers.get("Origin") == ALLOWED_ORIGIN:
            self.send_header("Access-Control-Allow-Origin", ALLOWED_ORIGIN)
        self.end_headers()
        self.wfile.write(body)

    def _allowed(self) -> bool:
        if self.headers.get("Origin") != ALLOWED_ORIGIN:
            LOG.warning("bridge: 허용되지 않은 출처의 요청 거부: %s", self.headers.get("Origin"))
            self._reply(403, {"error": "forbidden"})
            return False
        return True

    def do_OPTIONS(self):
        if not self._allowed():
            return
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", ALLOWED_ORIGIN)
        self.send_header("Access-Control-Allow-Methods", "GET, POST")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _ping(self):
        from . import __version__
        self._reply(200, {"app": "ClipSlicer", "version": __version__})

    def do_GET(self):
        if not self._allowed():
            return
        if self.path.split("?")[0] == "/ping":
            self._ping()
        else:
            self._reply(404, {"error": "not found"})

    def do_POST(self):
        if not self._allowed():
            return
        if self.path.split("?")[0] == "/ping":   # 확장은 POST 로 확인한다 (GET 에는 Origin 이 안 붙음)
            self._ping()
            return
        if self.path.split("?")[0] != "/send":
            self._reply(404, {"error": "not found"})
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = -1
        if not 0 < n <= MAX_BODY:
            self._reply(413, {"error": "too large"})
            return
        try:
            req = parse_request(self.rfile.read(n))
        except BridgeError as ex:
            self._reply(400, {"error": str(ex)})
            return
        LOG.info("브라우저 확장에서 받음: %s %s (헤더 %d개, 쿠키 %d개)", req["kind"], req["url"][:120],
                 len(req["headers"]), len(req["cookies"]))
        self.bridge.received.emit(req)
        self._reply(200, {"ok": True})


class _ExclusiveServer(ThreadingHTTPServer):
    """같은 포트를 두 프로그램이 나눠 쓰지 않게 (윈도우의 SO_REUSEADDR 는 남의 포트도 빼앗는다)."""
    allow_reuse_address = False

    def server_bind(self):
        import socket
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class Bridge(QObject):
    """received(dict) 는 GUI 스레드에서 받는다 (Qt 가 스레드 사이 신호를 큐로 넘김)."""
    received = Signal(dict)

    def __init__(self, parent=None, port: int = PORT):
        super().__init__(parent)
        self.port = port
        self._server: ThreadingHTTPServer | None = None

    def start(self) -> bool:
        handler = type("Handler", (_Handler,), {"bridge": self})
        try:
            self._server = _ExclusiveServer(("127.0.0.1", self.port), handler)
        except OSError as ex:
            LOG.warning("브라우저 확장 연결 서버를 열지 못함 (포트 %d): %s", self.port, ex)
            self._server = None
            return False
        self._server.daemon_threads = True
        threading.Thread(target=self._server.serve_forever, name="bridge", daemon=True).start()
        LOG.info("브라우저 확장 연결 대기: 127.0.0.1:%d", self.port)
        return True

    @property
    def running(self) -> bool:
        return self._server is not None

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
