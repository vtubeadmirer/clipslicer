"""ffmpeg / mpv 없이 돌아가는 모델 테스트."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.segments import ClipProject, fmt_time, fmt_time_file, parse_time, safe_filename  # noqa: E402


def make(duration=100.0):
    p = ClipProject(path="C:/video/sample.mp4", duration=duration, fps=30.0)
    p.rebuild_segments()
    return p


def test_markers_make_segments():
    p = make()
    assert len(p.segments) == 1
    assert p.add_marker(30.0) and p.add_marker(10.0)
    assert p.markers == [10.0, 30.0]
    assert [(s.start, s.end) for s in p.segments] == [(0.0, 10.0), (10.0, 30.0), (30.0, 100.0)]


def test_marker_too_close_or_out_of_range_rejected():
    p = make()
    assert p.add_marker(10.0)
    assert not p.add_marker(10.02)
    assert not p.add_marker(0.0)
    assert not p.add_marker(100.0)


def test_move_marker_keeps_order():
    p = make()
    p.add_marker(10.0)
    p.add_marker(30.0)
    p.move_marker(0, 50.0)  # 다음 마커(30) 를 넘지 못함
    assert p.markers[0] < 30.0
    p.move_marker(1, 90.0)
    assert p.markers == [p.markers[0], 90.0]


def test_segment_state_survives_rebuild():
    p = make()
    p.add_marker(10.0)
    p.segments[1].enabled = False
    p.segments[1].name = "tail"
    p.add_marker(50.0)  # 10~100 이 10~50, 50~100 으로 나뉨: 시작 시각 기준으로 설정 유지
    assert p.segments[1].enabled is False and p.segments[1].name == "tail"
    assert p.segments[2].enabled is True


def test_undo_redo():
    p = make()
    p.push_undo()
    p.add_marker(10.0)
    p.push_undo()
    p.segments[0].enabled = False
    assert p.undo() and p.segments[0].enabled is True and p.markers == [10.0]
    assert p.undo() and p.markers == []
    assert not p.undo()
    assert p.redo() and p.markers == [10.0]
    assert p.redo() and p.segments[0].enabled is False


def test_json_roundtrip(tmp_path):
    p = ClipProject(path=str(tmp_path / "v.mp4"), duration=60.0)
    p.rebuild_segments()
    p.add_marker(20.0)
    p.segments[1].name = "second"
    p.segments[0].enabled = False
    p.last_position = 12.5
    assert p.save()
    q = ClipProject(path=p.path, duration=60.0)
    q.rebuild_segments()
    assert q.load()
    assert q.markers == [20.0]
    assert q.segments[0].enabled is False and q.segments[1].name == "second"
    assert q.last_position == 12.5
    data = json.loads(open(p.project_file, encoding="utf-8").read())
    assert data["version"] == 1


def test_output_names_and_patterns():
    p = make()
    p.add_marker(65.0)
    assert p.output_name(0, ".mp4") == "sample_01.mp4"
    assert p.output_name(1, ".mp4", "{name}_{start}-{end}") == "sample_01m05s-01m40s.mp4"
    p.segments[1].name = 'bad:name?'
    assert p.output_name(1, ".mkv") == "bad_name_.mkv"
    assert p.output_name(0, ".mp4", "{nope}") == "sample_01.mp4"  # 잘못된 규칙은 기본값


def test_time_helpers():
    assert fmt_time(65.5) == "01:05.500"
    assert fmt_time(3661.25) == "01:01:01.250"
    assert fmt_time(3661.25, ms=False) == "1:01:01"
    assert fmt_time_file(3725) == "01h02m05s"
    assert parse_time("1:23.5") == 83.5
    assert parse_time("01:02:03") == 3723.0
    assert parse_time("83.5") == 83.5
    assert parse_time("1h2m3s") == 3723.0
    assert parse_time("abc") is None
    assert safe_filename('a/b\\c:d') == "a_b_c_d"


def test_nearest_marker_and_keyframe():
    p = make()
    p.add_marker(10.0)
    p.add_marker(20.0)
    assert p.nearest_marker(10.3, tol=0.5) == 0
    assert p.nearest_marker(15.0, tol=0.5) == -1
    p.keyframes = [0.0, 8.0, 16.0]
    assert p.nearest_keyframe(8.3, 0.5) == 8.0
    assert p.nearest_keyframe(12.0, 0.5) is None
