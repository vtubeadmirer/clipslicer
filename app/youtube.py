"""YouTube Data API v3 — OAuth 로그인, 이어 올리기(resumable) 업로드, 재생목록, 썸네일.

외부 라이브러리 없이 표준 라이브러리만 쓴다. 토큰은 Windows DPAPI 로 암호화해 프로그램 폴더에 저장한다.
준비물: Google Cloud 콘솔에서 만든 OAuth 클라이언트(데스크톱 앱)의 client_secret.json.
"""
from __future__ import annotations

import base64
import ctypes
import hashlib
import http.server
import json
import logging
import mimetypes
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from typing import Callable

from .paths import base_dir

LOG = logging.getLogger("clipslicer")

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API = "https://www.googleapis.com/youtube/v3"
UPLOAD_API = "https://www.googleapis.com/upload/youtube/v3"
SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube"
CHUNK = 8 * 1024 * 1024  # 8 MB (256 KB 배수여야 함)

CATEGORIES = [("20", "게임"), ("22", "인물/블로그"), ("24", "엔터테인먼트"), ("10", "음악"),
              ("17", "스포츠"), ("27", "교육"), ("28", "과학기술"), ("23", "코미디"), ("26", "노하우/스타일")]

CLIENT_FILE = "youtube_client_secret.json"
TOKEN_FILE = "youtube_token.bin"


class YouTubeError(Exception):
    pass


# --------------------------------------------------------------------------- 파일 위치
def config_dir() -> str:
    d = base_dir()
    try:
        probe = os.path.join(d, ".yt_write_test")
        with open(probe, "w"):
            pass
        os.remove(probe)
        return d
    except OSError:
        alt = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "ClipSlicer")
        os.makedirs(alt, exist_ok=True)
        return alt


def client_path() -> str:
    return os.path.join(config_dir(), CLIENT_FILE)


def token_path() -> str:
    return os.path.join(config_dir(), TOKEN_FILE)


# --------------------------------------------------------------------------- DPAPI
class _BLOB(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi(data: bytes, protect: bool) -> bytes:
    if os.name != "nt":
        return data
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    inp = _BLOB(len(data), ctypes.cast(ctypes.create_string_buffer(data, len(data)), ctypes.POINTER(ctypes.c_char)))
    out = _BLOB()
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    if protect:
        ok = fn(ctypes.byref(inp), "ClipSlicer", None, None, None, 0, ctypes.byref(out))
    else:
        ok = fn(ctypes.byref(inp), None, None, None, None, 0, ctypes.byref(out))
    if not ok:
        raise YouTubeError("토큰 암호화/복호화 실패 (DPAPI)")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)


def protect(data: bytes) -> bytes:
    return _dpapi(data, True)


def unprotect(data: bytes) -> bytes:
    return _dpapi(data, False)


# --------------------------------------------------------------------------- 클라이언트 / 토큰
def load_client(path: str | None = None) -> dict:
    p = path or client_path()
    if not os.path.isfile(p):
        raise YouTubeError("client_secret.json 이 없습니다. 설정 ▸ 유튜브 계정 연결에서 등록하세요.")
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    c = data.get("installed") or data.get("web") or data
    if not c.get("client_id") or not c.get("client_secret"):
        raise YouTubeError("client_secret.json 형식이 올바르지 않습니다 (client_id / client_secret 없음)")
    return {"client_id": c["client_id"], "client_secret": c["client_secret"]}


def install_client_file(src: str) -> str:
    load_client(src)  # 검증
    dst = client_path()
    with open(src, "rb") as f_in, open(dst, "wb") as f_out:
        f_out.write(f_in.read())
    return dst


def load_token() -> dict | None:
    p = token_path()
    if not os.path.isfile(p):
        return None
    try:
        with open(p, "rb") as f:
            return json.loads(unprotect(f.read()).decode("utf-8"))
    except Exception:
        LOG.warning("유튜브 토큰 읽기 실패", exc_info=True)
        return None


def save_token(tok: dict):
    with open(token_path(), "wb") as f:
        f.write(protect(json.dumps(tok).encode("utf-8")))


def clear_token():
    try:
        os.remove(token_path())
    except OSError:
        pass


def is_connected() -> bool:
    return load_token() is not None


# --------------------------------------------------------------------------- HTTP
def _request(method: str, url: str, data: bytes | None = None, headers: dict | None = None, timeout: int = 60):
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def _api_error(status: int, body: bytes) -> YouTubeError:
    reason = ""
    msg = ""
    try:
        j = json.loads(body.decode("utf-8", "replace"))
        err = j.get("error", {})
        msg = err.get("message", "") if isinstance(err, dict) else str(err)
        errs = err.get("errors") if isinstance(err, dict) else None
        if errs:
            reason = errs[0].get("reason", "")
    except Exception:
        msg = body[:200].decode("utf-8", "replace")
    friendly = {
        "quotaExceeded": "오늘의 YouTube API 할당량을 다 썼습니다 (하루 약 6개 업로드). 내일 다시 시도하세요.",
        "uploadLimitExceeded": "채널의 업로드 한도를 넘었습니다. 잠시 뒤 다시 시도하세요.",
        "youtubeSignupRequired": "이 구글 계정에는 유튜브 채널이 없습니다. 유튜브에서 채널을 먼저 만드세요.",
        "forbidden": "권한이 없습니다. 설정에서 계정 연결을 다시 하세요.",
        "invalidTitle": "제목이 비었거나 너무 깁니다 (100자 이내).",
        "invalidDescription": "설명이 너무 깁니다 (5000자 이내).",
        "invalidTags": "태그가 너무 많거나 깁니다 (전체 500자 이내).",
        "insufficientPermissions": "권한이 부족합니다. 설정에서 계정 연결을 다시 하세요.",
    }.get(reason)
    if status in (401,):
        friendly = "로그인이 만료되었습니다. 설정 ▸ 유튜브 계정 연결에서 다시 연결하세요."
    return YouTubeError(friendly or f"YouTube API 오류 {status}: {reason or msg}")


# --------------------------------------------------------------------------- OAuth
class _CodeHandler(http.server.BaseHTTPRequestHandler):
    result: dict = {}

    def do_GET(self):  # noqa: N802
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _CodeHandler.result = {k: v[0] for k, v in q.items()}
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        ok = "code" in q
        self.wfile.write(("<html><body style='font-family:sans-serif;text-align:center;padding:40px'>"
                          + ("<h2>ClipSlicer 연결 완료</h2><p>이 창을 닫고 프로그램으로 돌아가세요.</p>" if ok
                             else "<h2>연결이 취소되었습니다</h2>")
                          + "</body></html>").encode("utf-8"))

    def log_message(self, *args):
        pass


def authorize(open_browser: Callable[[str], None] | None = None, timeout: int = 300, cancel: Callable[[], bool] | None = None) -> dict:
    """브라우저로 Google 로그인 → 토큰 dict 저장 후 반환."""
    client = load_client()
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    server = http.server.HTTPServer(("127.0.0.1", 0), _CodeHandler)
    port = server.server_address[1]
    redirect = f"http://127.0.0.1:{port}/"
    _CodeHandler.result = {}
    params = {
        "client_id": client["client_id"], "redirect_uri": redirect, "response_type": "code",
        "scope": SCOPES, "access_type": "offline", "prompt": "consent", "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256",
    }
    url = AUTH_URL + "?" + urllib.parse.urlencode(params)
    th = threading.Thread(target=server.handle_request, daemon=True)
    th.start()
    (open_browser or webbrowser.open)(url)
    deadline = time.time() + timeout
    while th.is_alive() and time.time() < deadline:
        if cancel and cancel():
            break
        th.join(0.3)
    server.server_close()
    res = _CodeHandler.result
    if not res.get("code"):
        raise YouTubeError("로그인이 완료되지 않았습니다" + (f" ({res['error']})" if res.get("error") else ""))
    if res.get("state") != state:
        raise YouTubeError("로그인 응답이 올바르지 않습니다 (state 불일치)")
    data = urllib.parse.urlencode({
        "code": res["code"], "client_id": client["client_id"], "client_secret": client["client_secret"],
        "redirect_uri": redirect, "grant_type": "authorization_code", "code_verifier": verifier,
    }).encode()
    status, _h, body = _request("POST", TOKEN_URL, data, {"Content-Type": "application/x-www-form-urlencoded"})
    if status != 200:
        raise YouTubeError("토큰 발급 실패: " + body[:300].decode("utf-8", "replace"))
    tok = json.loads(body)
    if "refresh_token" not in tok:
        raise YouTubeError("refresh_token 이 없습니다. 구글 계정의 서드파티 액세스에서 ClipSlicer 를 제거한 뒤 다시 연결하세요.")
    tok["expires_at"] = time.time() + int(tok.get("expires_in", 3600)) - 60
    save_token(tok)
    return tok


def access_token() -> str:
    tok = load_token()
    if not tok:
        raise YouTubeError("유튜브 계정이 연결되어 있지 않습니다. 설정 ▸ 유튜브 계정 연결.")
    if time.time() < tok.get("expires_at", 0) and tok.get("access_token"):
        return tok["access_token"]
    client = load_client()
    data = urllib.parse.urlencode({
        "client_id": client["client_id"], "client_secret": client["client_secret"],
        "refresh_token": tok["refresh_token"], "grant_type": "refresh_token",
    }).encode()
    status, _h, body = _request("POST", TOKEN_URL, data, {"Content-Type": "application/x-www-form-urlencoded"})
    if status != 200:
        raise YouTubeError("로그인 갱신 실패. 설정 ▸ 유튜브 계정 연결에서 다시 연결하세요.")
    new = json.loads(body)
    tok["access_token"] = new["access_token"]
    tok["expires_at"] = time.time() + int(new.get("expires_in", 3600)) - 60
    save_token(tok)
    return tok["access_token"]


def disconnect():
    tok = load_token()
    if tok:
        try:
            _request("POST", REVOKE_URL + "?" + urllib.parse.urlencode({"token": tok.get("refresh_token") or tok.get("access_token")}),
                     b"", {"Content-Type": "application/x-www-form-urlencoded"}, timeout=15)
        except Exception:
            pass
    clear_token()


# --------------------------------------------------------------------------- API
def _get(path: str, params: dict) -> dict:
    url = f"{API}/{path}?" + urllib.parse.urlencode(params)
    status, _h, body = _request("GET", url, None, {"Authorization": "Bearer " + access_token()})
    if status != 200:
        raise _api_error(status, body)
    return json.loads(body)


def _post_json(url: str, obj: dict) -> dict:
    status, _h, body = _request("POST", url, json.dumps(obj).encode("utf-8"),
                                {"Authorization": "Bearer " + access_token(), "Content-Type": "application/json; charset=utf-8"})
    if status not in (200, 201):
        raise _api_error(status, body)
    return json.loads(body)


def my_channel() -> dict:
    j = _get("channels", {"part": "snippet", "mine": "true"})
    items = j.get("items") or []
    if not items:
        raise YouTubeError("이 구글 계정에는 유튜브 채널이 없습니다.")
    sn = items[0]["snippet"]
    return {"id": items[0]["id"], "title": sn.get("title", ""), "thumbnail": (sn.get("thumbnails") or {}).get("default", {}).get("url", "")}


def my_playlists() -> list[tuple[str, str]]:
    out = []
    token = None
    for _ in range(10):
        params = {"part": "snippet", "mine": "true", "maxResults": 50}
        if token:
            params["pageToken"] = token
        j = _get("playlists", params)
        out += [(it["id"], it["snippet"]["title"]) for it in j.get("items", [])]
        token = j.get("nextPageToken")
        if not token:
            break
    return out


def add_to_playlist(playlist_id: str, video_id: str):
    _post_json(f"{API}/playlistItems?part=snippet",
               {"snippet": {"playlistId": playlist_id, "resourceId": {"kind": "youtube#video", "videoId": video_id}}})


def set_thumbnail(video_id: str, image_path: str):
    ctype = mimetypes.guess_type(image_path)[0] or "image/png"
    with open(image_path, "rb") as f:
        data = f.read()
    url = f"{UPLOAD_API}/thumbnails/set?" + urllib.parse.urlencode({"videoId": video_id, "uploadType": "media"})
    status, _h, body = _request("POST", url, data, {"Authorization": "Bearer " + access_token(), "Content-Type": ctype})
    if status not in (200, 201):
        raise _api_error(status, body)


def build_metadata(title: str, description: str, tags: list[str], privacy: str = "private",
                   category: str = "22", made_for_kids: bool = False, publish_at: str | None = None) -> dict:
    title = (title or "").strip()[:100] or "ClipSlicer"
    snippet = {"title": title, "description": (description or "")[:5000], "categoryId": category}
    tags = [t.strip() for t in tags if t and t.strip()]
    if tags:
        snippet["tags"] = tags[:50]
    status = {"privacyStatus": privacy if privacy in ("private", "unlisted", "public") else "private",
              "selfDeclaredMadeForKids": bool(made_for_kids)}
    if publish_at:
        status["publishAt"] = publish_at
        status["privacyStatus"] = "private"
    return {"snippet": snippet, "status": status}


def content_range(offset: int, length: int, total: int) -> str:
    return f"bytes {offset}-{offset + length - 1}/{total}"


def upload_video(path: str, metadata: dict, on_progress: Callable[[float, str], None] | None = None,
                 cancel: Callable[[], bool] | None = None) -> str:
    """이어 올리기 업로드. 동영상 ID 를 반환."""
    total = os.path.getsize(path)
    ctype = mimetypes.guess_type(path)[0] or "video/*"
    url = f"{UPLOAD_API}/videos?" + urllib.parse.urlencode({"uploadType": "resumable", "part": "snippet,status"})
    status, headers, body = _request("POST", url, json.dumps(metadata).encode("utf-8"), {
        "Authorization": "Bearer " + access_token(), "Content-Type": "application/json; charset=utf-8",
        "X-Upload-Content-Length": str(total), "X-Upload-Content-Type": ctype})
    if status != 200:
        raise _api_error(status, body)
    session = headers.get("Location") or headers.get("location")
    if not session:
        raise YouTubeError("업로드 세션을 시작하지 못했습니다")
    offset = 0
    retries = 0
    with open(path, "rb") as f:
        while offset < total:
            if cancel and cancel():
                raise YouTubeError("취소됨")
            f.seek(offset)
            chunk = f.read(CHUNK)
            hdr = {"Authorization": "Bearer " + access_token(), "Content-Type": ctype,
                   "Content-Range": content_range(offset, len(chunk), total)}
            try:
                status, headers, body = _request("PUT", session, chunk, hdr, timeout=300)
            except (urllib.error.URLError, OSError, TimeoutError) as ex:
                retries += 1
                if retries > 5:
                    raise YouTubeError(f"네트워크 오류로 업로드 실패: {ex}")
                time.sleep(min(2 ** retries, 30))
                offset = _query_offset(session, total)
                continue
            if status == 308:
                rng = headers.get("Range") or headers.get("range")
                offset = int(rng.split("-")[-1]) + 1 if rng else offset + len(chunk)
                retries = 0
            elif status in (200, 201):
                vid = json.loads(body).get("id")
                if on_progress:
                    on_progress(1.0, "완료")
                return vid
            elif status in (500, 502, 503, 504):
                retries += 1
                if retries > 5:
                    raise _api_error(status, body)
                time.sleep(min(2 ** retries, 30))
                offset = _query_offset(session, total)
                continue
            else:
                raise _api_error(status, body)
            if on_progress:
                on_progress(offset / total, f"{offset / 1e6:.0f} / {total / 1e6:.0f} MB")
    raise YouTubeError("업로드가 끝났지만 응답이 없습니다")


def _query_offset(session: str, total: int) -> int:
    status, headers, _b = _request("PUT", session, b"", {"Authorization": "Bearer " + access_token(),
                                                        "Content-Range": f"bytes */{total}"}, timeout=60)
    if status == 308:
        rng = headers.get("Range") or headers.get("range")
        return int(rng.split("-")[-1]) + 1 if rng else 0
    return 0


def video_url(video_id: str) -> str:
    return f"https://youtu.be/{video_id}"


def studio_url(video_id: str) -> str:
    return f"https://studio.youtube.com/video/{video_id}/edit"


def fill_template(template: str, values: dict) -> str:
    class _D(dict):
        def __missing__(self, k):
            return "{" + k + "}"
    try:
        return template.format_map(_D(values))
    except (ValueError, IndexError):
        return template
