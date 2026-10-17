"""타임라인 정밀 조작: 프레임 단위 확대 한계 · 확대 막대 · 구간 맞춤 · 자석 · 프레임 시각 표시."""
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.segments import ClipProject  # noqa: E402
from app.timeline import fmt_timecode  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def make(duration=600.0, fps=30.0):
    p = ClipProject(path="C:/v/a.mp4", duration=duration, fps=fps)
    p.rebuild_segments()
    return p


def widget(qapp, proj):
    from app.timeline import TimelineWidget
    w = TimelineWidget()
    w.resize(1000, 120)
    w.canvas.resize(1000, w.canvas.height())
    w.canvas.set_project(proj)
    return w


def test_fmt_timecode():
    assert fmt_timecode(0, 30) == "00:00:00"
    assert fmt_timecode(83.5, 30) == "01:23:15"
    assert fmt_timecode(3600 + 1 / 30, 30) == "1:00:00:01"
    assert fmt_timecode(1.0, 59.94) == "00:01:00"      # 60fps 계열은 60 프레임으로 센다
    assert fmt_timecode(-3, 0) == "00:00:00"


def test_zoom_down_to_frames(qapp):
    w = widget(qapp, make())
    c = w.canvas
    assert math.isclose(c.min_view_len(), 15 / 30)
    for _ in range(60):
        c.zoom(2.0)
    assert math.isclose(c.view_len, 0.5) and math.isclose(c.zoom_factor(), 1200)
    assert w.zoom_slider.value() == w.ZOOM_STEPS            # 끝까지 확대 = 막대 끝
    c.zoom_reset()
    assert c.view_len == 600 and w.zoom_slider.value() == 0
    w.zoom_slider.setValue(w.ZOOM_STEPS // 2)              # 로그 눈금: 가운데 ≈ √1200 배
    assert abs(c.zoom_factor() - math.sqrt(1200)) / math.sqrt(1200) < 0.02
    assert abs(w.zoom_slider.value() - w.ZOOM_STEPS // 2) <= 1


def test_zoom_to_segment(qapp):
    p = make()
    p.add_marker(100.0)
    p.add_marker(160.0)
    w = widget(qapp, p)
    c = w.canvas
    c.position = 130.0
    assert c.zoom_to_segment()
    assert c.view_start < 100.0 and c.view_start + c.view_len > 160.0 and c.view_len < 70.0
    assert c.zoom_to_segment(0) and c.view_start == 0.0


def test_snap_to_keyframe_and_origin(qapp):
    p = make()
    p.keyframes = [10.0, 12.0]
    p.add_marker(20.0)
    w = widget(qapp, p)
    c = w.canvas
    c.zoom_to_range(0, 100, pad=0)                           # 1000px = 100초 → 8px = 0.8초
    c._drag_origin = 20.0
    assert c.snapped(10.5) == (10.0, 10.0)                   # 키프레임에 붙음
    assert c.snapped(10.5, enabled=False) == (10.5, None)    # Shift = 자석 끔
    assert c.snapped(19.6) == (20.0, 20.0)                   # 끌기 전 자리로 돌아오기 쉬움
    assert c.snapped(15.0) == (15.0, None)
    c.show_keyframes = False
    assert c.snapped(10.5) == (10.5, None)


_NUDGE = r"""
import os, sys, tempfile
sys.path.insert(0, sys.argv[1])
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
from PySide6.QtWidgets import QApplication
app = QApplication([])
from app.mainwindow import MainWindow
from app.segments import ClipProject
w = MainWindow()
p = ClipProject(path="C:/v/a.mp4", duration=600.0, fps=30.0)
p.rebuild_segments()
p.add_marker(10.0)
p.add_marker(50.0)
w.current = p
w.timeline.canvas.set_project(p)
w.player.seek = lambda t: None          # 화면 없는 테스트: 영상 없이 플레이어(libmpv)를 건드리지 않게
w._set_loop = lambda *a: None
w._highlight_row = lambda *a: None
w.timeline.canvas.selected_marker = 1
w.nudge_marker(1)
a = p.markers[1]
w.nudge_marker(-10)
b = p.markers[1]
p.undo()
c = p.markers[1]
print("RESULT", round(a * 30), round(b * 30), round(c * 30), p.markers[0], flush=True)
os._exit(0)   # 화면 없는 libmpv 정리 단계에서 죽는 것을 피한다 (결과는 이미 출력)
"""


def test_nudge_marker_by_frames():
    import subprocess
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    r = subprocess.run([sys.executable, "-c", _NUDGE, root], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=120, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    line = next((l for l in r.stdout.splitlines() if l.startswith("RESULT")), None)
    assert line, (r.returncode, r.stderr[-1500:])
    _, a, b, c, first = line.split()
    assert (int(a), int(b), int(c)) == (1501, 1491, 1501) and float(first) == 10.0   # 50초=1500프레임 → +1 → -10 → 되돌리기
