"""유튜브 모듈 중 네트워크 없이 검증 가능한 부분."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import youtube as yt  # noqa: E402


def test_build_metadata_limits():
    m = yt.build_metadata("t" * 150, "d" * 6000, ["a", " ", "b"] + ["x"] * 60, "public", "20")
    assert len(m["snippet"]["title"]) == 100 and len(m["snippet"]["description"]) == 5000
    assert m["snippet"]["tags"][:2] == ["a", "b"] and len(m["snippet"]["tags"]) == 50
    assert m["status"]["privacyStatus"] == "public" and m["snippet"]["categoryId"] == "20"
    assert yt.build_metadata("", "", [], "weird")["status"]["privacyStatus"] == "private"
    assert yt.build_metadata("", "", [])["snippet"]["title"] == "ClipSlicer"
    sched = yt.build_metadata("a", "", [], "public", publish_at="2030-01-01T00:00:00Z")
    assert sched["status"]["privacyStatus"] == "private" and sched["status"]["publishAt"]
    assert "tags" not in yt.build_metadata("a", "", [])["snippet"]


def test_content_range_and_urls():
    assert yt.content_range(0, 8, 100) == "bytes 0-7/100"
    assert yt.content_range(96, 4, 100) == "bytes 96-99/100"
    assert yt.video_url("abc") == "https://youtu.be/abc"
    assert "studio.youtube.com" in yt.studio_url("abc")


def test_fill_template():
    assert yt.fill_template("{title} ({start}~{end}) {nope}", {"title": "T", "start": "1", "end": "2"}) == "T (1~2) {nope}"
    assert yt.fill_template("{", {}) == "{"


def test_api_error_mapping():
    body = json.dumps({"error": {"message": "x", "errors": [{"reason": "quotaExceeded"}]}}).encode()
    assert "할당량" in str(yt._api_error(403, body))
    assert "다시 연결" in str(yt._api_error(401, b"{}"))
    assert "YouTube API 오류 500" in str(yt._api_error(500, b"not json"))


def test_load_client_formats(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"installed": {"client_id": "id", "client_secret": "s"}}), encoding="utf-8")
    assert yt.load_client(str(p)) == {"client_id": "id", "client_secret": "s"}
    p.write_text(json.dumps({"web": {"client_id": "id2", "client_secret": "s2"}}), encoding="utf-8")
    assert yt.load_client(str(p))["client_id"] == "id2"
    p.write_text(json.dumps({"foo": 1}), encoding="utf-8")
    with pytest.raises(yt.YouTubeError):
        yt.load_client(str(p))


@pytest.mark.skipif(os.name != "nt", reason="DPAPI 는 Windows 전용")
def test_dpapi_roundtrip():
    data = json.dumps({"refresh_token": "r", "한글": "값"}).encode("utf-8")
    enc = yt.protect(data)
    assert enc != data and b"refresh_token" not in enc
    assert yt.unprotect(enc) == data


def test_check_upload_limits():
    e, w = yt.check_upload("a.mp4", 13 * 3600, 10, False)
    assert len(e) == 1 and "12시간" in e[0]
    e, w = yt.check_upload("a.mp4", 60, 300 * 1024 ** 3, False)
    assert "256 GB" in e[0]
    e, w = yt.check_upload("a.mp4", 240, 10, True)
    assert not e and any("쇼츠" in x for x in w)
    e, w = yt.check_upload("a.mp4", 20 * 60, 10, False)
    assert not e and any("15분" in x for x in w)
    e, w = yt.check_upload("a.mp4", 60, 0, False)
    assert any("비어" in x for x in e)
    assert yt.check_upload("a.mp4", 60, 10, False) == ([], [])


def test_quota_tracking():
    class S(dict):
        def value(self, k, d=None):
            return self.get(k, d)

        def setValue(self, k, v):
            self[k] = v

    s = S()
    assert yt.uploads_today(s) == 0
    assert yt.record_upload(s) == 1 and yt.record_upload(s) == 2
    assert yt.uploads_today(s) == 2
    s["yt_quota_day"] = "2000-01-01"
    assert yt.uploads_today(s) == 0
    assert len(yt.quota_day()) == 10
