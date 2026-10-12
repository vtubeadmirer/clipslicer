"""0.4 기능 테스트: 클립 모드, 타임스탬프 파싱, 챕터 텍스트, 캐시, 세로 크롭, 장면 전환."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.segments import ClipProject, parse_timestamps  # noqa: E402
from app import cache  # noqa: E402
from app.paths import find_tool  # noqa: E402


def make(duration=100.0):
    p = ClipProject(path="C:/video/sample.mp4", duration=duration, fps=30.0)
    p.rebuild_segments()
    return p


def test_parse_timestamps():
    text = "0:00 인트로\n3:12 본편\n1:02:03.5 하이라이트\n12:34 다시 12:34\n숫자 2024 와 10:5 는 무시\n"
    assert parse_timestamps(text) == [0.0, 192.0, 754.0, 3723.5]
    assert parse_timestamps("") == []


def test_clip_mode_keeps_only_clips():
    p = make()
    assert p.apply_clip(10.0, 20.0)
    assert p.markers == [10.0, 20.0]
    assert [s.enabled for s in p.segments] == [False, True, False]
    assert p.apply_clip(50.0, 60.0)
    assert [s.enabled for s in p.segments] == [False, True, False, True, False]
    # 클립 안에 마커를 더 찍어도 그 조각들은 켜진 채 유지
    p.add_marker(15.0)
    p._apply_clip_enables()
    assert [s.enabled for s in p.segments] == [False, True, True, False, True, False]
    assert not p.apply_clip(70.0, 70.05)


def test_clip_undo_and_json(tmp_path):
    p = ClipProject(path=str(tmp_path / "v.mp4"), duration=100.0)
    p.rebuild_segments()
    p.push_undo()
    p.apply_clip(10.0, 20.0)
    p.crop_x = 0.25
    assert p.save()
    q = ClipProject(path=p.path, duration=100.0)
    q.rebuild_segments()
    assert q.load() and q.clips == [(10.0, 20.0)] and q.crop_x == 0.25
    assert [s.enabled for s in q.segments] == [False, True, False]
    assert p.undo() and p.clips == [] and p.markers == []
    assert p.redo() and p.clips == [(10.0, 20.0)]


def test_chapter_text():
    p = make(7200)
    p.add_marker(192.0)
    p.add_marker(3723.0)
    p.segments[1].name = "본편"
    p.segments[0].enabled = False
    assert p.chapter_text() == "03:12 본편\n1:02:03 구간 3"


def test_cache_roundtrip(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x" * 100)
    assert cache.load(str(video)) is None
    assert cache.save(str(video), [(0.0, b"\xff\xd8")], [0.1, 0.5], [0.0, 3.0])
    data = cache.load(str(video))
    assert data and data["keyframes"] == [0.0, 3.0] and data["thumbs"][0][1] == b"\xff\xd8"
    video.write_bytes(b"y" * 200)  # 파일이 바뀌면 캐시 무효
    assert cache.load(str(video)) is None
    cache.remove(str(video))
    assert not os.path.exists(str(video) + cache.SUFFIX)


# ---- ffmpeg 필요 ----
needs_ffmpeg = pytest.mark.skipif(not (find_tool("ffmpeg") and find_tool("ffprobe")), reason="ffmpeg 없음")


@pytest.fixture(scope="module")
def scene_video(tmp_path_factory):
    import subprocess
    from app import ffmpeg_tools as ft  # noqa: F401
    d = tmp_path_factory.mktemp("scene")
    out = str(d / "scene.mp4")
    # 빨강 5초 → 파랑 5초 → 초록 5초: 5초, 10초에 장면 전환
    subprocess.run([find_tool("ffmpeg"), "-v", "error", "-y",
                    "-f", "lavfi", "-i", "color=c=red:s=320x180:r=30:d=5",
                    "-f", "lavfi", "-i", "color=c=blue:s=320x180:r=30:d=5",
                    "-f", "lavfi", "-i", "color=c=green:s=320x180:r=30:d=5",
                    "-filter_complex", "[0][1][2]concat=n=3:v=1:a=0",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", out], check=True, capture_output=True)
    return out


@needs_ffmpeg
def test_detect_scenes(scene_video):
    from app import ffmpeg_tools as ft
    prog = []
    times = ft.detect_scenes(scene_video, 15.0, 0.3, 1.0, prog.append)
    assert len(times) == 2 and abs(times[0] - 5) < 0.2 and abs(times[1] - 10) < 0.2
    assert prog and prog[-1] > 0.9


@needs_ffmpeg
def test_grab_frame_and_vertical(scene_video, tmp_path):
    from app import ffmpeg_tools as ft
    png = ft.grab_frame(scene_video, 7.0, "png")
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    jpg = ft.grab_frame(scene_video, 7.0, "jpeg")
    assert jpg[:2] == b"\xff\xd8"
    assert ft.vertical_crop_filter(1920, 1080, 0.5) == "crop=606:1080:656:0,scale=1080:1920:flags=lanczos"
    assert ft.vertical_crop_filter(1080, 1920, 0.5).startswith("crop=1080:1920:0:0")
    out = str(tmp_path / "vert.mp4")
    info = ft.probe(scene_video)
    ft.Cutter().cut_vertical(scene_video, 4.0, 6.0, out, info, 0.0, lambda p: None)
    o = ft.probe(out)
    assert o["width"] == 1080 and o["height"] == 1920 and abs(o["duration"] - 2.0) < 0.1
