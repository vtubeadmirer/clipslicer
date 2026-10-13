"""yt-dlp 치지직 우회 패치 단위 테스트 (네트워크 불필요)."""
import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import ytdlp_patches as yp  # noqa: E402

MPD = """<?xml version="1.0"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" xmlns:nvod="http://naver.com/nvod">
 <Period><AdaptationSet mimeType="video/mp4"><Representation id="a" bandwidth="1"/></AdaptationSet>
 <AdaptationSet mimeType="video/mp2t" nvod:m3u="https://cdn.example/x/master.m3u8?_lsu_sa_=abc&amp;k=1">
  <Representation id="b" bandwidth="2"/></AdaptationSet></Period>
</MPD>"""


def test_find_m3u_url():
    doc = ET.fromstring(MPD)
    assert yp.find_m3u_url(doc) == "https://cdn.example/x/master.m3u8?_lsu_sa_=abc&k=1"
    assert yp.find_m3u_url(ET.fromstring("<MPD/>")) is None
    assert yp.find_m3u_url(None) is None


def test_source_url_error_detection():
    inner = KeyError("sourceURL")
    try:
        try:
            raise inner
        except KeyError as e:
            raise RuntimeError("wrapped") from e
    except RuntimeError as outer:
        assert yp._is_source_url_error(outer)
    assert not yp._is_source_url_error(KeyError("other"))
    assert not yp._is_source_url_error(ValueError("x"))

    class WithCause(Exception):
        def __init__(self, cause):
            super().__init__("ie")
            self.cause = cause

    assert yp._is_source_url_error(WithCause(KeyError("sourceURL")))


def test_patch_appends_token_to_formats(monkeypatch):
    import yt_dlp.extractor.common as common

    yp._applied = False
    yp.apply()
    assert yp._applied

    class FakeIE(common.InfoExtractor):
        def __init__(self):
            pass

        def _extract_m3u8_formats_and_subtitles(self, url, video_id, ext, m3u8_id=None, fatal=True):
            assert url.startswith("https://cdn.example/x/master.m3u8?")
            return [{"format_id": "hls-1", "url": "https://cdn.example/x/v1.m3u8"},
                    {"format_id": "hls-2", "url": "https://cdn.example/x/v2.m3u8?a=1"}], {}

    def boom(self, *a, **k):
        raise KeyError("sourceURL")

    monkeypatch.setattr(common.InfoExtractor, "_parse_mpd_periods", boom)
    fmts, subs = FakeIE()._parse_mpd_formats_and_subtitles(ET.fromstring(MPD), "dash", "", "u")
    assert fmts[0]["url"] == "https://cdn.example/x/v1.m3u8?_lsu_sa_=abc&k=1"
    assert fmts[1]["url"] == "https://cdn.example/x/v2.m3u8?a=1&_lsu_sa_=abc&k=1"
    assert fmts[0]["extra_param_to_segment_url"] == "_lsu_sa_=abc&k=1"
