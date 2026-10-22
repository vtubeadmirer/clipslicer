"""영상 이어 붙이기: 서로 다른 영상 파일(또는 그 안의 켜진 구간)을 순서대로 하나로.

규격(코덱 · 해상도 · fps · 오디오)이 모두 같으면 재인코딩 없이 바로 이어 붙이고(빠름, 화질 그대로),
다르면 가장 큰 화면 · 높은 fps 에 맞춰 재인코딩한다 (크기가 다른 영상은 가운데 두고 검은 여백, 소리 없는 영상은 무음).
복사 방식이 실패하면 자동으로 재인코딩으로 다시 한다.
"""
from __future__ import annotations

import logging
import os
import shutil
import tempfile

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton, QTableWidget,
                               QTableWidgetItem, QToolButton, QVBoxLayout)

from . import ffmpeg_tools
from .ffmpeg_tools import Cancelled, Cutter
from .i18n import tr
from .segments import fmt_time

LOG = logging.getLogger("clipslicer")
COPY_VCODECS = {"h264", "hevc", "av1", "mpeg4"}   # mp4 에 그대로 담을 수 있는 영상 코덱


def join_plan(items: list[dict]) -> tuple[str, str]:
    """('copy' | 'render', 이유). items: [{path, info, parts:[(a, b)]}]."""
    infos = [it["info"] for it in items]
    first = infos[0]
    for i in infos:
        if i.get("vcodec") not in COPY_VCODECS:
            return "render", tr("mp4 에 그대로 담을 수 없는 코덱 ({0})").format(i.get("vcodec") or "?")
        if (i.get("width"), i.get("height")) != (first.get("width"), first.get("height")):
            return "render", tr("해상도가 다름 ({0}x{1} / {2}x{3})").format(first.get("width"), first.get("height"),
                                                                       i.get("width"), i.get("height"))
        if i.get("vcodec") != first.get("vcodec"):
            return "render", tr("영상 코덱이 다름")
        if abs(float(i.get("fps") or 0) - float(first.get("fps") or 0)) > 0.05:
            return "render", tr("프레임 수(fps)가 다름")
        if bool(i.get("has_audio")) != bool(first.get("has_audio")) or \
                (i.get("has_audio") and i.get("acodec") != first.get("acodec")):
            return "render", tr("소리 형식이 다르거나 소리 없는 영상이 섞임")
    return "copy", tr("규격이 모두 같아 재인코딩 없이 바로 이어 붙입니다 (빠름, 화질 그대로)")


def render_target(items: list[dict]) -> tuple[tuple[int, int], float]:
    """재인코딩 기준: 가장 큰 화면, 가장 높은 fps (최대 60)."""
    best = max((it["info"] for it in items), key=lambda i: (i.get("width") or 0) * (i.get("height") or 0))
    fps = min(60.0, max(float(it["info"].get("fps") or 30.0) for it in items))
    w, h = int(best.get("width") or 1280), int(best.get("height") or 720)
    return (w - w % 2, h - h % 2), fps


def total_duration(items: list[dict]) -> float:
    return sum(b - a for it in items for a, b in it["parts"])


class JoinWorker(QThread):
    progress = Signal(float, str)
    done = Signal(str, str)   # 결과 경로 (실패면 ''), 오류

    def __init__(self, items: list[dict], dst: str, normalize: bool = False, gpu: str | None = None, parent=None):
        super().__init__(parent)
        self.items, self.dst, self.normalize, self.gpu = items, dst, normalize, gpu
        self._cutter: Cutter | None = None
        self._cancel = False

    def cancel(self):
        self._cancel = True
        if self._cutter:
            self._cutter.cancel()

    def run(self):
        cutter = self._cutter = Cutter()
        total = total_duration(self.items)
        plan, why = join_plan(self.items)
        try:
            if plan == "copy":
                try:
                    self.progress.emit(0.0, tr("이어 붙이는 중… (재인코딩 없음)"))
                    # 전체를 넣는 영상은 파일 그대로 (구간 지정 없이), 구간만 넣는 영상은 (파일, 시작, 끝)
                    entries = [it["path"] if self._whole(it) else (it["path"], a, b)
                               for it in self.items for a, b in it["parts"]]
                    cutter.concat(entries, self.dst, lambda p: self.progress.emit(p, tr("이어 붙이는 중…")),
                                  total, normalize=self.normalize)
                    got = ffmpeg_tools.probe(self.dst)["duration"]
                    if abs(got - total) <= max(2.0, total * 0.005):   # 결과 길이가 맞아야 성공
                        self.done.emit(self.dst, "")
                        return
                    LOG.warning("이어 붙인 길이가 다름 (%.1f초, 예상 %.1f초) → 재인코딩으로 다시", got, total)
                    self.progress.emit(0.0, tr("길이가 맞지 않아 재인코딩으로 다시 합니다…"))
                except Cancelled:
                    raise
                except Exception as ex:   # 복사로 안 되는 조합이면 재인코딩으로 다시
                    LOG.warning("이어 붙이기 복사 실패 → 재인코딩으로 다시: %s", ex)
            self._render(cutter, total)
            got = ffmpeg_tools.probe(self.dst)["duration"]
            if abs(got - total) > max(3.0, total * 0.01):
                raise RuntimeError(tr("이어 붙인 결과 길이가 맞지 않습니다 ({0} / 예상 {1})").format(
                    fmt_time(got, ms=False), fmt_time(total, ms=False)))
            self.done.emit(self.dst, "")
        except Cancelled:
            self._remove(self.dst)
            self.done.emit("", tr("취소됨"))
        except Exception as ex:
            LOG.exception("이어 붙이기 실패")
            self._remove(self.dst)
            self.done.emit("", str(ex)[:400])
        finally:
            self._cutter = None

    def _render(self, cutter: Cutter, total: float):
        size, fps = render_target(self.items)
        tmp = tempfile.mkdtemp(prefix="clipslicer_join_")
        try:
            files: list[str] = []
            cut_total = sum(b - a for it in self.items for a, b in it["parts"]
                            if not self._whole(it))
            done = 0.0
            for n, it in enumerate(self.items):
                if self._whole(it):
                    files.append(it["path"])
                    continue
                for k, (a, b) in enumerate(it["parts"]):   # 구간만 넣는 영상은 조각을 먼저 잘라 둔다 (복사)
                    f = os.path.join(tmp, f"{n:03d}_{k:03d}{os.path.splitext(it['path'])[1] or '.mp4'}")
                    span = b - a
                    cutter.cut_copy(it["path"], a, b, f, lambda p, d=done, s=span: self.progress.emit(
                        0.2 * (d + p * s) / max(cut_total, 0.1), tr("구간 자르는 중…")))
                    files.append(f)
                    done += span
            base = 0.2 if cut_total > 0 else 0.0
            self.progress.emit(base, tr("규격을 맞춰 재인코딩하며 이어 붙이는 중… ({0}x{1}, {2:g}fps)").format(size[0], size[1], fps))
            cutter.concat_render(files, self.dst, lambda p: self.progress.emit(base + (1 - base) * p, tr("재인코딩 중…")),
                                 size=size, fps=fps, gpu=self.gpu, normalize=self.normalize)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    @staticmethod
    def _whole(it: dict) -> bool:
        d = float(it["info"].get("duration") or 0)
        return len(it["parts"]) == 1 and it["parts"][0][0] <= 0.01 and it["parts"][0][1] >= d - 0.05

    @staticmethod
    def _remove(p: str):
        try:
            os.remove(p)
        except OSError:
            pass


class JoinDialog(QDialog):
    """순서를 정하고, 영상마다 '전체' 또는 '켜진 구간만' 을 골라 하나로 이어 붙인다."""
    fileReady = Signal(str)

    def __init__(self, parent, paths: list[str], projects: dict | None = None, gpu: str | None = None):
        super().__init__(parent)
        self.setWindowTitle(tr("영상 이어 붙이기"))
        self.resize(760, 460)
        self.projects = projects or {}
        self.gpu = gpu
        self.items: list[dict] = []
        self.worker: JoinWorker | None = None
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(tr("위에서부터 순서대로 이어 붙입니다. 마커로 구간을 나눠 둔 영상은 '켜진 구간만' 을 고를 수 있습니다.")))
        mid = QHBoxLayout()
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([tr("영상"), tr("길이"), tr("규격"), tr("넣을 부분")])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        for c in (1, 2, 3):
            hh.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        mid.addWidget(self.table, 1)
        side = QVBoxLayout()
        for text, tip, fn in (("▲", tr("위로"), lambda: self._move(-1)), ("▼", tr("아래로"), lambda: self._move(1)),
                              (tr("빼기"), tr("목록에서 빼기"), self._remove_row), (tr("추가…"), tr("영상 파일 추가"), self._add_files)):
            b = QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.setMinimumWidth(56)
            b.clicked.connect(fn)
            side.addWidget(b)
        side.addStretch(1)
        mid.addLayout(side)
        lay.addLayout(mid, 1)
        self.lbl_plan = QLabel()
        self.lbl_plan.setWordWrap(True)
        lay.addWidget(self.lbl_plan)
        orow = QHBoxLayout()
        orow.addWidget(QLabel(tr("저장")))
        self.ed_out = QLineEdit()
        orow.addWidget(self.ed_out, 1)
        b = QToolButton()
        b.setText("…")
        b.clicked.connect(self._choose_out)
        orow.addWidget(b)
        self.cb_norm = QCheckBox(tr("음량 정규화"))
        self.cb_norm.setToolTip(tr("영상마다 다른 소리 크기를 -14 LUFS 로 고르게 (소리만 다시 인코딩)"))
        orow.addWidget(self.cb_norm)
        lay.addLayout(orow)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setFormat(tr("대기 중"))
        lay.addWidget(self.progress)
        brow = QHBoxLayout()
        brow.addStretch(1)
        self.b_go = QPushButton(tr("이어 붙이기"))
        self.b_go.setDefault(True)
        self.b_go.clicked.connect(self._start)
        self.b_close = QPushButton(tr("닫기"))
        self.b_close.clicked.connect(self._close)
        brow.addWidget(self.b_go)
        brow.addWidget(self.b_close)
        lay.addLayout(brow)
        for p in paths:
            self._append(p)
        self._refresh()

    # ---- 목록 ----
    def _append(self, path: str) -> bool:
        path = os.path.abspath(path)
        proj = self.projects.get(path)
        try:
            info = proj.info if proj is not None and getattr(proj, "info", None) else ffmpeg_tools.probe(path)
        except Exception as ex:
            QMessageBox.warning(self, tr("영상 이어 붙이기"), tr("열 수 없는 파일입니다: {0}\n{1}").format(os.path.basename(path), ex))
            return False
        if not info.get("duration") or not info.get("width"):
            QMessageBox.warning(self, tr("영상 이어 붙이기"), tr("영상이 아니거나 길이를 알 수 없습니다: {0}").format(os.path.basename(path)))
            return False
        segs = []
        if proj is not None and proj.markers:
            segs = [(s.start, s.end) for _, s in proj.ordered_enabled()]
        self.items.append({"path": path, "info": info, "segs": segs, "use_segs": False,
                           "parts": [(0.0, float(info["duration"]))]})
        return True

    def _refresh(self):
        self.table.setRowCount(0)
        for r, it in enumerate(self.items):
            self.table.insertRow(r)
            i = it["info"]
            name = QTableWidgetItem(os.path.basename(it["path"]))
            name.setToolTip(it["path"])
            self.table.setItem(r, 0, name)
            self.table.setItem(r, 1, QTableWidgetItem(fmt_time(sum(b - a for a, b in it["parts"]), ms=False)))
            spec = f"{i.get('width')}x{i.get('height')} {float(i.get('fps') or 0):g}fps {i.get('vcodec')}" + \
                   ("" if i.get("has_audio") else tr(" (소리 없음)"))
            self.table.setItem(r, 2, QTableWidgetItem(spec))
            cb = QComboBox()
            cb.addItem(tr("전체"), False)
            if it["segs"]:
                cb.addItem(tr("켜진 구간 {0}개").format(len(it["segs"])), True)
            cb.setCurrentIndex(1 if it["use_segs"] and it["segs"] else 0)
            cb.currentIndexChanged.connect(lambda _i, r=r, cb=cb: self._set_use_segs(r, bool(cb.currentData())))
            self.table.setCellWidget(r, 3, cb)
        if self.items and not self.ed_out.text().strip():
            first = self.items[0]["path"]
            self.ed_out.setText(_unique(os.path.join(os.path.dirname(first),
                                                     os.path.splitext(os.path.basename(first))[0] + "_joined.mp4")))
        self._update_plan()

    def _set_use_segs(self, row: int, on: bool):
        it = self.items[row]
        it["use_segs"] = on and bool(it["segs"])
        it["parts"] = list(it["segs"]) if it["use_segs"] else [(0.0, float(it["info"]["duration"]))]
        self.table.item(row, 1).setText(fmt_time(sum(b - a for a, b in it["parts"]), ms=False))
        self._update_plan()

    def _update_plan(self):
        ok = len(self.items) >= 2
        self.b_go.setEnabled(ok and self.worker is None)
        if not ok:
            self.lbl_plan.setText(tr("이어 붙일 영상을 2개 이상 넣어 주세요 ('추가…')."))
            return
        plan, why = join_plan(self.items)
        total = fmt_time(total_duration(self.items), ms=False)
        if plan == "copy":
            self.lbl_plan.setText(tr("✓ {0}\n합친 길이 {1}").format(why, total))
        else:
            (w, h), fps = render_target(self.items)
            self.lbl_plan.setText(tr("↻ {0} → {1}x{2} {3:g}fps 로 맞춰 재인코딩합니다 (시간이 걸림).\n합친 길이 {4}").format(
                why, w, h, fps, total))

    def _move(self, d: int):
        r = self.table.currentRow()
        if r < 0 or not (0 <= r + d < len(self.items)):
            return
        self.items[r], self.items[r + d] = self.items[r + d], self.items[r]
        self._refresh()
        self.table.selectRow(r + d)

    def _remove_row(self):
        r = self.table.currentRow()
        if 0 <= r < len(self.items):
            del self.items[r]
            self._refresh()

    def _add_files(self):
        start = os.path.dirname(self.items[-1]["path"]) if self.items else ""
        paths, _ = QFileDialog.getOpenFileNames(self, tr("이어 붙일 영상"), start,
                                                tr("영상 (*.mp4 *.mkv *.mov *.ts *.webm *.flv *.avi *.m4v);;모든 파일 (*)"))
        if any([self._append(p) for p in paths]):
            self._refresh()

    def _choose_out(self):
        p, _ = QFileDialog.getSaveFileName(self, tr("저장할 파일"), self.ed_out.text(), "MP4 (*.mp4)")
        if p:
            self.ed_out.setText(p if p.lower().endswith(".mp4") else p + ".mp4")

    # ---- 실행 ----
    def _start(self):
        dst = self.ed_out.text().strip()
        if not dst:
            return
        if not dst.lower().endswith(".mp4"):
            dst += ".mp4"
        if any(os.path.normcase(os.path.abspath(dst)) == os.path.normcase(it["path"]) for it in self.items):
            QMessageBox.warning(self, tr("영상 이어 붙이기"), tr("넣은 영상과 같은 이름으로는 저장할 수 없습니다."))
            return
        if os.path.exists(dst) and QMessageBox.question(self, tr("영상 이어 붙이기"),
                                                        tr("{0} 이(가) 이미 있습니다. 덮어쓸까요?").format(os.path.basename(dst))) != QMessageBox.Yes:
            return
        os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
        self.worker = JoinWorker([dict(it) for it in self.items], dst, self.cb_norm.isChecked(), self.gpu, self)
        self.worker.progress.connect(lambda p, t: (self.progress.setValue(int(p * 1000)), self.progress.setFormat(f"%p%  {t}")))
        self.worker.done.connect(self._on_done)
        self.b_go.setEnabled(False)
        self.b_close.setText(tr("취소"))
        self.table.setEnabled(False)
        LOG.info("이어 붙이기 시작: %d개 → %s (%s)", len(self.items), dst, join_plan(self.items)[0])
        self.worker.start()

    def _on_done(self, path: str, error: str):
        self.worker = None
        self.b_close.setText(tr("닫기"))
        self.table.setEnabled(True)
        if path:
            self.progress.setValue(1000)
            self.progress.setFormat(tr("완료"))
            self.fileReady.emit(path)
            self.accept()
        else:
            self.progress.setValue(0)
            self.progress.setFormat(tr("실패") if error != tr("취소됨") else tr("취소됨"))
            self._update_plan()
            if error != tr("취소됨"):
                QMessageBox.warning(self, tr("영상 이어 붙이기"), tr("이어 붙이지 못했습니다:\n{0}").format(error))

    def _close(self):
        if self.worker is not None:
            self.worker.cancel()
            self.worker.wait(5000)
            return
        self.reject()

    def reject(self):
        if self.worker is not None:   # 작업 중 Esc / 창 닫기 → 취소부터
            self.worker.cancel()
            self.worker.wait(5000)
        super().reject()


def _unique(path: str) -> str:
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    n = 2
    while os.path.exists(f"{base}_{n}{ext}"):
        n += 1
    return f"{base}_{n}{ext}"
