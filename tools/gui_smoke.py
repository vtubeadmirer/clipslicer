"""GUI 스모크 테스트 (pytest 아님 — libmpv 가 실제 창을 필요로 한다).

사용: python tools/gui_smoke.py ko|en
  %TEMP%/clipslicer_test/test2.mp4 를 열고 (없으면 firstrun.make_sample 로 만든다) QTimer 로 단계를 돌린다:
  마커 추가 → 메모 → 파형 뒤 loud_peaks → 합치기 순서 이동 → 시작 패널 최근 목록 → 새 대화상자들 열고 닫기
  → 음량 정규화 + 캡션으로 4초 구간 내보내기 → 결과 probe → 스크린샷 %TEMP%/clipslicer_test/smoke_<lang>.png → 종료.
  설정은 임시 ini 를 써서 사용자 settings.ini 를 건드리지 않는다. 종료 코드 0 = 통과.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

LANG = (sys.argv[1] if len(sys.argv) > 1 else "ko").lower()
TEST_DIR = os.path.join(tempfile.gettempdir(), "clipslicer_test")
VIDEO = os.path.join(TEST_DIR, "test2.mp4")
OUT_DIR = os.path.join(TEST_DIR, f"smoke_out_{LANG}")
SHOT = os.path.join(TEST_DIR, f"smoke_{LANG}.png")
INI = os.path.join(TEST_DIR, f"smoke_{LANG}.ini")
TIMEOUT_S = 60.0

os.makedirs(TEST_DIR, exist_ok=True)
# 이전 실행이 남긴 작업 파일 (마커·구간 상태) 과 캐시가 결과를 바꾸지 않도록 지운다
for stale in (INI, SHOT, VIDEO + ".clipslicer.json", VIDEO + ".clipslicer.json.bak", VIDEO + ".clipslicer.chat.json"):
    try:
        os.remove(stale)
    except OSError:
        pass

from PySide6.QtCore import Qt, QSettings, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app import i18n, paths  # noqa: E402
from app.firstrun import make_sample, FirstRunDialog  # noqa: E402

i18n.set_language(LANG)
if not os.path.isfile(VIDEO):
    make_sample(VIDEO)

from app.paths import missing_tools  # noqa: E402

if missing_tools():
    print("필수 도구 없음:", missing_tools())
    sys.exit(2)

app = QApplication(sys.argv)
app.setApplicationName("ClipSlicerSmoke")

# 사용자 settings.ini 대신 임시 ini
_settings = QSettings(INI, QSettings.IniFormat)
_settings.setValue("first_run_done", "1")
_settings.setValue("check_updates", "0")
_settings.setValue("out_dir", OUT_DIR)
_settings.setValue("recent", [VIDEO])
_settings.sync()
paths.make_settings = lambda: QSettings(INI, QSettings.IniFormat)

import app.mainwindow as mw_mod  # noqa: E402
from app.mainwindow import MainWindow, COL_NOTE, COL_ORDER  # noqa: E402
from app.segments import loud_peaks  # noqa: E402
from app import ffmpeg_tools  # noqa: E402
from app.bookmarks import BookmarkWindow  # noqa: E402
from app.chat import ChatDialog  # noqa: E402
from app.upload_history import HistoryDialog  # noqa: E402
from app.discord import DiscordSettingsDialog  # noqa: E402
from app.youtube_ui import PresetDialog, PresetStore  # noqa: E402

mw_mod.make_settings = paths.make_settings

win = MainWindow()
win.show()

results: list[tuple[str, bool, str]] = []
state: dict = {"export": None, "deadline": time.time() + TIMEOUT_S}


def check(name: str, ok: bool, detail: str = ""):
    results.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  {detail}" if detail else ""))


def proj():
    return win.current


# ---- 단계 ----
def step_open():
    win.add_files([VIDEO])
    return lambda: proj() is not None and proj().path == os.path.abspath(VIDEO) and win.player.duration > 0


def step_markers():
    p = proj()
    p.push_undo()
    n = p.add_markers([2.0, 6.0, 12.0])
    win._changed()
    check("markers", n == 3 and len(p.segments) == 4, f"segments={len(p.segments)}")


def step_note():
    p = proj()
    p.push_undo()
    p.segments[1].note = "smoke note"
    win._changed()
    it = win.table.item(1, COL_NOTE)
    check("note column", it is not None and it.text() == "smoke note", repr(it.text() if it else None))


def step_wait_wave():
    return lambda: bool(proj().waveform)


def step_loud():
    p = proj()
    times = loud_peaks(p.waveform, p.duration)
    check("loud_peaks", isinstance(times, list), f"{len(times)} peaks on {len(p.waveform)} buckets")


def step_merge_order():
    p = proj()
    for s in p.segments:
        s.enabled = True
    p.merge_order = []
    win.cb_merge.setChecked(True)
    before = [i for i, _ in p.ordered_enabled()]
    win._move_segment_order(2, -1)
    after = [i for i, _ in p.ordered_enabled()]
    visible = not win.table.isColumnHidden(COL_ORDER)
    check("merge order", visible and before[:2] == [0, 1] and after[1] == 2 and after[2] == 1, f"{before} -> {after}, col visible={visible}")
    win.undo()
    win.cb_merge.setChecked(False)
    check("merge order undo", [i for i, _ in p.ordered_enabled()] == before)


def step_startpanel():
    panel = win.drop_label
    panel.set_recent([VIDEO, os.path.join(TEST_DIR, "does_not_exist.mp4")])
    n = len(panel.recent_buttons)
    check("startpanel recent", n == 1, f"rows={n}")


def _open_close(name: str, make):
    try:
        d = make()
        d.show()
        app.processEvents()
        d.close()
        d.deleteLater()
        check(f"dialog {name}", True)
    except Exception as ex:  # noqa: BLE001
        check(f"dialog {name}", False, f"{type(ex).__name__}: {ex}")
        traceback.print_exc()


def step_dialogs():
    _open_close("BookmarkWindow", lambda: BookmarkWindow(win, win.settings))
    _open_close("ChatDialog", lambda: ChatDialog(win, url="", duration=proj().duration))
    _open_close("HistoryDialog", lambda: HistoryDialog(win, entries=[]))
    _open_close("DiscordSettingsDialog", lambda: DiscordSettingsDialog(win, win.settings))
    _open_close("PresetDialog", lambda: PresetDialog(win, PresetStore(win.settings)))
    _open_close("FirstRunDialog", lambda: FirstRunDialog(win))
    from app.dialogs import RenderAssetsDialog, LoudDialog
    _open_close("RenderAssetsDialog", lambda: RenderAssetsDialog(win, win.settings))
    _open_close("LoudDialog", lambda: LoudDialog(win))
    win.act_right_panel.setChecked(False)
    hidden = not win.right_panel.isVisible()
    win.act_right_panel.setChecked(True)
    check("right panel toggle", hidden and win.right_panel.isVisible())


def step_export():
    p = proj()
    for i, s in enumerate(p.segments):
        s.enabled = (i == 1)   # 2.0 ~ 6.0 = 4초
    win._changed()
    win.ed_outdir.setText(OUT_DIR)
    win.cb_normalize.setChecked(True)
    win.ed_caption.setText("Smoke caption")
    win.cb_open.setChecked(False)
    win.cb_youtube.setChecked(False)
    win.cb_discord.setChecked(False)
    idx = win.cb_mode.findData("fast")
    win.cb_mode.setCurrentIndex(idx)
    jobs = win._build_jobs([p])
    check("build jobs", len(jobs) == 1 and jobs[0].normalize and jobs[0].caption == "Smoke caption" and jobs[0].dst.endswith(".mp4"),
          f"{len(jobs)} jobs, dst={os.path.basename(jobs[0].dst) if jobs else None}")
    for j in jobs:
        if os.path.exists(j.dst):
            os.remove(j.dst)
    state["dst"] = jobs[0].dst if jobs else ""

    def on_done(ok, fail):
        state["export"] = (ok, fail)

    win.start_export(all_files=False)
    if win.export_worker:
        win.export_worker.allFinished.connect(on_done)
    chip_seen = {"v": False}

    def wait():
        if win.lbl_export.text():
            chip_seen["v"] = True
        state["chip"] = chip_seen["v"]
        return state["export"] is not None
    return wait


def step_probe():
    ok, fail = state["export"]
    dst = state.get("dst", "")
    info = ffmpeg_tools.probe(dst) if os.path.isfile(dst) else {}
    dur = float(info.get("duration", 0))
    check("export normalize+caption", ok == 1 and fail == 0 and abs(dur - 4.0) < 0.6 and info.get("has_audio"),
          f"ok={ok} fail={fail} dur={dur:.2f} acodec={info.get('acodec')} chip_seen={state.get('chip')}")
    check("export chip cleared", win.lbl_export.text() == "")


def step_shot():
    app.processEvents()
    pix = win.grab()
    saved = pix.save(SHOT, "PNG")
    check("screenshot", saved and os.path.getsize(SHOT) > 1000, SHOT)


STEPS = [step_open, step_markers, step_note, step_wait_wave, step_loud, step_merge_order, step_startpanel,
         step_dialogs, step_export, step_probe, step_shot]
cursor = {"i": 0, "wait": None, "wait_since": 0.0}


def finish(code: int):
    if state.get("finished"):
        return
    state["finished"] = True
    timer.stop()
    try:
        win.close()
    except Exception:  # noqa: BLE001
        traceback.print_exc()
    failed = [r for r in results if not r[1]]
    print(f"== {LANG}: {len(results) - len(failed)} passed, {len(failed)} failed")
    state["code"] = code
    QTimer.singleShot(100, lambda: app.exit(code))


def tick():
    try:
        if time.time() > state["deadline"]:
            check("timeout", False, f"step {cursor['i']} ({STEPS[cursor['i']].__name__ if cursor['i'] < len(STEPS) else '-'})")
            finish(1)
            return
        if cursor["wait"] is not None:
            if not cursor["wait"]():
                if time.time() - cursor["wait_since"] > 45:
                    check("wait timeout", False, STEPS[cursor["i"] - 1].__name__)
                    finish(1)
                    return
                return
            cursor["wait"] = None
        if cursor["i"] >= len(STEPS):
            finish(0 if all(r[1] for r in results) else 1)
            return
        step = STEPS[cursor["i"]]
        cursor["i"] += 1
        cond = step()
        if callable(cond):
            cursor["wait"] = cond
            cursor["wait_since"] = time.time()
    except Exception as ex:  # noqa: BLE001
        traceback.print_exc()
        check(f"exception in step {cursor['i']}", False, f"{type(ex).__name__}: {ex}")
        finish(1)


timer = QTimer()
timer.setInterval(150)
timer.timeout.connect(tick)
QTimer.singleShot(500, timer.start)
rc = app.exec()
sys.exit(state.get("code", rc) or rc)
