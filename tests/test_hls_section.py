"""HLS 구간 다운로드 보조 함수 (네트워크 불필요)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import hls_section as hs  # noqa: E402

PL = """#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:4
#EXTINF:4.000,
a-000000.ts
#EXTINF:4.000,
a-000001.ts
#EXTINF:3.500,
a-000002.ts
#EXTINF:4.000,
https://other.cdn/abs-000003.ts?x=1
#EXT-X-ENDLIST
"""


def test_parse_playlist_and_tokens():
    segs = hs.parse_playlist(PL, "https://cdn/v/list.m3u8?_lsu_sa_=T", "_lsu_sa_=T")
    assert [round(s[0], 1) for s in segs] == [0.0, 4.0, 8.0, 11.5]
    assert segs[0][2] == "https://cdn/v/a-000000.ts?_lsu_sa_=T"
    assert segs[3][2] == "https://other.cdn/abs-000003.ts?x=1&_lsu_sa_=T"
    assert hs.parse_playlist("#EXTM3U\n", "u") == []


def test_select_segments():
    segs = hs.parse_playlist(PL, "https://cdn/v/list.m3u8")
    assert [s[2].rsplit("/", 1)[-1][:-3] for s in hs.select_segments(segs, 5.0, 9.0)] == ["a-000001", "a-000002"]
    assert len(hs.select_segments(segs, 0, 100)) == 4
    assert hs.select_segments(segs, 100, 200) == []
    assert len(hs.select_segments(segs, 4.0, 4.0 + 0.01)) == 1


def test_is_mpegts():
    assert hs.is_mpegts(b"\x47" + b"\x00" * 187 + b"\x47" + b"\x00" * 10)
    assert not hs.is_mpegts(b"\x00\x00\x00\x18ftypmp42")
