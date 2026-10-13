"""방송 북마크 저장소 · 녹화 파일 매핑 · 시작 화면 · 처음 실행 안내 · 샘플 영상."""
import os
import sys
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import bookmarks  # noqa: E402
from app.paths import find_tool  # noqa: E402
from app.segments import ClipProject  # noqa: E402
from app.startpanel import project_summary  # noqa: E402

needs_ffmpeg = pytest.mark.skipif(not (find_tool("ffmpeg") and find_tool("ffprobe")), reason="ffmpeg 없음")


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def store(tmp_path, monkeypatch):
    path = str(tmp_path / "bookmarks.jsonl")
    monkeypatch.setattr(bookmarks, "store_path", lambda: path)
    return path


# ---- 저장소 ----
def test_bookmark_store_roundtrip(store):
    assert bookmarks.load_bookmarks() == []
    t1 = bookmarks.add_bookmark("첫 번째")
    t2 = bookmarks.add_bookmark()
    assert t2 >= t1 and os.path.isfile(store)
    with open(store, "a", encoding="utf-8") as f:
        f.write("깨진 줄\n\n")
    items = bookmarks.load_bookmarks()
    assert [b["note"] for b in items] == ["첫 번째", ""]
    assert items[0]["ts"] == t1 and items[1]["ts"] == t2
    bookmarks.clear_bookmarks()
    assert bookmarks.load_bookmarks() == [] and not os.path.exists(store)
    bookmarks.clear_bookmarks()  # 없어도 조용히


def test_bookmarks_for_file(store, tmp_path):
    video = tmp_path / "rec.mp4"
    video.write_bytes(b"x")
    end = 1_700_000_000.0
    os.utime(str(video), (end, end))
    dur = 100.0
    bookmarks.add_bookmark("가운데", ts=end - 50.0)
    bookmarks.add_bookmark("녹화 전", ts=end - 150.0)
    bookmarks.add_bookmark("녹화 후", ts=end + 5.0)
    bookmarks.add_bookmark("끝 직전", ts=end - 0.5)
    bookmarks.add_bookmark("시작", ts=end - 100.0)
    hits = bookmarks.bookmarks_for_file(str(video), dur)
    assert hits == [(0.0, "시작"), (50.0, "가운데"), (99.5, "끝 직전")]
    assert bookmarks.bookmarks_for_file(str(tmp_path / "없음.mp4"), dur) == []
    assert bookmarks.bookmarks_for_file(str(video), 0.0) == []
    # 프로젝트에 마커로 넣기 (실행 취소 1단계, 경계값은 제외)
    proj = ClipProject(path=str(video), duration=dur)
    proj.rebuild_segments()
    assert bookmarks.apply_to_project(proj) == 2
    assert proj.markers == [50.0, 99.5] and len(proj.undo_stack) == 1
    assert bookmarks.apply_to_project(proj) == 0 and len(proj.undo_stack) == 1  # 중복은 추가 안 함
    assert proj.undo() and proj.markers == []


def test_fmt_bookmark_time():
    now = time.time()
    assert len(bookmarks.fmt_bookmark_time(now)) == 8
    assert len(bookmarks.fmt_bookmark_time(now - 3 * 86400)) == 14


# ---- 시작 화면 ----
def test_project_summary(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    assert project_summary(str(video)) == ""
    p = ClipProject(path=str(video), duration=100.0)
    p.rebuild_segments()
    p.add_markers([10.0, 20.0])
    p.segments[1].enabled = False
    assert p.save()
    assert project_summary(str(video)) == "마커 2개 · 켜진 구간 2개"
    (tmp_path / "bad.mp4").write_bytes(b"x")
    (tmp_path / "bad.mp4.clipslicer.json").write_text("{깨짐", encoding="utf-8")
    assert project_summary(str(tmp_path / "bad.mp4")) == ""


def test_start_panel_recent(qapp, tmp_path):
    from app.startpanel import StartPanel
    panel = StartPanel()
    assert panel.recent_box.isHidden()
    paths = []
    for i in range(7):
        f = tmp_path / f"clip{i}.mp4"
        f.write_bytes(b"x")
        paths.append(str(f))
    p = ClipProject(path=paths[0], duration=60.0)
    p.rebuild_segments()
    p.add_marker(30.0)
    assert p.save()
    panel.set_recent([str(tmp_path / "missing.mp4"), paths[0], paths[0]] + paths[1:])
    assert len(panel.recent_buttons) == 5
    assert panel.recent_buttons[0].text() == "📝 clip0.mp4 — 마커 1개 · 켜진 구간 2개"
    assert panel.recent_buttons[1].text() == "🎞 clip1.mp4"
    assert panel.recent_box.isVisibleTo(panel)
    got = []
    panel.fileRequested.connect(got.append)
    panel.recent_buttons[0].click()
    assert got == [paths[0]]
    fired = []
    panel.openRequested.connect(lambda: fired.append("open"))
    panel.urlRequested.connect(lambda: fired.append("url"))
    panel.sampleRequested.connect(lambda: fired.append("sample"))
    panel.b_open.click()
    panel.b_url.click()
    panel.b_sample.click()
    assert fired == ["open", "url", "sample"]
    panel.set_recent([])
    assert panel.recent_buttons == [] and panel.recent_box.isHidden()


# ---- 처음 실행 안내 / 샘플 ----
class _FakeSettings:
    def __init__(self):
        self.d = {}

    def value(self, k, default=None):
        return self.d.get(k, default)

    def setValue(self, k, v):
        self.d[k] = v

    def contains(self, k):
        return k in self.d


def test_first_run_dialog(qapp):
    from app.firstrun import FirstRunDialog
    s = _FakeSettings()
    assert FirstRunDialog.should_show(s)
    # 0.7 이하에서 올라온 기존 설치 (first_run_done 은 없지만 쓰던 설정은 있음) 는 안내를 건너뛴다
    old = _FakeSettings()
    old.setValue("mode", "fast")
    assert not FirstRunDialog.should_show(old)
    d = FirstRunDialog()
    assert d.dont_show_again
    fired = []
    d.sampleRequested.connect(lambda: fired.append(1))
    d.b_sample.click()
    assert fired == [1] and d.result() == FirstRunDialog.Accepted
    FirstRunDialog.mark_done(s)
    assert not FirstRunDialog.should_show(s)


def test_bookmark_window_offscreen(qapp, store, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from app.bookmarks import BookmarkWindow, GlobalHotkey
    monkeypatch.setattr(GlobalHotkey, "register", lambda self, name: (False, "테스트"))  # 실제 단축키 등록 금지
    monkeypatch.setattr(QApplication, "beep", staticmethod(lambda: None))
    s = _FakeSettings()
    w = BookmarkWindow(None, s)
    assert w.hotkey_name == bookmarks.DEFAULT_HOTKEY and w.list.count() == 0
    got = []
    w.bookmarked.connect(got.append)
    ts = w.bookmark_now()
    assert got == [ts] and w.list.count() == 1 and bookmarks.load_bookmarks()[0]["ts"] == ts
    w.cb_hotkey.setCurrentText("F9")
    assert s.value(bookmarks.SETTINGS_KEY) == "F9"
    w.b_clear.click()
    assert w.list.count() == 0 and bookmarks.load_bookmarks() == []
    w.close()


def test_notifier_offscreen(qapp):
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QMainWindow
    from app.notify import Notifier
    win = QMainWindow()
    n = Notifier(win, QIcon())  # 트레이가 없는 환경(offscreen)에서도 죽지 않고, 있으면 풍선을 띄운다
    assert isinstance(n.notify("제목", "내용", force=True), bool)
    assert n.notify("제목", "내용") is False or n.available
    n.hide()


@needs_ffmpeg
def test_make_sample(tmp_path):
    from app import ffmpeg_tools as ft
    from app.firstrun import make_sample
    dst = str(tmp_path / "samples" / "sample.mp4")
    assert make_sample(dst) == dst and os.path.isfile(dst)
    info = ft.probe(dst)
    assert abs(info["duration"] - 30.0) < 0.5
    assert info["width"] == 640 and info["height"] == 360 and info["has_audio"]
    mtime = os.path.getmtime(dst)
    assert make_sample(dst) == dst and os.path.getmtime(dst) == mtime  # 캐시 사용
    assert not os.path.exists(dst + ".part.mp4")
