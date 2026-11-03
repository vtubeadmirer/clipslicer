"""m3u8 직접 받기 · 라이브 녹화: 순수 함수 + 로컬 HTTP 서버로 Referer/쿠키 검사 + 실제 녹화/중지."""
import http.server
import os
import subprocess
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import live_record as lr  # noqa: E402
from app.paths import find_tool  # noqa: E402

MASTER = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=640x360
low/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=5000000,RESOLUTION=1920x1080
high/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=2500000,RESOLUTION=1280x720
mid/index.m3u8
"""


def test_url_helpers():
    assert lr.is_m3u8("https://cdn.x/a/b/playlist.m3u8?token=1")
    assert not lr.is_m3u8("https://rplay.live/live/69f764ae5690cb201aae393f")
    assert lr.guess_referer("https://media.rplay.live/x.m3u8") == "https://rplay.live/"
    assert lr.guess_referer("https://example.com/x.m3u8") == ""
    assert lr.unsupported_page("https://rplay.live/live/abc")
    assert lr.unsupported_page("https://rplay.live/x/live.m3u8") == ""
    assert lr.unsupported_page("https://www.youtube.com/watch?v=x") == ""
    assert lr.origin_of("https://rplay.live/live/abc") == "https://rplay.live"
    h = lr.request_headers("https://rplay.live/", "a=1")
    assert h["Referer"] == "https://rplay.live/" and h["Origin"] == "https://rplay.live" and h["Cookie"] == "a=1"
    assert lr.ffmpeg_header_arg("https://rplay.live/", "a=1") == "Referer: https://rplay.live/\r\nOrigin: https://rplay.live\r\nCookie: a=1\r\n"
    assert lr.ffmpeg_header_arg() == ""
    assert lr.ytdlp_cookie_opts("") == {}
    assert lr.ytdlp_cookie_opts("Firefox") == {"cookiesfrombrowser": ("firefox",)}
    assert lr.ytdlp_cookie_opts("C:/x/cookies.txt") == {"cookiefile": "C:/x/cookies.txt"}


def test_vimeo_player_url():
    p = "https://player.vimeo.com/video/76979871"
    for u in ("https://vimeo.com/76979871", "https://www.vimeo.com/76979871/", "http://vimeo.com/76979871?share=copy",
              "https://vimeo.com/channels/staffpicks/76979871", "https://vimeo.com/groups/x/videos/76979871",
              "https://vimeo.com/album/5/video/76979871", "https://vimeo.com/showcase/5/video/76979871",
              "https://vimeo.com/manage/videos/76979871"):
        assert lr.vimeo_player_url(u) == p, u
    assert lr.vimeo_player_url("https://vimeo.com/76979871/ab12cd34ef") == p + "?h=ab12cd34ef"   # 일부 공개
    assert lr.vimeo_player_url("https://vimeo.com/76979871?h=ab12") == p + "?h=ab12"
    for u in (p, p + "?h=ab12", "https://vimeo.com/showcase/5", "https://vimeo.com/album/5", "https://vimeo.com/someuser",
              "https://vimeo.com/channels/staffpicks", "https://notvimeo.com/123", "https://www.youtube.com/watch?v=x", "vimeo.com/123", ""):
        assert lr.vimeo_player_url(u) == u, u


def _run_vimeo_worker(tmp_path, url, cookies, fake):
    """받기 부분만 fake 로 바꿔 worker 를 돌린다. (받은 파일, 오류)"""
    from PySide6.QtWidgets import QApplication
    from app.workers import DownloadWorker
    _app = QApplication.instance() or QApplication([])
    w = DownloadWorker(url, str(tmp_path), cookies=cookies)
    w._download_full = lambda _y, _h: fake(w.url)
    res = {}
    w.done.connect(lambda p, e: res.update(path=p, err=e))
    w.run()
    return res


def test_worker_uses_vimeo_player_url(tmp_path):
    import yt_dlp
    f = tmp_path / "v.mp4"
    f.write_bytes(b"x")
    seen = []

    def ok(u):
        seen.append(u)
        return str(f)

    # 쿠키 없음: 처음부터 플레이어 주소
    assert _run_vimeo_worker(tmp_path, "https://vimeo.com/123", "", ok)["path"] == str(f)
    assert seen == ["https://player.vimeo.com/video/123"]

    # 쿠키 있음: vimeo.com 먼저, 로그인 오류면 플레이어 주소로 다시
    seen.clear()

    def needs_login(u):
        seen.append(u)
        if "player." not in u:
            raise yt_dlp.utils.DownloadError("ERROR: The web client only works when logged-in.")
        return str(f)

    assert _run_vimeo_worker(tmp_path, "https://vimeo.com/123", "firefox", needs_login)["path"] == str(f)
    assert seen == ["https://vimeo.com/123", "https://player.vimeo.com/video/123"]

    # 다른 오류는 다시 시도하지 않는다
    seen.clear()

    def broken(u):
        seen.append(u)
        raise yt_dlp.utils.DownloadError("ERROR: HTTP Error 404")

    assert "404" in _run_vimeo_worker(tmp_path, "https://vimeo.com/123", "firefox", broken)["err"]
    assert len(seen) == 1

    # DRM 은 우회하지 않고 알아보기 쉽게 알린다
    def drm(_u):
        raise yt_dlp.utils.DownloadError("ERROR: This format is DRM protected; Try selecting another format")

    assert "DRM" in _run_vimeo_worker(tmp_path, "https://vimeo.com/123", "", drm)["err"]
    assert "Try selecting" not in _run_vimeo_worker(tmp_path, "https://vimeo.com/123", "", drm)["err"]


def test_dialog_rewrites_pasted_vimeo_url(tmp_path):
    from PySide6.QtWidgets import QApplication
    from app.dialogs import DownloadDialog
    _app = QApplication.instance() or QApplication([])
    d = DownloadDialog(None, str(tmp_path))
    d.ed_url.textEdited.emit("  https://vimeo.com/76979871?share=copy ")
    assert d.ed_url.text() == "https://player.vimeo.com/video/76979871"
    d.ed_url.setText("https://www.youtube.com/watch?v=x")
    d.ed_url.textEdited.emit(d.ed_url.text())
    assert d.ed_url.text() == "https://www.youtube.com/watch?v=x"
    # 로그인 쿠키를 고르면 로그인이 필요한 영상일 수 있으니 그대로 둔다
    d.cb_cookies.setCurrentIndex(d.cb_cookies.findData("firefox"))
    d.ed_url.setText("https://vimeo.com/76979871")
    d.ed_url.textEdited.emit(d.ed_url.text())
    assert d.ed_url.text() == "https://vimeo.com/76979871"


def test_write_cookies_txt_is_readable_by_ytdlp(tmp_path):
    p = lr.write_cookies_txt([{"domain": ".rplay.live", "path": "/", "secure": True, "expiry": 2147483647, "name": "tok", "value": "abc"},
                              {"domain": "media.rplay.live", "path": "/", "secure": False, "expiry": 0, "name": "s", "value": "1"}],
                             str(tmp_path / "c.txt"))
    hdr = lr.cookie_header(p, "https://media.rplay.live/live/master.m3u8")
    assert "tok=abc" in hdr and "s=1" in hdr
    assert lr.cookie_header(p, "https://other.example/x.m3u8") == ""


def test_playlist_helpers():
    base = "https://cdn.x/live/master.m3u8"
    assert lr.is_master(MASTER)
    assert lr.best_variant(MASTER, base) == "https://cdn.x/live/high/index.m3u8"
    assert lr.best_variant(MASTER, base, 720) == "https://cdn.x/live/mid/index.m3u8"
    assert lr.best_variant(MASTER, base, 240) == "https://cdn.x/live/low/index.m3u8"  # 제한보다 다 크면 가장 작은 것
    with pytest.raises(lr.LiveError):
        lr.best_variant("#EXTM3U\n", base)
    assert lr.is_live("#EXTM3U\n#EXTINF:2,\na.ts\n")
    assert not lr.is_live("#EXTM3U\n#EXTINF:2,\na.ts\n#EXT-X-ENDLIST\n")
    assert lr.drm_reason('#EXT-X-KEY:METHOD=AES-128,URI="k.key"') == ""
    assert lr.drm_reason("#EXT-X-KEY:METHOD=NONE") == ""
    assert lr.drm_reason('#EXT-X-KEY:METHOD=SAMPLE-AES,URI="skd://x",KEYFORMAT="com.apple.streamingkeydelivery"')
    assert lr.drm_reason('#EXT-X-SESSION-KEY:METHOD=SAMPLE-AES-CTR,KEYFORMAT="urn:uuid:edef8ba9-79d6-4ace-a3c8-27dcd51d21ed"')


# --------------------------------------------------------------------------- 로컬 HLS 서버
needs_ffmpeg = pytest.mark.skipif(not find_tool("ffmpeg"), reason="ffmpeg 없음")


class _Handler(http.server.SimpleHTTPRequestHandler):
    """Referer 와 Cookie 가 맞아야 응답하는 서버 (rplay 같은 CDN 흉내)."""
    root = ""
    require = True
    seen = []

    def translate_path(self, path):
        return os.path.join(self.root, path.split("?")[0].lstrip("/").replace("/", os.sep))

    def do_GET(self):
        _Handler.seen.append((self.path, self.headers.get("Referer"), self.headers.get("Cookie")))
        if self.require and (self.headers.get("Referer") != "https://rplay.live/" or "sess=ok" not in (self.headers.get("Cookie") or "")):
            self.send_error(403)
            return
        return super().do_GET()

    def log_message(self, *a):
        pass


@pytest.fixture(scope="module")
def hls_server(tmp_path_factory):
    d = tmp_path_factory.mktemp("hls")
    ff = find_tool("ffmpeg")
    if not ff:
        pytest.skip("ffmpeg 없음")
    vod = d / "vod"
    vod.mkdir()
    subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30:duration=12",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=12", "-c:v", "libx264", "-preset", "ultrafast",
                    "-g", "60", "-c:a", "aac", "-shortest", "-f", "hls", "-hls_time", "2", "-hls_playlist_type", "vod",
                    str(vod / "index.m3u8")], check=True, capture_output=True)
    # 라이브 흉내: 같은 세그먼트, ENDLIST 없음
    live = d / "live"
    live.mkdir()
    text = (vod / "index.m3u8").read_text(encoding="utf-8")
    for f in vod.glob("*.ts"):
        (live / f.name).write_bytes(f.read_bytes())
    live_text = "\n".join(l for l in text.splitlines() if "ENDLIST" not in l and "PLAYLIST-TYPE" not in l) + "\n"
    (live / "index.m3u8").write_text(live_text, encoding="utf-8")
    (d / "master.m3u8").write_text("#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=500000,RESOLUTION=320x180\nvod/index.m3u8\n",
                                   encoding="utf-8")
    cookies = d / "cookies.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n127.0.0.1\tFALSE\t/\tFALSE\t2147483647\tsess\tok\n", encoding="utf-8")
    _Handler.root = str(d)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield {"base": f"http://127.0.0.1:{srv.server_address[1]}", "dir": d, "cookies": str(cookies)}
    srv.shutdown()


@needs_ffmpeg
def test_resolve_needs_headers(hls_server):
    url = hls_server["base"] + "/master.m3u8"
    with pytest.raises(lr.LiveError):  # 헤더 없음 → 403
        lr.resolve(url, lr.request_headers())
    hdr = lr.request_headers("https://rplay.live/", lr.cookie_header(hls_server["cookies"], url))
    assert "sess=ok" in hdr["Cookie"]
    media, live = lr.resolve(url, hdr)
    assert media.endswith("/vod/index.m3u8") and live is False
    media, live = lr.resolve(hls_server["base"] + "/live/index.m3u8", hdr)
    assert live is True


@needs_ffmpeg
def test_describe_playlists(hls_server):
    """확장 팝업 표시용: 전체 화질(마스터) / 한 화질, 실시간 / 다시보기, 헤더 없으면 실패."""
    hdr = lr.request_headers("https://rplay.live/", "sess=ok")
    m = lr.describe(hls_server["base"] + "/master.m3u8", hdr)
    assert m["kind"] == "master" and m["heights"] == [180] and m["live"] is False and not m["error"], m
    assert m["variant_paths"] == [{"height": 180, "path": "/vod/index.m3u8"}]
    v = lr.describe(hls_server["base"] + "/live/index.m3u8", hdr)
    assert v["kind"] == "media" and v["live"] is True and not v["drm"], v
    vod = lr.describe(hls_server["base"] + "/vod/index.m3u8", hdr)
    assert vod["live"] is False and abs(vod["duration"] - 12) < 0.5      # 다시보기는 길이로 구별
    assert abs(m["duration"] - 12) < 0.5 and "duration" not in v          # 마스터도 길이, 라이브는 없음
    bad = lr.describe(hls_server["base"] + "/master.m3u8", lr.request_headers())
    assert bad["error"] and not bad["kind"]


def test_hls_extension_picky_only_for_hls():
    """치지직 라이브(.m4v fMP4 조각): ffmpeg 8 은 확장자 검사로 거부 → HLS 입력에만 -extension_picky 0."""
    cmd = lr.LiveRecorder("https://x/a.m3u8", "o.ts").command()
    i = cmd.index("-extension_picky")
    assert cmd[i + 1] == "0" and i < cmd.index("-i")
    from app.workers import DownloadWorker as W
    hls = {"is_live": True, "protocol": "m3u8_native", "url": "https://cdn/chunklist.m3u8",
           "http_headers": {"User-Agent": "UA", "Referer": "https://chzzk.naver.com/"}}
    p = {}
    W._allow_hls_extensions(p, hls)
    assert p == {"external_downloader_args": {"ffmpeg_i": ["-extension_picky", "0"]}}
    p = {}
    W._allow_hls_extensions(p, {"requested_formats": [{"protocol": "m3u8_native"}, {"protocol": "https"}]})
    assert p == {}                                  # HLS 가 아닌 입력이 섞이면 붙이지 않는다 (Option not found)

    class FakeYdl:
        class cookiejar:
            @staticmethod
            def get_cookie_header(url):
                return "NID=1"
    url, hdr = W._live_hls(FakeYdl, hls)
    assert url == "https://cdn/chunklist.m3u8" and hdr["Referer"] == "https://chzzk.naver.com/" and hdr["Cookie"] == "NID=1"
    assert W._live_hls(FakeYdl, dict(hls, is_live=False)) is None          # 다시보기는 yt-dlp 가 받음
    assert W._live_hls(FakeYdl, dict(hls, protocol="https")) is None
    assert W._live_hls(FakeYdl, {"is_live": True, "requested_formats": [hls, hls]}) is None


def test_variants_audio_only_and_order():
    text = ("#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=128000,CODECS=\"mp4a.40.2\"\naudio.m3u8\n"
            "#EXT-X-STREAM-INF:BANDWIDTH=900000,RESOLUTION=640x360,CODECS=\"avc1.4d401e,mp4a.40.2\"\n360.m3u8\n"
            "#EXT-X-STREAM-INF:BANDWIDTH=5000000,RESOLUTION=1920x1080,CODECS=\"avc1.640028,mp4a.40.2\"\n1080.m3u8\n")
    vs = lr.variants(text, "https://cdn/x/master.m3u8")
    assert [v["height"] for v in vs] == [1080, 360, 0]
    assert vs[0]["url"] == "https://cdn/x/1080.m3u8" and not vs[0]["audio_only"] and vs[2]["audio_only"]


@needs_ffmpeg
def test_live_recorder_stop_and_remux(hls_server, tmp_path):
    from app import ffmpeg_tools as ft
    ts = str(tmp_path / "rec.ts")
    rec = lr.LiveRecorder(hls_server["base"] + "/vod/index.m3u8", ts, "https://rplay.live/", "sess=ok",
                          input_args=["-re"])
    rec.start()
    threading.Timer(3.0, rec.stop).start()
    code = rec.poll_progress()
    assert os.path.getsize(ts) > 1024 and 1.0 < rec.out_time < 8.0, (code, rec.out_time, rec.stderr_tail)
    mp4 = str(tmp_path / "rec.mp4")
    assert lr.remux_to_mp4(ts, mp4)
    info = ft.probe(mp4)
    assert info["vcodec"] == "h264" and info["has_audio"] and 1.0 < info["duration"] < 8.0


_WORKER_SCRIPT = r"""
import json, os, sys
sys.path.insert(0, sys.argv[1])
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from app.workers import DownloadWorker
url, out_dir, cookies, stop_after = sys.argv[2], sys.argv[3], sys.argv[4], float(sys.argv[5])
app = QApplication([])
res = {}
w = DownloadWorker(url, out_dir, "best", None, None, cookies, "https://rplay.live/")
w.done.connect(lambda p, e: (res.update(path=p, err=e), app.quit()))
if stop_after >= 0:
    w.liveStarted.connect(lambda: (res.update(live=True), QTimer.singleShot(int(stop_after * 1000), w.stop_recording)))
w.start()
QTimer.singleShot(90000, app.quit)
app.exec()
w.wait(5000)
print("RESULT=" + json.dumps(res))
"""


def _run_worker(url, out_dir, cookies, stop_after=None):
    """다른 테스트의 Qt 상태와 섞이지 않게 별도 프로세스에서 DownloadWorker 를 돌린다."""
    import json
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = dict(os.environ, PYTHONIOENCODING="utf-8", QT_QPA_PLATFORM="offscreen")
    r = subprocess.run([sys.executable, "-c", _WORKER_SCRIPT, root, url, str(out_dir), cookies or "",
                        str(-1 if stop_after is None else stop_after)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=150, env=env)
    line = next((l for l in r.stdout.splitlines() if l.startswith("RESULT=")), None)
    assert line, (r.returncode, r.stdout[-800:], r.stderr[-1500:])
    return json.loads(line[len("RESULT="):])


@needs_ffmpeg
def test_worker_vod_m3u8_with_cookie_and_referer(hls_server, tmp_path):
    from app import ffmpeg_tools as ft
    res = _run_worker(hls_server["base"] + "/master.m3u8", tmp_path, hls_server["cookies"])
    assert res.get("path") and not res.get("err"), res
    assert abs(ft.probe(res["path"])["duration"] - 12) < 1.0


@needs_ffmpeg
def test_worker_live_m3u8_stop_saves_mp4(hls_server, tmp_path):
    from app import ffmpeg_tools as ft
    res = _run_worker(hls_server["base"] + "/live/index.m3u8", tmp_path, hls_server["cookies"], stop_after=4)
    assert res.get("live") and res.get("path", "").endswith(".mp4") and not res.get("err"), res
    assert ft.probe(res["path"])["duration"] > 1.0
    assert not [f for f in os.listdir(tmp_path) if f.endswith(".ts")]


def test_worker_rejects_rplay_page(tmp_path):
    res = _run_worker("https://rplay.live/live/69f764ae5690cb201aae393f", tmp_path, "")
    assert not res.get("path") and "확장" in res.get("err", "")
