"""영상 이어 붙이기: 방식 결정(복사/재인코딩) · 실제로 이어 붙이기 (같은 규격 · 다른 규격 + 소리 없는 영상 · 구간만)."""
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.join import JoinWorker, join_plan, render_target  # noqa: E402
from app.paths import find_tool  # noqa: E402

needs_ffmpeg = pytest.mark.skipif(not find_tool("ffmpeg"), reason="ffmpeg 없음")


def _info(w=1920, h=1080, fps=30.0, v="h264", a="aac", audio=True, dur=10.0):
    return {"width": w, "height": h, "fps": fps, "vcodec": v, "acodec": a if audio else "", "has_audio": audio, "duration": dur}


def _it(info, parts=None):
    return {"path": "x.mp4", "info": info, "parts": parts or [(0.0, info["duration"])]}


def test_join_plan():
    assert join_plan([_it(_info()), _it(_info(dur=5))])[0] == "copy"
    assert join_plan([_it(_info()), _it(_info(w=1280, h=720))])[0] == "render"
    assert join_plan([_it(_info()), _it(_info(fps=60))])[0] == "render"
    assert join_plan([_it(_info()), _it(_info(audio=False))])[0] == "render"
    assert join_plan([_it(_info()), _it(_info(a="opus"))])[0] == "render"
    assert join_plan([_it(_info(v="vp9")), _it(_info(v="vp9"))])[0] == "render"   # mp4 에 그대로 못 담음
    assert join_plan([_it(_info(fps=29.97)), _it(_info(fps=29.97))])[0] == "copy"


def test_render_target():
    size, fps = render_target([_it(_info(1280, 720, 30)), _it(_info(1920, 1080, 60)), _it(_info(853, 480, 120))])
    assert size == (1920, 1080) and fps == 60.0           # 가장 큰 화면, fps 는 최대 60
    assert render_target([_it(_info(853, 481, 25))])[0] == (852, 480)   # 짝수로


def _make(path, w, h, fps, dur, audio=True):
    cmd = [find_tool("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size={w}x{h}:rate={fps}:duration={dur}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={dur}", "-c:a", "aac", "-shortest"]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-g", str(fps), "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(cmd, check=True, capture_output=True)


def _run(items, dst):
    from PySide6.QtCore import QCoreApplication
    from app import ffmpeg_tools as ft
    QCoreApplication.instance() or QCoreApplication([])
    res = {}
    w = JoinWorker([dict(it, info=ft.probe(it["path"])) for it in items], str(dst))
    w.done.connect(lambda p, e: res.update(path=p, err=e))
    w.run()   # 같은 스레드에서 바로 (신호도 바로 전달)
    return res


@needs_ffmpeg
def test_join_same_format_copy_and_segments(tmp_path):
    from app import ffmpeg_tools as ft
    a, b = tmp_path / "a.mp4", tmp_path / "b.mp4"
    _make(a, 320, 180, 30, 4)
    _make(b, 320, 180, 30, 3)
    res = _run([{"path": str(a), "parts": [(0.0, 4.0)]}, {"path": str(b), "parts": [(0.0, 3.0)]}], tmp_path / "ab.mp4")
    assert res.get("path") and not res.get("err"), res
    i = ft.probe(res["path"])
    assert abs(i["duration"] - 7.0) < 0.4 and i["width"] == 320 and i["has_audio"]
    # 켜진 구간만: a 의 1~3초 + b 전체
    res = _run([{"path": str(a), "parts": [(1.0, 3.0)]}, {"path": str(b), "parts": [(0.0, 3.0)]}], tmp_path / "seg.mp4")
    assert res.get("path") and abs(ft.probe(res["path"])["duration"] - 5.0) < 1.2, res


@needs_ffmpeg
def test_join_different_formats_render(tmp_path):
    from app import ffmpeg_tools as ft
    a, c = tmp_path / "a.mp4", tmp_path / "c.mp4"
    _make(a, 320, 180, 30, 3)
    _make(c, 640, 360, 25, 2, audio=False)            # 크기 · fps 다르고 소리 없음
    items = [{"path": str(c), "parts": [(0.0, 2.0)]}, {"path": str(a), "parts": [(0.5, 2.5)]}]
    res = _run(items, tmp_path / "mix.mp4")
    assert res.get("path") and not res.get("err"), res
    i = ft.probe(res["path"])
    assert (i["width"], i["height"]) == (640, 360) and abs(i["fps"] - 30) < 0.1 and i["has_audio"], i
    assert abs(i["duration"] - 4.0) < 1.2, i
    assert not [d for d in os.listdir(tmp_path) if d.startswith("clipslicer_join_")]
