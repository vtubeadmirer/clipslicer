"""HLS(m3u8) 주소 직접 받기 · 라이브 녹화.

yt-dlp 가 페이지 주소를 지원하지 않는 사이트(예: rplay.live)도 m3u8 주소만 알면 받을 수 있게 한다.
- 로그인 쿠키(브라우저 또는 cookies.txt)와 Referer/Origin 헤더를 붙인다.
- 재생 목록에 #EXT-X-ENDLIST 가 없으면 라이브로 보고 ffmpeg 로 녹화한다. '녹화 중지' 를 누르면
  ffmpeg 에 q 를 보내 그때까지 받은 분량을 정상 종료시키고 mp4 로 정리한다.
- DRM(SAMPLE-AES, Widevine/FairPlay/PlayReady 키)이 걸린 스트림은 받지 않는다.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from typing import Callable

from .ffmpeg_tools import find_tool, CREATE_NO_WINDOW
from .i18n import tr

LOG = logging.getLogger("clipslicer")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"
BROWSERS = ("firefox", "edge", "chrome", "whale", "brave", "opera", "vivaldi", "chromium")

# 페이지 주소만으로는 받을 수 없는 사이트 → 기본 Referer
REFERER_HINTS = {"rplay": "https://rplay.live/"}
# ffmpeg 8 의 HLS 입력은 조각 확장자가 형식과 맞는지 엄격히 본다 → 치지직 라이브(fMP4 조각이 .m4v)가
# 'Invalid data' 로 열리지 않는다. HLS 입력에만 붙일 것 (다른 입력에 주면 'Option not found' 로 실패).
HLS_INPUT_ARGS = ["-extension_picky", "0"]


class LiveError(Exception):
    pass


# --------------------------------------------------------------------------- 주소 · 헤더
def is_m3u8(url: str) -> bool:
    path = urllib.parse.urlparse(url).path.lower()
    return path.endswith(".m3u8") or ".m3u8" in url.lower().split("?")[0]


def guess_referer(url: str) -> str:
    host = urllib.parse.urlparse(url).netloc.lower()
    for key, ref in REFERER_HINTS.items():
        if key in host or key in url.lower():
            return ref
    return ""


def unsupported_page(url: str) -> str:
    """페이지 주소로는 못 받는 사이트면 안내 문구, 아니면 ''."""
    host = urllib.parse.urlparse(url).netloc.lower()
    if "rplay.live" in host and not is_m3u8(url):
        return tr("rplay 는 페이지 주소로는 받을 수 없습니다. 크롬에서 방송을 재생한 뒤 'ClipSlicer 연결' 확장 목록에서 "
                  "'녹화/받기' 를 누르세요 (성인 · 멤버십 방송은 로그인 · 인증 후 영상이 재생돼야 목록에 뜹니다).")
    return ""


def origin_of(referer: str) -> str:
    p = urllib.parse.urlparse(referer)
    return f"{p.scheme}://{p.netloc}" if p.scheme and p.netloc else ""


def request_headers(referer: str = "", cookie: str = "") -> dict:
    h = {"User-Agent": UA}
    if referer:
        h["Referer"] = referer
        o = origin_of(referer)
        if o:
            h["Origin"] = o
    if cookie:
        h["Cookie"] = cookie
    return h


def ffmpeg_header_arg(referer: str = "", cookie: str = "") -> str:
    """ffmpeg -headers 값 (각 줄 CRLF 로 끝남). User-Agent 는 -user_agent 로 따로 준다."""
    h = request_headers(referer, cookie)
    h.pop("User-Agent", None)
    return "".join(f"{k}: {v}\r\n" for k, v in h.items())


def browser_headers(headers: dict) -> dict:
    """브라우저 확장이 넘긴 실제 요청 헤더 + 빠진 User-Agent 보충."""
    h = dict(headers or {})
    if not any(k.lower() == "user-agent" for k in h):
        h["User-Agent"] = UA
    return h


def split_user_agent(headers: dict) -> tuple[str, str]:
    """(User-Agent, ffmpeg -headers 문자열). ffmpeg 는 UA 를 -user_agent 로 따로 받는다."""
    ua = UA
    lines = []
    for k, v in headers.items():
        if k.lower() == "user-agent":
            ua = v
        else:
            lines.append(f"{k}: {v}\r\n")
    return ua, "".join(lines)


def write_cookies_txt(cookies: list[dict], path: str) -> str:
    """[{domain, path, secure, expiry, name, value}] → Netscape cookies.txt (yt-dlp/live_record 용)."""
    lines = ["# Netscape HTTP Cookie File", "# ClipSlicer 가 저장 (로그인 정보가 들어 있으니 공유 금지)"]
    for c in cookies:
        dom = c["domain"]
        lines.append("\t".join([dom, "TRUE" if dom.startswith(".") else "FALSE", c.get("path") or "/",
                                "TRUE" if c.get("secure") else "FALSE", str(int(c.get("expiry") or 0)),
                                c["name"], c["value"]]))
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    return path


def ytdlp_cookie_opts(cookies: str) -> dict:
    """'' | 브라우저 이름 | cookies.txt 경로 → yt-dlp 옵션."""
    c = (cookies or "").strip()
    if not c:
        return {}
    if c.lower() in BROWSERS:
        return {"cookiesfrombrowser": (c.lower(),)}
    return {"cookiefile": c}


def cookie_header(cookies: str, url: str) -> str:
    """선택한 쿠키 저장소에서 url 에 보낼 Cookie 헤더 값을 만든다."""
    opts = ytdlp_cookie_opts(cookies)
    if not opts:
        return ""
    import yt_dlp
    try:
        with yt_dlp.YoutubeDL(dict(opts, quiet=True, no_warnings=True)) as ydl:
            return ydl.cookiejar.get_cookie_header(url) or ""
    except Exception as ex:
        raise LiveError(tr("브라우저 쿠키를 읽지 못했습니다: {0}\n"
                           "크롬·엣지·웨일은 최신 버전의 쿠키 암호화 때문에 실패할 수 있습니다. "
                           "Firefox 로 로그인하거나 cookies.txt 파일을 쓰세요.").format(str(ex)[:200])) from ex


# --------------------------------------------------------------------------- 재생 목록
def fetch_text(url: str, headers: dict, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise LiveError(tr("접근이 거부되었습니다 (HTTP {0}). 로그인 쿠키나 참조 페이지(Referer)를 확인하세요. "
                               "m3u8 주소에 붙은 토큰이 만료됐을 수도 있습니다.").format(e.code)) from e
        raise LiveError(tr("재생 목록을 받지 못했습니다 (HTTP {0}).").format(e.code)) from e
    except OSError as e:
        raise LiveError(tr("재생 목록을 받지 못했습니다: {0}").format(e)) from e


def is_master(text: str) -> bool:
    return "#EXT-X-STREAM-INF" in text


def best_variant(master_text: str, base_url: str, max_height: int = 0) -> str:
    """마스터 재생 목록에서 가장 높은 대역(높이 제한 안)의 변형 주소."""
    best = None  # (height_ok, bandwidth, url)
    lines = master_text.splitlines()
    for i, line in enumerate(lines):
        if not line.startswith("#EXT-X-STREAM-INF"):
            continue
        bw = int((re.search(r"BANDWIDTH=(\d+)", line) or [0, 0])[1] or 0)
        m = re.search(r"RESOLUTION=\d+x(\d+)", line)
        h = int(m.group(1)) if m else 0
        uri = next((l.strip() for l in lines[i + 1:] if l.strip() and not l.startswith("#")), "")
        if not uri:
            continue
        ok = 1 if (not max_height or not h or h <= max_height) else 0
        cand = (ok, bw if ok else -h, urllib.parse.urljoin(base_url, uri))
        if best is None or cand[:2] > best[:2]:
            best = cand
    if best is None:
        raise LiveError(tr("재생 목록에 변형이 없습니다"))
    return best[2]


def variants(master_text: str, base_url: str) -> list[dict]:
    """마스터 재생 목록의 변형들: [{height, bandwidth, url, audio_only}] (높은 화질 순)."""
    out = []
    lines = master_text.splitlines()
    for i, line in enumerate(lines):
        if not line.startswith("#EXT-X-STREAM-INF"):
            continue
        uri = next((l.strip() for l in lines[i + 1:] if l.strip() and not l.startswith("#")), "")
        if not uri:
            continue
        bw = int((re.search(r"BANDWIDTH=(\d+)", line) or [0, 0])[1] or 0)
        m = re.search(r"RESOLUTION=\d+x(\d+)", line)
        codecs = (re.search(r'CODECS="([^"]*)"', line) or [0, ""])[1]
        out.append({"height": int(m.group(1)) if m else 0, "bandwidth": bw, "url": urllib.parse.urljoin(base_url, uri),
                    "audio_only": not m and bool(codecs) and not re.search(r"avc|hvc|hev|vp0?9|av01", codecs, re.I)})
    out.sort(key=lambda v: (v["height"], v["bandwidth"]), reverse=True)
    return out


def describe(url: str, headers: dict, timeout: int = 8) -> dict:
    """확장 팝업에 보여 줄 재생 목록 정보 (브라우저 헤더 그대로 받아 본다).

    {kind: 'master'|'media', live: bool|None, heights: [1080, 720…], audio_only: bool, drm: str, error: str}
    master = 여러 화질이 든 대표 목록 (ClipSlicer 가 가장 좋은 화질을 고름), media = 한 화질의 실제 목록.
    """
    info = {"kind": "", "live": None, "heights": [], "audio_only": False, "drm": "", "error": ""}
    try:
        text = fetch_text(url, headers, timeout)
        if not text.lstrip().startswith("#EXTM3U"):
            info["error"] = tr("재생 목록이 아님")
            return info
        info["drm"] = drm_reason(text)
        if is_master(text):
            vs = variants(text, url)
            info["kind"] = "master"
            info["heights"] = sorted({v["height"] for v in vs if v["height"]}, reverse=True)
            info["audio_only"] = bool(vs) and all(v["audio_only"] for v in vs)
            # 같은 탭의 '한 화질' 목록이 몇 p 인지 팝업이 맞춰 볼 수 있게 (주소의 경로만, 토큰 제외)
            info["variant_paths"] = [{"height": v["height"], "path": urllib.parse.urlparse(v["url"]).path} for v in vs]
            if vs:   # 라이브인지는 변형 하나를 받아 봐야 안다 (토큰이 없으면 마스터의 쿼리를 이어 붙임)
                v_url = vs[0]["url"]
                q = urllib.parse.urlparse(url).query
                if q and "?" not in v_url:
                    v_url += "?" + q
                sub = fetch_text(v_url, headers, timeout)
                info["live"] = is_live(sub)
                info["drm"] = info["drm"] or drm_reason(sub)
        else:
            info["kind"] = "media"
            info["live"] = is_live(text)
    except LiveError as ex:
        info["error"] = str(ex)[:200]
    return info


def is_live(media_text: str) -> bool:
    return "#EXT-X-ENDLIST" not in media_text and "#EXT-X-PLAYLIST-TYPE:VOD" not in media_text


def drm_reason(text: str) -> str:
    """DRM 이면 사유, 아니면 ''. AES-128(일반 HLS 암호화)은 로그인 쿠키로 키를 받는 정상 방식이라 허용."""
    for m in re.finditer(r"#EXT-X-(?:SESSION-)?KEY:([^\n]*)", text):
        attrs = m.group(1).upper()
        if "METHOD=NONE" in attrs:
            continue
        if "SAMPLE-AES" in attrs or "KEYFORMAT=" in attrs and "IDENTITY" not in attrs:
            return tr("이 방송은 DRM 으로 보호되어 있어 받을 수 없습니다.")
    return ""


def resolve(url: str, headers: dict, max_height: int = 0) -> tuple[str, bool]:
    """(미디어 재생 목록 주소, 라이브 여부). DRM 이면 LiveError."""
    text = fetch_text(url, headers)
    if not text.lstrip().startswith("#EXTM3U"):
        raise LiveError(tr("m3u8 재생 목록이 아닙니다. 주소를 다시 확인하세요."))
    reason = drm_reason(text)
    media_url = url
    if is_master(text):
        media_url = best_variant(text, url, max_height)
        # 변형 주소에 토큰이 없으면 마스터의 쿼리를 이어 붙인다 (서명 주소 CDN 대응)
        q = urllib.parse.urlparse(url).query
        if q and "?" not in media_url:
            media_url += "?" + q
        text = fetch_text(media_url, headers)
        reason = reason or drm_reason(text)
    if reason:
        raise LiveError(reason)
    return media_url, is_live(text)


# --------------------------------------------------------------------------- 녹화
class LiveRecorder:
    """ffmpeg 로 HLS 를 .ts 에 그대로 저장. stop() 은 q 를 보내 정상 종료시킨다."""

    def __init__(self, url: str, dst_ts: str, referer: str = "", cookie: str = "",
                 input_args: list[str] | None = None, headers: dict | None = None):
        self.url, self.dst_ts = url, dst_ts
        self.referer, self.cookie = referer, cookie
        self.headers = headers  # 브라우저에서 받은 요청 헤더 그대로 (있으면 referer/cookie 대신)
        self.input_args = input_args or []
        self.proc: subprocess.Popen | None = None
        self.out_time = 0.0
        self.size = 0
        self.stderr_tail: list[str] = []
        self._stopping = False

    def command(self) -> list[str]:
        cmd = [find_tool("ffmpeg"), "-hide_banner", "-nostats", "-loglevel", "warning", "-y"]
        if self.url.lower().startswith("http"):
            if self.headers:
                ua, hdr = split_user_agent(self.headers)
            else:
                ua, hdr = UA, ffmpeg_header_arg(self.referer, self.cookie)
            cmd += ["-user_agent", ua]
            if hdr:
                cmd += ["-headers", hdr]
            cmd += ["-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "10",
                    "-rw_timeout", "30000000"]
            cmd += HLS_INPUT_ARGS   # 입력은 항상 HLS 재생 목록
        cmd += self.input_args + ["-i", self.url, "-map", "0:v?", "-map", "0:a?", "-c", "copy",
                                  "-f", "mpegts", "-progress", "pipe:1", self.dst_ts]
        return cmd

    def start(self):
        self.proc = subprocess.Popen(self.command(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, creationflags=CREATE_NO_WINDOW)
        threading.Thread(target=self._read_err, daemon=True).start()

    def _read_err(self):
        assert self.proc and self.proc.stderr
        for raw in self.proc.stderr:
            line = raw.decode("utf-8", "replace").strip()
            if line:
                self.stderr_tail.append(line)
                del self.stderr_tail[:-8]

    def poll_progress(self, on_progress: Callable[[float, int], None] | None = None,
                      cancel: Callable[[], bool] | None = None) -> int:
        """ffmpeg 가 끝날 때까지 진행률을 읽는다. cancel() 이 참이 되면 stop(). 종료 코드 반환."""
        assert self.proc and self.proc.stdout
        for raw in self.proc.stdout:
            line = raw.decode("utf-8", "replace").strip()
            if line.startswith("out_time_us="):
                try:
                    self.out_time = max(self.out_time, int(line.split("=", 1)[1]) / 1e6)
                except ValueError:
                    pass
            elif line.startswith("total_size="):
                try:
                    self.size = int(line.split("=", 1)[1])
                except ValueError:
                    pass
            elif line.startswith("progress=") and on_progress:
                on_progress(self.out_time, self.size)
            if cancel and cancel() and not self._stopping:
                self.stop()
        return self.proc.wait()

    def stop(self, timeout: float = 15.0):
        """정상 종료 요청 (q). 응답이 없으면 강제 종료."""
        if not self.proc or self.proc.poll() is not None or self._stopping:
            return
        self._stopping = True
        try:
            self.proc.stdin.write(b"q")
            self.proc.stdin.flush()
        except OSError:
            pass

        def _kill_later():
            t0 = time.time()
            while self.proc.poll() is None and time.time() - t0 < timeout:
                time.sleep(0.2)
            if self.proc.poll() is None:
                self.proc.kill()
        threading.Thread(target=_kill_later, daemon=True).start()


def clip_recent(ts_path: str, end_t: float, seconds: float, dst_mp4: str) -> str:
    """녹화 중인(계속 자라는) .ts 에서 end_t 초까지의 마지막 seconds 초를 mp4 로 복사 (재인코딩 없음).

    실시간 클립('지난 30초'). 시작은 키프레임에 맞춰 1~2초 앞당겨질 수 있다. 성공하면 dst_mp4, 실패하면 LiveError.
    """
    end_t = max(0.0, end_t)
    start = max(0.0, end_t - seconds)
    if end_t - start < 1.0:
        raise LiveError(tr("아직 녹화된 분량이 부족합니다"))
    os.makedirs(os.path.dirname(dst_mp4) or ".", exist_ok=True)
    cmd = [find_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{start:.3f}", "-i", ts_path,
           "-t", f"{end_t - start:.3f}", "-map", "0:v?", "-map", "0:a?", "-c", "copy",
           "-avoid_negative_ts", "make_zero", "-movflags", "+faststart", dst_mp4]
    r = subprocess.run(cmd, capture_output=True, creationflags=CREATE_NO_WINDOW, stdin=subprocess.DEVNULL, timeout=120)
    if r.returncode != 0 or not os.path.isfile(dst_mp4) or os.path.getsize(dst_mp4) < 1024:
        lines = r.stderr.decode("utf-8", "replace").strip().splitlines()
        raise LiveError(tr("클립을 만들지 못했습니다: {0}").format(lines[-1] if lines else "?"))
    return dst_mp4


def remux_to_mp4(src_ts: str, dst_mp4: str) -> bool:
    cmd = [find_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-i", src_ts,
           "-map", "0:v?", "-map", "0:a?", "-c", "copy", "-movflags", "+faststart", dst_mp4]
    r = subprocess.run(cmd, capture_output=True, creationflags=CREATE_NO_WINDOW, stdin=subprocess.DEVNULL)
    ok = r.returncode == 0 and os.path.isfile(dst_mp4) and os.path.getsize(dst_mp4) > 0
    if not ok:
        LOG.warning("mp4 정리 실패: %s", r.stderr.decode("utf-8", "replace")[-400:])
    return ok
