"""일괄 작업 모델 테스트: 구간 메모, 합치기 순서, 저장 백업, 큰 소리 찾기, 북마크 → 마커. ffmpeg / mpv 불필요."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.segments import ClipProject, bookmarks_to_markers, loud_peaks  # noqa: E402


def make(duration=100.0, path="C:/video/sample.mp4"):
    p = ClipProject(path=path, duration=duration, fps=30.0)
    p.rebuild_segments()
    return p


def order_of(p: ClipProject) -> list[int]:
    return [i for i, _ in p.ordered_enabled()]


def read_json(p: ClipProject) -> dict:
    with open(p.project_file, encoding="utf-8") as f:
        return json.load(f)


# ---- 메모 ----
def test_note_survives_rebuild_undo_and_json(tmp_path):
    p = make(path=str(tmp_path / "v.mp4"))
    p.add_marker(10.0)
    p.segments[1].note = "웃음 터짐"
    p.add_marker(50.0)  # 10~100 이 10~50, 50~100 으로 나뉨: 메모는 시작 시각 기준으로 유지
    assert p.segments[1].note == "웃음 터짐" and p.segments[2].note == ""
    p.push_undo()
    p.segments[1].note = "바뀐 메모"
    assert p.undo() and p.segments[1].note == "웃음 터짐"
    assert p.redo() and p.segments[1].note == "바뀐 메모"
    assert p.save()
    q = make(path=p.path)
    assert q.load()
    assert [s.note for s in q.segments] == ["", "바뀐 메모", ""]
    assert read_json(p)["segments"][1]["note"] == "바뀐 메모"


def test_load_without_note_field_defaults_empty(tmp_path):
    p = make(path=str(tmp_path / "v.mp4"))
    data = {"version": 1, "duration": 100.0, "markers": [10.0],
            "segments": [{"start": 0.0, "enabled": True, "name": "a"}, {"start": 10.0, "enabled": False, "name": ""}]}
    with open(p.project_file, "w", encoding="utf-8") as f:
        json.dump(data, f)
    assert p.load()
    assert [s.note for s in p.segments] == ["", ""]
    assert p.segments[0].name == "a" and p.segments[1].enabled is False
    assert p.merge_order == [] and p.source_url == "" and p.chat is None


# ---- 합치기 순서 ----
def test_ordered_enabled_chronological_by_default():
    p = make()
    p.add_markers([10.0, 20.0, 30.0])
    assert order_of(p) == [0, 1, 2, 3]
    assert p.ordered_enabled() == p.enabled_segments()


def test_ordered_enabled_follows_merge_order_then_chronological():
    p = make()
    p.add_markers([10.0, 20.0, 30.0])
    p.merge_order = [30.0, 10.0]
    assert order_of(p) == [3, 1, 0, 2]
    p.segments[1].enabled = False
    assert order_of(p) == [3, 0, 2]
    assert p.merge_position(3) == 0 and p.merge_position(2) == 2 and p.merge_position(1) == -1


def test_move_in_order():
    p = make()
    p.add_markers([10.0, 20.0, 30.0])
    assert not p.move_in_order(0, -1)       # 이미 맨 앞
    assert not p.move_in_order(3, 1)        # 이미 맨 뒤
    assert not p.move_in_order(1, 0)
    assert not p.move_in_order(9, -1)       # 없는 구간
    assert p.merge_order == []
    assert p.move_in_order(2, -2)
    assert order_of(p) == [2, 0, 1, 3]
    assert p.merge_order == [20.0, 0.0, 10.0, 30.0]   # 전체 순서가 확정됨
    assert p.move_in_order(2, 1)
    assert order_of(p) == [0, 2, 1, 3]
    assert p.move_in_order(3, -3)
    assert order_of(p) == [3, 0, 2, 1]
    assert not p.move_in_order(1, 5)        # 끝을 넘는 이동은 제자리


def test_move_in_order_keeps_enabled_block_first():
    p = make()
    p.add_markers([10.0, 20.0, 30.0])
    p.segments[0].enabled = False
    assert p.move_in_order(2, -1)
    assert order_of(p) == [2, 1, 3]
    assert p.merge_order == [20.0, 10.0, 30.0, 0.0]   # 꺼진 구간은 뒤에


def test_merge_order_pruned_on_rebuild_and_load(tmp_path):
    p = make(path=str(tmp_path / "v.mp4"))
    p.add_markers([10.0, 20.0])
    p.merge_order = [20.0, 0.0, 10.0]
    p.remove_marker(1)                      # 20.0 구간 사라짐
    assert p.merge_order == [0.0, 10.0]
    assert order_of(p) == [0, 1]
    p.merge_order = [10.0, 10.0, 99.0]      # 중복·없는 시각
    p.rebuild_segments()
    assert p.merge_order == [10.0]
    p.merge_order = [10.0, 0.0, 77.0]
    p.save()
    with open(p.project_file, encoding="utf-8") as f:
        data = json.load(f)
    data["merge_order"] = [10.0, 55.0, 0.0]
    with open(p.project_file, "w", encoding="utf-8") as f:
        json.dump(data, f)
    q = make(path=p.path)
    assert q.load() and q.merge_order == [10.0, 0.0]


def test_merge_order_and_source_url_persist_and_undo(tmp_path):
    p = make(path=str(tmp_path / "v.mp4"))
    p.add_markers([10.0, 20.0])
    p.source_url = "https://example.com/watch?v=abc"
    p.chat = {"messages": [1, 2, 3]}
    p.push_undo()
    assert p.move_in_order(2, -2)
    assert p.save()
    data = read_json(p)
    assert data["merge_order"] == [20.0, 0.0, 10.0] and data["source_url"] == "https://example.com/watch?v=abc"
    assert "chat" not in data
    q = make(path=p.path)
    assert q.load()
    assert q.merge_order == [20.0, 0.0, 10.0] and q.source_url == "https://example.com/watch?v=abc" and q.chat is None
    assert order_of(q) == [2, 0, 1]
    assert p.undo() and p.merge_order == [] and order_of(p) == [0, 1, 2]
    assert p.redo() and p.merge_order == [20.0, 0.0, 10.0]


# ---- 저장 백업 ----
def test_save_creates_backup_of_previous_file(tmp_path):
    p = make(path=str(tmp_path / "v.mp4"))
    assert p.save()
    bak = p.project_file + ".bak"
    assert not os.path.exists(bak)          # 처음 저장: 백업할 것이 없음
    with open(p.project_file, encoding="utf-8") as f:
        first = f.read()
    p.add_marker(10.0)
    assert p.save()
    assert os.path.exists(bak)
    with open(bak, encoding="utf-8") as f:
        assert f.read() == first
    assert read_json(p)["markers"] == [10.0]


# ---- 큰 소리 찾기 ----
def test_loud_peaks_flat_or_empty_gives_nothing():
    assert loud_peaks([], 100.0) == []
    assert loud_peaks([0.3] * 100, 100.0) == []
    assert loud_peaks([1.0] * 100, 100.0) == []
    assert loud_peaks([0.0] * 100, 100.0) == []
    assert loud_peaks([0.5] * 100, 0.0) == []


def test_loud_peaks_single_spike_minus_lead():
    wave = [0.1] * 100
    wave[50] = 0.9
    assert loud_peaks(wave, 100.0) == [48.0]
    assert loud_peaks(wave, 100.0, lead=0.0) == [50.0]
    assert loud_peaks(wave, 200.0) == [98.0]   # bucket 하나 = 2초
    wave = [0.1] * 100
    wave[1] = 0.9
    assert loud_peaks(wave, 100.0) == [0.0]    # lead 를 빼도 0 아래로는 안 내려감


def test_loud_peaks_consecutive_buckets_are_one_group():
    wave = [0.1] * 100
    wave[50:53] = [0.6, 0.9, 0.7]
    assert loud_peaks(wave, 100.0) == [49.0]


def test_loud_peaks_min_gap_keeps_loudest():
    wave = [0.1] * 100
    wave[50] = 0.7
    wave[55] = 0.9
    assert loud_peaks(wave, 100.0) == [53.0]
    assert loud_peaks(wave, 100.0, min_gap=3.0) == [48.0, 53.0]


def test_loud_peaks_respects_max_count_loudest_first():
    wave = [0.1] * 100
    for i in (10, 30, 50, 70, 90):
        wave[i] = 0.9
    wave[70] = 1.0
    wave[30] = 0.95
    assert loud_peaks(wave, 100.0) == [8.0, 28.0, 48.0, 68.0, 88.0]
    assert loud_peaks(wave, 100.0, max_count=2) == [28.0, 68.0]
    assert loud_peaks(wave, 100.0, max_count=0) == []


def test_loud_peaks_threshold_uses_factor():
    wave = [0.2] * 100
    wave[40] = 0.5
    assert loud_peaks(wave, 100.0, factor=3.0) == []        # 0.5 < 0.6
    assert loud_peaks(wave, 100.0, factor=2.0) == [38.0]    # 0.5 > 0.4


# ---- 북마크 → 마커 ----
def test_bookmarks_to_markers_in_and_out_of_range():
    end = 1_700_000_000.0
    dur = 3600.0
    marks = [end - 10, end - 3000, end - 3605, end - 3600, end - 1800.1234, end, end + 5, end - 3000]
    assert bookmarks_to_markers(marks, end, dur) == [600.0, 1799.877, 3590.0]
    assert bookmarks_to_markers([], end, dur) == []
    assert bookmarks_to_markers([end - 10], end, 0.0) == []
