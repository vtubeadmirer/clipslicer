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

def test_init_segment():
    text = '#EXTM3U\n#EXT-X-MAP:URI="1080p_0_0_0.m4s?type=hls&filetype=.m4s"\n#EXTINF:2.0,\n1080p_1.m4v\n'
    assert hs.init_segment(text, "https://cdn/v/1080p/list.m3u8") == "https://cdn/v/1080p/1080p_0_0_0.m4s?type=hls&filetype=.m4s"
    assert hs.init_segment(text, "https://cdn/v/list.m3u8", "tok=1").endswith("&tok=1")
    assert hs.init_segment(PL, "https://cdn/v/list.m3u8") == ""


def test_fmp4_section_like_chzzk(tmp_path):
    """치지직 다시보기처럼 fMP4 조각(.m4v) + 머리 조각(#EXT-X-MAP .m4s) 인 HLS 의 구간 받기.
    머리 조각을 빼먹으면 ffmpeg 가 'no tfhd was found' 로 못 읽었다 (0.9.16)."""
    import http.server
    import subprocess
    import threading
    import pytest
    from app.paths import find_tool
    from app import ffmpeg_tools as ft
    ff = find_tool("ffmpeg")
    if not ff:
        pytest.skip("ffmpeg 없음")
    src = tmp_path / "hls"
    src.mkdir()
    subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30:duration=20",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=20", "-c:v", "libx264", "-preset", "ultrafast",
                    "-g", "60", "-c:a", "aac", "-shortest", "-f", "hls", "-hls_time", "2", "-hls_playlist_type", "vod",
                    "-hls_segment_type", "fmp4", "-hls_fmp4_init_filename", "1080p_0_0_0.m4s",
                    "-hls_segment_filename", str(src / "1080p_%d.m4v"), str(src / "index.m3u8")],
                   check=True, capture_output=True, cwd=str(src))   # 머리 조각은 현재 폴더에 써진다
    assert (src / "1080p_0_0_0.m4s").exists()
    assert "#EXT-X-MAP" in (src / "index.m3u8").read_text(encoding="utf-8")

    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(src), **k)

        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        part = str(tmp_path / "part.ts")             # 앱처럼 .ts 이름으로 받아도 내용(fMP4)으로 읽혀야 한다
        s0, s1 = hs.download_section(f"http://127.0.0.1:{srv.server_address[1]}/index.m3u8", 6.0, 12.0, part)
    finally:
        srv.shutdown()
    assert s0 <= 6.0 and s1 >= 12.0
    out = str(tmp_path / "cut.mp4")
    ft.Cutter().cut_copy(part, 6.0 - s0, 12.0 - s0, out, lambda p: None)
    info = ft.probe(out)
    assert info["vcodec"] == "h264" and info["has_audio"] and abs(info["duration"] - 6.0) < 1.5, info
