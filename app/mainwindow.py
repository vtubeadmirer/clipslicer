"""메인 창."""
from __future__ import annotations

import os
import subprocess

from PySide6.QtCore import Qt, QSettings, QTimer
from PySide6.QtGui import QAction, QKeySequence, QPixmap, QShortcut, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QTableWidget, QTableWidgetItem, QHeaderView, QLineEdit, QRadioButton,
    QProgressBar, QFileDialog, QMessageBox, QGroupBox, QPlainTextEdit, QCheckBox, QAbstractItemView,
    QToolButton, QStyle, QSizePolicy, QApplication,
)

from . import __version__, ffmpeg_tools
from .player import MpvWidget
from .segments import ClipProject, fmt_time
from .timeline import TimelineWidget
from .workers import AnalyzeWorker, ExportWorker, ExportJob

VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".ts", ".m4v", ".wmv", ".flv", ".mpg", ".mpeg", ".m2ts", ".mts"}
COL_USE, COL_NO, COL_START, COL_END, COL_DUR, COL_NAME = range(6)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"ClipSlicer {__version__}")
        self.resize(1280, 760)
        self.setAcceptDrops(True)
        self.settings = QSettings("ClipSlicer", "ClipSlicer")

        self.projects: dict[str, ClipProject] = {}
        self.current: ClipProject | None = None
        self.workers: dict[str, AnalyzeWorker] = {}
        self.export_worker: ExportWorker | None = None
        self.loop_idx = -1
        self._table_updating = False

        self._build_ui()
        self._build_shortcuts()
        self._restore_settings()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        root = QSplitter(Qt.Horizontal, self)
        self.setCentralWidget(root)

        # ---- 왼쪽: 파일 목록 ----
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(6, 6, 6, 6)
        self.file_list = QListWidget()
        self.file_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.file_list.currentRowChanged.connect(self._on_file_selected)
        lv.addWidget(QLabel("영상 목록"))
        lv.addWidget(self.file_list, 1)
        fb = QHBoxLayout()
        btn_add = QPushButton("＋ 영상 추가")
        btn_add.clicked.connect(self.open_files)
        btn_rm = QPushButton("－ 제거")
        btn_rm.clicked.connect(self.remove_current_file)
        fb.addWidget(btn_add)
        fb.addWidget(btn_rm)
        lv.addLayout(fb)
        root.addWidget(left)

        # ---- 가운데: 플레이어 + 타임라인 + 컨트롤 ----
        center = QWidget()
        cv = QVBoxLayout(center)
        cv.setContentsMargins(0, 6, 0, 6)
        cv.setSpacing(4)
        self.player = MpvWidget()
        self.player.positionChanged.connect(self._on_position)
        self.player.durationChanged.connect(self._on_duration)
        self.player.pauseChanged.connect(self._on_pause_changed)
        self.player.fileLoaded.connect(self._on_file_loaded)
        self.player.clicked.connect(self.player.toggle_pause)
        cv.addWidget(self.player, 1)

        self.timeline = TimelineWidget()
        self.timeline.seekRequested.connect(self._on_seek_requested)
        self.timeline.markerMoved.connect(self._on_marker_moved)
        self.timeline.markerDeleted.connect(self._on_marker_deleted)
        self.timeline.segmentToggled.connect(self.toggle_segment)
        self.timeline.segmentLoopRequested.connect(self.toggle_loop_segment)
        self.timeline.addMarkerRequested.connect(self._add_marker_at)
        cv.addWidget(self.timeline)

        ctl = QHBoxLayout()
        ctl.setContentsMargins(6, 0, 6, 0)
        self.lbl_time = QLabel("00:00.000 / 00:00.000")
        self.lbl_time.setMinimumWidth(170)
        self.lbl_time.setStyleSheet("font-family: Consolas, monospace; font-size: 13px;")
        ctl.addWidget(self.lbl_time)

        def tb(text, tip, fn):
            b = QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.setAutoRaise(True)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(fn)
            ctl.addWidget(b)
            return b

        tb("⏮", "10초 뒤로 (Ctrl+←)", lambda: self.player.seek_relative(-10))
        tb("◀◀", "1초 뒤로 (Shift+←)", lambda: self.player.seek_relative(-1))
        tb("◀", "한 프레임 뒤로 (←)", lambda: self.player.frame_step(False))
        self.btn_play = tb("▶", "재생/정지 (Space)", self.player.toggle_pause)
        self.btn_play.setStyleSheet("font-size: 16px; min-width: 36px;")
        tb("▶", "한 프레임 앞으로 (→)", lambda: self.player.frame_step(True))
        tb("▶▶", "1초 앞으로 (Shift+→)", lambda: self.player.seek_relative(1))
        tb("⏭", "10초 앞으로 (Ctrl+→)", lambda: self.player.seek_relative(10))
        ctl.addStretch(1)
        self.btn_cut = QPushButton("✂  여기서 자르기  (S)")
        self.btn_cut.setFocusPolicy(Qt.NoFocus)
        self.btn_cut.setStyleSheet("font-weight: bold; padding: 6px 14px;")
        self.btn_cut.clicked.connect(self.add_marker_here)
        ctl.addWidget(self.btn_cut)
        self.btn_loop = QPushButton("🔁 구간 반복 (L)")
        self.btn_loop.setCheckable(True)
        self.btn_loop.setFocusPolicy(Qt.NoFocus)
        self.btn_loop.clicked.connect(self._on_loop_button)
        ctl.addWidget(self.btn_loop)
        cv.addLayout(ctl)

        hint = QLabel("타임라인: 클릭=이동 · 우클릭=마커 추가/삭제 · 마커 드래그=이동 · Ctrl+클릭=구간 켜기/끄기 · 더블클릭=구간 반복")
        hint.setStyleSheet("color: #888; font-size: 11px; padding-left: 6px;")
        cv.addWidget(hint)
        root.addWidget(center)

        # ---- 오른쪽: 구간 목록 + 내보내기 ----
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(6, 6, 6, 6)
        head = QHBoxLayout()
        head.addWidget(QLabel("구간 목록"))
        head.addStretch(1)
        btn_clear = QPushButton("마커 모두 지우기")
        btn_clear.setFocusPolicy(Qt.NoFocus)
        btn_clear.clicked.connect(self.clear_markers)
        head.addWidget(btn_clear)
        rv.addLayout(head)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["사용", "#", "시작", "끝", "길이", "파일명"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(COL_NAME, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.table.setFocusPolicy(Qt.ClickFocus)
        self.table.itemChanged.connect(self._on_table_item_changed)
        self.table.cellClicked.connect(self._on_table_cell_clicked)
        self.table.cellDoubleClicked.connect(self._on_table_cell_double_clicked)
        rv.addWidget(self.table, 1)

        grp = QGroupBox("내보내기")
        gv = QVBoxLayout(grp)
        outrow = QHBoxLayout()
        self.ed_outdir = QLineEdit()
        self.ed_outdir.setPlaceholderText("비워 두면 원본 옆 '<이름>_cuts' 폴더")
        btn_out = QToolButton()
        btn_out.setText("…")
        btn_out.clicked.connect(self.choose_outdir)
        outrow.addWidget(QLabel("폴더"))
        outrow.addWidget(self.ed_outdir, 1)
        outrow.addWidget(btn_out)
        gv.addLayout(outrow)
        moderow = QHBoxLayout()
        self.rb_fast = QRadioButton("빠르게 (무손실, 키프레임 단위)")
        self.rb_precise = QRadioButton("정확하게 (재인코딩, 느림)")
        self.rb_fast.setChecked(True)
        moderow.addWidget(self.rb_fast)
        moderow.addWidget(self.rb_precise)
        gv.addLayout(moderow)
        self.cb_open = QCheckBox("완료 후 폴더 열기")
        self.cb_open.setChecked(True)
        gv.addWidget(self.cb_open)
        btnrow = QHBoxLayout()
        self.btn_export_cur = QPushButton("현재 영상 내보내기")
        self.btn_export_cur.clicked.connect(lambda: self.start_export(all_files=False))
        self.btn_export_all = QPushButton("모든 영상 내보내기 (Ctrl+E)")
        self.btn_export_all.setStyleSheet("font-weight: bold;")
        self.btn_export_all.clicked.connect(lambda: self.start_export(all_files=True))
        self.btn_cancel = QPushButton("취소")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self.cancel_export)
        for b in (self.btn_export_cur, self.btn_export_all, self.btn_cancel):
            b.setFocusPolicy(Qt.NoFocus)
            btnrow.addWidget(b)
        gv.addLayout(btnrow)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        gv.addWidget(self.progress)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(110)
        self.log.setStyleSheet("font-size: 11px;")
        gv.addWidget(self.log)
        rv.addWidget(grp)
        root.addWidget(right)

        root.setStretchFactor(0, 0)
        root.setStretchFactor(1, 1)
        root.setStretchFactor(2, 0)
        root.setSizes([200, 760, 340])
        self.splitter = root

        # 메뉴
        m = self.menuBar().addMenu("파일")
        a_open = QAction("영상 열기…", self)
        a_open.setShortcut(QKeySequence.Open)
        a_open.triggered.connect(self.open_files)
        m.addAction(a_open)
        m.addSeparator()
        a_quit = QAction("종료", self)
        a_quit.triggered.connect(self.close)
        m.addAction(a_quit)
        h = self.menuBar().addMenu("도움말")
        a_keys = QAction("단축키", self)
        a_keys.triggered.connect(self.show_keys)
        h.addAction(a_keys)

        self.statusBar().showMessage("영상을 끌어다 놓거나 Ctrl+O 로 열어 주세요")

    def _build_shortcuts(self):
        def sc(keys, fn):
            s = QShortcut(QKeySequence(keys), self)
            s.setContext(Qt.ApplicationShortcut)
            s.activated.connect(fn)

        sc("Space", self.player.toggle_pause)
        sc("K", self.player.toggle_pause)
        sc("Left", lambda: self.player.frame_step(False))
        sc("Right", lambda: self.player.frame_step(True))
        sc("Shift+Left", lambda: self.player.seek_relative(-1))
        sc("Shift+Right", lambda: self.player.seek_relative(1))
        sc("Ctrl+Left", lambda: self.player.seek_relative(-10))
        sc("Ctrl+Right", lambda: self.player.seek_relative(10))
        sc("J", lambda: self.player.seek_relative(-5))
        sc("Home", lambda: self.player.seek(0))
        sc("End", lambda: self.player.seek(self.player.duration))
        sc("S", self.add_marker_here)
        sc("Delete", self.delete_nearest_marker)
        sc("L", self._on_loop_shortcut)
        sc("Ctrl+E", lambda: self.start_export(all_files=True))
        sc("Up", self._jump_segment_prev)
        sc("Down", self._jump_segment_next)
        sc("Ctrl+Up", lambda: self._select_file_offset(-1))
        sc("Ctrl+Down", lambda: self._select_file_offset(1))

    def show_keys(self):
        QMessageBox.information(self, "단축키", (
            "Space / K      재생·정지\n"
            "← →            한 프레임 이동\n"
            "Shift+← →      1초 이동\n"
            "Ctrl+← →       10초 이동\n"
            "J              5초 뒤로\n"
            "Home / End     처음 / 끝\n"
            "S              현재 위치에 자르기 마커\n"
            "Delete         가까운 마커 삭제\n"
            "L              현재 구간 반복 켜기/끄기\n"
            "↑ ↓            이전 / 다음 구간 시작으로\n"
            "Ctrl+↑ ↓       이전 / 다음 영상\n"
            "Ctrl+O         영상 열기\n"
            "Ctrl+E         모든 영상 내보내기\n"
        ))

    # ------------------------------------------------------------ 설정
    def _restore_settings(self):
        self.ed_outdir.setText(self.settings.value("out_dir", ""))
        if self.settings.value("precise", "0") == "1":
            self.rb_precise.setChecked(True)
        self.cb_open.setChecked(self.settings.value("open_after", "1") == "1")
        geo = self.settings.value("geometry")
        if geo:
            self.restoreGeometry(geo)
        sizes = self.settings.value("splitter")
        if sizes:
            try:
                self.splitter.setSizes([int(s) for s in sizes])
            except (TypeError, ValueError):
                pass

    def _save_settings(self):
        self.settings.setValue("out_dir", self.ed_outdir.text())
        self.settings.setValue("precise", "1" if self.rb_precise.isChecked() else "0")
        self.settings.setValue("open_after", "1" if self.cb_open.isChecked() else "0")
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("splitter", self.splitter.sizes())

    def closeEvent(self, e):
        if self.export_worker and self.export_worker.isRunning():
            if QMessageBox.question(self, "종료", "내보내기가 진행 중입니다. 취소하고 종료할까요?") != QMessageBox.Yes:
                e.ignore()
                return
            self.export_worker.cancel()
            self.export_worker.wait(3000)
        self._save_settings()
        for w in self.workers.values():
            if w.isRunning():
                w.wait(2000)
        self.player.shutdown()
        super().closeEvent(e)

    # ------------------------------------------------------------ 파일
    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e: QDropEvent):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        self.add_files(paths)

    def open_files(self):
        start = self.settings.value("last_dir", "")
        exts = " ".join(f"*{x}" for x in sorted(VIDEO_EXTS))
        paths, _ = QFileDialog.getOpenFileNames(self, "영상 열기", start, f"영상 파일 ({exts});;모든 파일 (*.*)")
        if paths:
            self.settings.setValue("last_dir", os.path.dirname(paths[0]))
            self.add_files(paths)

    def add_files(self, paths: list[str]):
        added = None
        for p in paths:
            if os.path.isdir(p):
                for name in sorted(os.listdir(p)):
                    if os.path.splitext(name)[1].lower() in VIDEO_EXTS:
                        added = self._add_file(os.path.join(p, name)) or added
                continue
            added = self._add_file(p) or added
        if added is not None:
            row = list(self.projects.keys()).index(added)
            self.file_list.setCurrentRow(row)

    def _add_file(self, path: str) -> str | None:
        path = os.path.abspath(path)
        if path in self.projects:
            return path
        try:
            info = ffmpeg_tools.probe(path)
        except Exception as ex:
            self._log(f"열기 실패: {os.path.basename(path)} — {ex}")
            return None
        if info["duration"] <= 0:
            self._log(f"길이를 알 수 없음: {os.path.basename(path)}")
            return None
        proj = ClipProject(path=path, duration=info["duration"], fps=info["fps"],
                           width=info["width"], height=info["height"])
        proj.rebuild_segments()
        self.projects[path] = proj
        item = QListWidgetItem(os.path.basename(path))
        item.setToolTip(f"{path}\n{info['width']}x{info['height']}  {info['fps']:.2f}fps  {fmt_time(info['duration'])}")
        item.setData(Qt.UserRole, path)
        self.file_list.addItem(item)
        self._start_analyze(proj)
        return path

    def _start_analyze(self, proj: ClipProject):
        w = AnalyzeWorker(proj.path, proj.duration, self)
        w.thumbsReady.connect(self._on_thumbs_ready)
        w.waveformReady.connect(self._on_waveform_ready)
        w.finished.connect(lambda p=proj.path: self.workers.pop(p, None))
        self.workers[proj.path] = w
        w.start()

    def _on_thumbs_ready(self, path: str, thumbs: list):
        proj = self.projects.get(path)
        if not proj:
            return
        out = []
        for t, data in thumbs:
            pix = QPixmap()
            if pix.loadFromData(data, "JPEG"):
                out.append((t, pix))
        proj.thumbs = out
        if proj is self.current:
            self.timeline.update()

    def _on_waveform_ready(self, path: str, wave):
        proj = self.projects.get(path)
        if not proj:
            return
        proj.waveform = wave
        if proj is self.current:
            self.timeline.update()

    def remove_current_file(self):
        row = self.file_list.currentRow()
        if row < 0:
            return
        item = self.file_list.takeItem(row)
        path = item.data(Qt.UserRole)
        self.projects.pop(path, None)
        if self.current and self.current.path == path:
            self.current = None
            self.player.unload()
            self.timeline.set_project(None)
            self._refresh_table()
            self._update_time_label(0)
        if self.file_list.count() == 0:
            self.file_list.setCurrentRow(-1)

    def _select_file_offset(self, d: int):
        n = self.file_list.count()
        if n == 0:
            return
        row = (self.file_list.currentRow() + d) % n
        self.file_list.setCurrentRow(row)

    def _on_file_selected(self, row: int):
        if row < 0:
            return
        path = self.file_list.item(row).data(Qt.UserRole)
        proj = self.projects.get(path)
        if not proj or proj is self.current:
            return
        if self.current:
            self.current.last_position = self.player.position
        self._set_loop(-1)
        self.current = proj
        self.player.load(path)
        self.timeline.set_project(proj)
        self._refresh_table()
        self.setWindowTitle(f"ClipSlicer {__version__} — {os.path.basename(path)}")
        self.statusBar().showMessage(f"{proj.width}x{proj.height}  {proj.fps:.2f}fps  {fmt_time(proj.duration)}")

    def _on_file_loaded(self):
        if self.current and self.current.last_position > 0:
            self.player.seek(self.current.last_position)

    # ------------------------------------------------------------ 재생 상태
    def _on_position(self, t: float):
        self.timeline.set_position(t)
        self._update_time_label(t)

    def _on_duration(self, d: float):
        if self.current and d > 0 and abs(self.current.duration - d) > 0.5:
            # ffprobe 와 mpv 길이가 다르면 mpv 기준으로 보정
            self.current.duration = d
            self.current.rebuild_segments()
            self.timeline.update()
            self._refresh_table()

    def _on_pause_changed(self, paused: bool):
        self.btn_play.setText("▶" if paused else "⏸")

    def _update_time_label(self, t: float):
        dur = self.current.duration if self.current else 0.0
        self.lbl_time.setText(f"{fmt_time(t)} / {fmt_time(dur)}")

    def _on_seek_requested(self, t: float, final: bool):
        self.player.seek(t, exact=final)

    def _snap(self, t: float) -> float:
        fps = self.current.fps if self.current and self.current.fps > 0 else 30.0
        return round(t * fps) / fps

    # ------------------------------------------------------------ 마커 / 구간
    def add_marker_here(self):
        if not self.current:
            return
        self.player.pause()
        self._add_marker_at(self.player.position)

    def _add_marker_at(self, t: float):
        if not self.current:
            return
        if self.current.add_marker(self._snap(t)):
            self._set_loop(-1)
            self._after_segments_changed()
            self.statusBar().showMessage(f"마커 추가: {fmt_time(t)}", 3000)

    def delete_nearest_marker(self):
        if not self.current or not self.current.markers:
            return
        tol = max(self.current.duration * 0.02, 0.5)
        idx = self.current.nearest_marker(self.player.position, tol)
        if idx < 0:
            idx = min(range(len(self.current.markers)),
                      key=lambda i: abs(self.current.markers[i] - self.player.position))
        self._on_marker_deleted(idx)

    def _on_marker_deleted(self, idx: int):
        if not self.current:
            return
        self.current.remove_marker(idx)
        self._set_loop(-1)
        self._after_segments_changed()

    def _on_marker_moved(self, idx: int, t: float):
        if not self.current:
            return
        self.current.move_marker(idx, self._snap(t))
        self._set_loop(-1)
        self._after_segments_changed()

    def clear_markers(self):
        if not self.current or not self.current.markers:
            return
        if QMessageBox.question(self, "마커 지우기", "이 영상의 마커를 모두 지울까요?") == QMessageBox.Yes:
            self.current.clear_markers()
            self._set_loop(-1)
            self._after_segments_changed()

    def toggle_segment(self, idx: int):
        if not self.current or not (0 <= idx < len(self.current.segments)):
            return
        seg = self.current.segments[idx]
        seg.enabled = not seg.enabled
        self._after_segments_changed()

    def _after_segments_changed(self):
        self.timeline.update()
        self._refresh_table()

    def _jump_segment_prev(self):
        if not self.current:
            return
        starts = [s.start for s in self.current.segments]
        pos = self.player.position
        prev = [s for s in starts if s < pos - 0.3]
        self.player.seek(prev[-1] if prev else 0.0)

    def _jump_segment_next(self):
        if not self.current:
            return
        starts = [s.start for s in self.current.segments]
        pos = self.player.position
        nxt = [s for s in starts if s > pos + 0.01]
        if nxt:
            self.player.seek(nxt[0])

    # ---- 구간 반복 ----
    def _set_loop(self, idx: int):
        self.loop_idx = idx
        if idx < 0 or not self.current or idx >= len(self.current.segments):
            self.loop_idx = -1
            self.player.set_loop(None, None)
        else:
            seg = self.current.segments[idx]
            self.player.set_loop(seg.start, seg.end)
        self.timeline.set_loop_segment(self.loop_idx)
        self.btn_loop.setChecked(self.loop_idx >= 0)

    def toggle_loop_segment(self, idx: int):
        if self.loop_idx == idx:
            self._set_loop(-1)
            return
        self._set_loop(idx)
        if self.loop_idx >= 0:
            seg = self.current.segments[idx]
            self.player.seek(seg.start)
            if self.player.paused:
                self.player.toggle_pause()

    def _on_loop_shortcut(self):
        if not self.current:
            return
        if self.loop_idx >= 0:
            self._set_loop(-1)
        else:
            self.toggle_loop_segment(self.current.segment_at(self.player.position))

    def _on_loop_button(self, checked: bool):
        if not self.current:
            self.btn_loop.setChecked(False)
            return
        if checked:
            self.toggle_loop_segment(self.current.segment_at(self.player.position))
        else:
            self._set_loop(-1)

    # ---- 테이블 ----
    def _refresh_table(self):
        self._table_updating = True
        self.table.setRowCount(0)
        if self.current:
            ext = ".mp4" if self.rb_precise.isChecked() else self.current.ext
            for i, s in enumerate(self.current.segments):
                self.table.insertRow(i)
                use = QTableWidgetItem()
                use.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                use.setCheckState(Qt.Checked if s.enabled else Qt.Unchecked)
                self.table.setItem(i, COL_USE, use)
                for col, text in ((COL_NO, str(i + 1)), (COL_START, fmt_time(s.start)),
                                  (COL_END, fmt_time(s.end)), (COL_DUR, fmt_time(s.duration))):
                    it = QTableWidgetItem(text)
                    it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                    if col != COL_NO:
                        it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    self.table.setItem(i, col, it)
                name = QTableWidgetItem(s.name or self.current.output_name(i, ext))
                name.setToolTip("더블클릭해서 파일명 변경")
                if not s.name:
                    name.setForeground(Qt.gray)
                self.table.setItem(i, COL_NAME, name)
                if not s.enabled:
                    for c in range(6):
                        self.table.item(i, c).setForeground(Qt.darkGray)
        self._table_updating = False

    def _on_table_item_changed(self, item: QTableWidgetItem):
        if self._table_updating or not self.current:
            return
        row = item.row()
        if row >= len(self.current.segments):
            return
        seg = self.current.segments[row]
        if item.column() == COL_USE:
            seg.enabled = item.checkState() == Qt.Checked
            self._after_segments_changed()
        elif item.column() == COL_NAME:
            text = os.path.splitext(item.text().strip())[0]
            auto = os.path.splitext(self.current.output_name(row, ""))[0]
            seg.name = "" if text in ("", auto) else text
            self._refresh_table()
        self.setFocus()

    def _on_table_cell_clicked(self, row: int, col: int):
        if self.current and 0 <= row < len(self.current.segments) and col != COL_USE:
            self.player.seek(self.current.segments[row].start)

    def _on_table_cell_double_clicked(self, row: int, col: int):
        if col != COL_NAME and self.current and 0 <= row < len(self.current.segments):
            self.toggle_loop_segment(row)

    # ------------------------------------------------------------ 내보내기
    def choose_outdir(self):
        d = QFileDialog.getExistingDirectory(self, "출력 폴더", self.ed_outdir.text() or "")
        if d:
            self.ed_outdir.setText(d)

    def _out_dir_for(self, proj: ClipProject) -> str:
        custom = self.ed_outdir.text().strip()
        if custom:
            return custom
        return os.path.join(os.path.dirname(proj.path), f"{proj.stem}_cuts")

    def start_export(self, all_files: bool):
        if self.export_worker and self.export_worker.isRunning():
            return
        projects = list(self.projects.values()) if all_files else ([self.current] if self.current else [])
        precise = self.rb_precise.isChecked()
        jobs: list[ExportJob] = []
        for proj in projects:
            if proj is None:
                continue
            ext = ".mp4" if precise else proj.ext
            outdir = self._out_dir_for(proj)
            for i, seg in proj.enabled_segments():
                dst = os.path.join(outdir, proj.output_name(i, ext))
                if os.path.abspath(dst) == os.path.abspath(proj.path):
                    dst = os.path.join(outdir, f"{proj.stem}_cut{ext}")
                jobs.append(ExportJob(proj.path, seg.start, seg.end, dst, precise))
        if not jobs:
            QMessageBox.information(self, "내보내기", "내보낼 구간이 없습니다.")
            return
        self.player.pause()
        self.log.clear()
        self._log(f"{len(jobs)}개 구간 내보내기 시작 ({'정확하게' if precise else '빠르게'})")
        self.progress.setValue(0)
        self.progress.setFormat("%p%")
        self._set_export_running(True)
        self._job_total = len(jobs)
        self._export_dirs = sorted({os.path.dirname(j.dst) for j in jobs})
        self.export_worker = ExportWorker(jobs, self)
        self.export_worker.jobStarted.connect(self._on_job_started)
        self.export_worker.jobProgress.connect(self._on_job_progress)
        self.export_worker.jobFinished.connect(self._on_job_finished)
        self.export_worker.allFinished.connect(self._on_export_finished)
        self.export_worker.start()

    def cancel_export(self):
        if self.export_worker:
            self.export_worker.cancel()
            self._log("취소 요청…")

    def _set_export_running(self, running: bool):
        self.btn_export_cur.setEnabled(not running)
        self.btn_export_all.setEnabled(not running)
        self.btn_cancel.setEnabled(running)

    def _on_job_started(self, i: int, label: str):
        self.progress.setFormat(f"[{i + 1}/{self._job_total}] {label}  %p%")

    def _on_job_progress(self, i: int, frac: float):
        total = (i + frac) / self._job_total
        self.progress.setValue(int(total * 1000))

    def _on_job_finished(self, i: int, ok: bool, msg: str):
        label = self.export_worker.jobs[i].label if self.export_worker else str(i)
        self._log(("✔ " if ok else "✖ ") + label + ("" if ok else f"\n   {msg}"))

    def _on_export_finished(self, ok_n: int, fail_n: int):
        self._set_export_running(False)
        self.progress.setValue(1000 if fail_n == 0 else self.progress.value())
        self.progress.setFormat(f"완료: 성공 {ok_n}, 실패 {fail_n}")
        self._log(f"완료 — 성공 {ok_n}, 실패 {fail_n}")
        if self.cb_open.isChecked() and ok_n and self._export_dirs:
            for d in self._export_dirs[:3]:
                try:
                    os.startfile(d)
                except OSError:
                    subprocess.Popen(["explorer", d])

    def _log(self, text: str):
        self.log.appendPlainText(text)
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())
