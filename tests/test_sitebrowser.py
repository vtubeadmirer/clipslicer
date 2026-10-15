"""내장 브라우저 녹화: 순수 함수 (QtWebEngine 창은 tools 스모크로 확인)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.sitebrowser import pick_stream, write_cookies_txt  # noqa: E402
from app import live_record as lr  # noqa: E402


def test_pick_stream():
    assert pick_stream([]) == ""
    assert pick_stream(["https://c/x/720p/chunk.m3u8", "https://c/x/master.m3u8"]) == "https://c/x/master.m3u8"
    assert pick_stream(["https://c/a.m3u8", "https://c/b.m3u8"]) == "https://c/a.m3u8"


def test_write_cookies_txt_is_readable_by_ytdlp(tmp_path):
    p = write_cookies_txt([{"domain": ".rplay.live", "path": "/", "secure": True, "expiry": 2147483647, "name": "tok", "value": "abc"},
                           {"domain": "media.rplay.live", "path": "/", "secure": False, "expiry": 0, "name": "s", "value": "1"}],
                          str(tmp_path / "c.txt"))
    hdr = lr.cookie_header(p, "https://media.rplay.live/live/master.m3u8")
    assert "tok=abc" in hdr and "s=1" in hdr
    assert lr.cookie_header(p, "https://other.example/x.m3u8") == ""
