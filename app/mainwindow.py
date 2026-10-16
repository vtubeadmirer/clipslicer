"""메인 창."""
from __future__ import annotations

from .i18n import tr
import os
import subprocess

from PySide6.QtCore import Qt, QSettings, QTimer, Signal
from PySide6.QtGui import QAction, QKeySequence, QPixmap, QShortcut, QDragEnterEvent, QDropEvent, QColor, QBrush
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QTableWidget, QTableWidgetItem, QHeaderView, QLineEdit, QRadioButton,
    QProgressBar, QFileDialog, QMessageBox, QGroupBox, QPlainTextEdit, QCheckBox, QAbstractItemView,
    QToolButton, QSlider, QComboBox, QStackedWidget, QMenu, QSizePolicy, QStyle, QApplication,
    QScrollArea, QFrame,
)

from . import __version__, ffmpeg_tools
import logging

from .paths import make_settings
from .logging_setup import log_dir
from . import updater
from . import i18n
from . import youtube as yt
from .youtube_ui import ConnectDialog, UploadDialog, make_items
from .dialogs import (SilenceDialog, PatternDialog, ask_overwrite, SceneDialog, TimestampDialog, CropDialog, DownloadDialog,
                      UpdateDialog, RenderAssetsDialog, LoudDialog)
from .help import HelpDialog
from .player import MpvWidget
from .segments import ClipProject, fmt_time, parse_time, DEFAULT_PATTERN, fmt_time_file, loud_peaks
from .timeline import TimelineWidget, seg_color
from .workers import AnalyzeWorker, ExportWorker, ExportJob, ExportPart, SilenceWorker, GpuDetectWorker, SceneWorker, DownloadWorker
from . import bookmarks
from .bookmarks import BookmarkWindow
from .notify import Notifier
from .startpanel import StartPanel
from .firstrun import FirstRunDialog, SampleWorker, sample_path
from .chat import ChatDialog, ChatData, DEFAULT_KEYWORDS
from .upload_history import HistoryDialog
from . import discord

VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".ts", ".m4v", ".wmv", ".flv", ".mpg", ".mpeg", ".m2ts", ".mts"}
COL_USE, COL_NO, COL_ORDER, COL_START, COL_END, COL_DUR, COL_NAME, COL_NOTE = range(8)
SPEEDS = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 4.0]
MAX_RECENT = 10
LOG = logging.getLogger("clipslicer")


class TimeEdit(QLineEdit):
    """클릭하면 시각을 입력해서 이동할 수 있는 시간 표시."""
    seekTo = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFrame(False)
        self.setCursor(Qt.IBeamCursor)
        self.setToolTip(tr("클릭해서 시각 입력 (예: 1:23.5, 01:02:03, 83.5, 1h2m3s)"))
        self.setFixedWidth(190)
        self.setStyleSheet("font-family: Consolas, monospace; font-size: 13px; background: transparent;")
        self._pos = 0.0
        self._dur = 0.0
        self._editing = False
        self.returnPressed.connect(self._commit)

    def set_times(self, pos: float, dur: float):
        self._pos, self._dur = pos, dur
        if not self._editing:
            self.setText(f"{fmt_time(pos)} / {fmt_time(dur)}")

    def mousePressEvent(self, e):
        if not self._editing:
            self._editing = True
            self.setReadOnly(False)
            self.setText(fmt_time(self._pos))
            self.selectAll()
            self.setStyleSheet("font-family: Consolas, monospace; font-size: 13px; background: #1c1c20; border: 1px solid #42a5f5;")
        super().mousePressEvent(e)

    def _end_edit(self):
        self._editing = False
        self.setReadOnly(True)
        self.setStyleSheet("font-family: Consolas, monospace; font-size: 13px; background: transparent;")
        self.set_times(self._pos, self._dur)
        self.clearFocus()

    def _commit(self):
        t = parse_time(self.text())
        self._end_edit()
        if t is not None:
            self.seekTo.emit(t)

    def focusOutEvent(self, e):
        if self._editing:
            self._end_edit()
        super().focusOutEvent(e)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape and self._editing:
            self._end_edit()
            return
        super().keyPressEvent(e)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"ClipSlicer {__version__}")
        self.resize(1320, 800)
        self.setAcceptDrops(True)
        self.settings = make_settings()  # exe 옆 settings.ini (포터블)

        self.projects: dict[str, ClipProject] = {}
        self.current: ClipProject | None = None
        self.workers: dict[str, AnalyzeWorker] = {}
        self.export_worker: ExportWorker | None = None
        self.silence_worker: SilenceWorker | None = None
        self.scene_worker: SceneWorker | None = None
        self.update_worker = None
        self.update_info: dict | None = None
        self._update_manual = False
        self.loop_idx = -1
        self.preview_active = False
        self.gpu_encoder: str | None = None
        self._table_updating = False
        self._hl_row = -1
        self._export_dirs: list[str] = []
        self._job_total = 0
        self.bookmark_window: BookmarkWindow | None = None
        self.sample_worker: SampleWorker | None = None
        self.discord_worker = None

        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(600)
        self.save_timer.timeout.connect(self._save_dirty)

        self._build_ui()
        self._build_menus()
        self._build_shortcuts()
        self.notifier = Notifier(self, QApplication.windowIcon())
        self._restore_settings()
        self._start_gpu_detect()
        QTimer.singleShot(3000, self._auto_check_updates)
        QTimer.singleShot(400, self._maybe_first_run)

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        root = QSplitter(Qt.Horizontal, self)
        self.setCentralWidget(root)

        # ---- 왼쪽: 파일 목록 ----
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(8, 8, 4, 8)
        lv.setSpacing(6)
        title = QLabel(tr("영상 목록"))
        title.setObjectName("panelTitle")
        lv.addWidget(title)
        self.file_list = QListWidget()
        self.file_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.file_list.currentRowChanged.connect(self._on_file_selected)
        self.file_list.setToolTip(tr("클릭해서 전환 · Ctrl+↑/↓"))
        lv.addWidget(self.file_list, 1)
        fb = QHBoxLayout()
        btn_add = QPushButton(tr("＋ 추가"))
        btn_add.setToolTip(tr("영상 열기 (Ctrl+O)"))
        btn_add.clicked.connect(self.open_files)
        btn_rm = QPushButton(tr("－ 제거"))
        btn_rm.setToolTip(tr("목록에서 현재 영상 제거 (파일은 그대로)"))
        btn_rm.clicked.connect(self.remove_current_file)
        for b in (btn_add, btn_rm):
            b.setFocusPolicy(Qt.NoFocus)
        fb.addWidget(btn_add)
        fb.addWidget(btn_rm)
        lv.addLayout(fb)
        root.addWidget(left)

        # ---- 가운데: 플레이어 + 타임라인 + 컨트롤 ----
        center = QWidget()
        cv = QVBoxLayout(center)
        cv.setContentsMargins(4, 8, 4, 8)
        cv.setSpacing(6)

        self.stack = QStackedWidget()
        self.drop_label = StartPanel()
        self.drop_label.openRequested.connect(self.open_files)
        self.drop_label.urlRequested.connect(self.open_url)
        self.drop_label.sampleRequested.connect(self.open_sample)
        self.drop_label.fileRequested.connect(lambda p: self.add_files([p]))
        self.player = MpvWidget(compat=self.settings.value("compat_mode", "0") == "1")
        self.player.positionChanged.connect(self._on_position)
        self.player.durationChanged.connect(self._on_duration)
        self.player.pauseChanged.connect(self._on_pause_changed)
        self.player.fileLoaded.connect(self._on_file_loaded)
        self.player.clicked.connect(self.player.toggle_pause)
        self.stack.addWidget(self.drop_label)
        self.stack.addWidget(self.player)
        cv.addWidget(self.stack, 1)

        self.timeline = TimelineWidget()
        tl = self.timeline.canvas
        tl.seekRequested.connect(self._on_seek_requested)
        tl.markerDragStarted.connect(self._on_marker_drag_started)
        tl.markerMoved.connect(self._on_marker_moved)
        tl.markerDeleted.connect(self._on_marker_deleted)
        tl.segmentToggled.connect(self.toggle_segment)
        tl.segmentLoopRequested.connect(self.toggle_loop_segment)
        tl.addMarkerRequested.connect(self._add_marker_at)
        tl.viewChanged.connect(self._update_zoom_label)
        cv.addWidget(self.timeline)

        # 컨트롤 줄
        ctl = QHBoxLayout()
        ctl.setContentsMargins(4, 0, 4, 0)
        ctl.setSpacing(2)
        self.time_edit = TimeEdit()
        self.time_edit.seekTo.connect(lambda t: self.player.seek(t))
        ctl.addWidget(self.time_edit)

        def tb(text, tip, fn, big=False):
            b = QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.setAutoRaise(True)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(fn)
            if big:
                b.setObjectName("playBtn")
            ctl.addWidget(b)
            return b

        tb("⏮", tr("10초 뒤로 (Ctrl+←)"), lambda: self.player.seek_relative(-10))
        tb("◀◀", tr("1초 뒤로 (Shift+←)"), lambda: self.player.seek_relative(-1))
        tb("◀", tr("한 프레임 뒤로 (←)"), lambda: self.player.frame_step(False))
        self.btn_play = tb("▶", tr("재생/정지 (Space)"), self.player.toggle_pause, big=True)
        tb("▶", tr("한 프레임 앞으로 (→)"), lambda: self.player.frame_step(True))
        tb("▶▶", tr("1초 앞으로 (Shift+→)"), lambda: self.player.seek_relative(1))
        tb("⏭", tr("10초 앞으로 (Ctrl+→)"), lambda: self.player.seek_relative(10))
        ctl.addSpacing(10)

        self.btn_cut = QPushButton(tr("✂  여기서 자르기"))
        self.btn_cut.setObjectName("cutBtn")
        self.btn_cut.setToolTip(tr("현재 위치에 자르기 마커 (S)"))
        self.btn_cut.setFocusPolicy(Qt.NoFocus)
        self.btn_cut.clicked.connect(self.add_marker_here)
        ctl.addWidget(self.btn_cut)
        self.btn_preview = QPushButton(tr("↺ 앞뒤 2초"))
        self.btn_preview.setCheckable(True)
        self.btn_preview.setToolTip(tr("현재 위치 앞뒤 2초를 반복 재생해서 자를 지점 확인 (R)"))
        self.btn_preview.setFocusPolicy(Qt.NoFocus)
        self.btn_preview.clicked.connect(self._on_preview_button)
        ctl.addWidget(self.btn_preview)
        self.btn_loop = QPushButton(tr("🔁 구간 반복"))
        self.btn_loop.setCheckable(True)
        self.btn_loop.setToolTip(tr("현재 구간 반복 재생 (L) · 타임라인 더블클릭"))
        self.btn_loop.setFocusPolicy(Qt.NoFocus)
        self.btn_loop.clicked.connect(self._on_loop_button)
        ctl.addWidget(self.btn_loop)
        ctl.addStretch(1)

        self.cb_speed = QComboBox()
        for s in SPEEDS:
            self.cb_speed.addItem(f"{s:g}x", s)
        self.cb_speed.setCurrentIndex(SPEEDS.index(1.0))
        self.cb_speed.setToolTip(tr("재생 속도 ([ 느리게 · ] 빠르게 · \\ 1배속)"))
        self.cb_speed.setFocusPolicy(Qt.NoFocus)
        self.cb_speed.currentIndexChanged.connect(lambda i: self.player.set_speed(self.cb_speed.itemData(i)))
        ctl.addWidget(self.cb_speed)
        self.btn_mute = QToolButton()
        self.btn_mute.setText("🔊")
        self.btn_mute.setCheckable(True)
        self.btn_mute.setAutoRaise(True)
        self.btn_mute.setToolTip(tr("음소거 (M)"))
        self.btn_mute.setFocusPolicy(Qt.NoFocus)
        self.btn_mute.toggled.connect(self._on_mute)
        ctl.addWidget(self.btn_mute)
        self.sl_volume = QSlider(Qt.Horizontal)
        self.sl_volume.setRange(0, 100)
        self.sl_volume.setValue(100)
        self.sl_volume.setFixedWidth(90)
        self.sl_volume.setToolTip(tr("볼륨"))
        self.sl_volume.setFocusPolicy(Qt.NoFocus)
        self.sl_volume.valueChanged.connect(self.player.set_volume)
        ctl.addWidget(self.sl_volume)
        # 창이 좁으면 컨트롤 줄은 가로 스크롤 (창 최소 폭을 키우지 않게)
        ctl_w = QWidget()
        ctl_w.setLayout(ctl)
        ctl_sa = QScrollArea()
        ctl_sa.setWidget(ctl_w)
        ctl_sa.setWidgetResizable(True)
        ctl_sa.setFrameShape(QFrame.NoFrame)
        ctl_sa.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        ctl_sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        ctl_sa.setFixedHeight(ctl_w.sizeHint().height() + 14)
        cv.addWidget(ctl_sa)

        hint = QLabel(tr("타임라인: 클릭 이동 · 우클릭 마커 추가/삭제 · 마커 드래그 · Ctrl+클릭 구간 켜기/끄기 · 더블클릭 구간 반복 · Ctrl+휠 확대"))
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        hint.setMinimumWidth(0)
        hint.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        cv.addWidget(hint)
        root.addWidget(center)

        # ---- 오른쪽: 구간 목록 + 내보내기 ----
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(4, 8, 8, 8)
        rv.setSpacing(6)
        head = QHBoxLayout()
        t2 = QLabel(tr("구간 목록"))
        t2.setObjectName("panelTitle")
        head.addWidget(t2)
        head.addStretch(1)
        btn_silence = QPushButton(tr("무음 자동 마커"))
        btn_silence.setToolTip(tr("조용한 구간에 마커를 자동으로 찍습니다 (Ctrl+Shift+M)"))
        btn_silence.setFocusPolicy(Qt.NoFocus)
        btn_silence.clicked.connect(self.auto_markers_silence)
        head.addWidget(btn_silence)
        btn_chap = QPushButton(tr("챕터 복사"))
        btn_chap.setToolTip(tr("켜진 구간을 '00:00 이름' 목록으로 클립보드에 복사 (유튜브 설명란용)"))
        btn_chap.setFocusPolicy(Qt.NoFocus)
        btn_chap.clicked.connect(self.copy_chapters)
        head.addWidget(btn_chap)
        btn_clear = QPushButton(tr("모두 지우기"))
        btn_clear.setToolTip(tr("이 영상의 마커를 전부 삭제 (실행 취소 가능)"))
        btn_clear.setFocusPolicy(Qt.NoFocus)
        btn_clear.clicked.connect(self.clear_markers)
        head.addWidget(btn_clear)
        rv.addLayout(head)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels([tr("사용"), "#", tr("순서"), tr("시작"), tr("끝"), tr("길이"), tr("파일명"), tr("메모")])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(COL_NAME, QHeaderView.Stretch)
        hh.setSectionResizeMode(COL_NOTE, QHeaderView.Stretch)
        self.table.setColumnHidden(COL_ORDER, True)   # '하나로 합치기' 를 켤 때만 보임
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.table.setFocusPolicy(Qt.ClickFocus)
        self.table.setToolTip(tr("클릭: 구간 시작으로 이동 · 더블클릭(파일명): 이름 변경 · 더블클릭(그 외): 반복 재생"))
        self.table.itemChanged.connect(self._on_table_item_changed)
        self.table.cellClicked.connect(self._on_table_cell_clicked)
        self.table.cellDoubleClicked.connect(self._on_table_cell_double_clicked)
        rv.addWidget(self.table, 1)

        grp = QGroupBox(tr("내보내기"))
        gv = QVBoxLayout(grp)
        gv.setSpacing(6)
        outrow = QHBoxLayout()
        self.ed_outdir = QLineEdit()
        self.ed_outdir.setPlaceholderText(tr("비워 두면 원본 옆 '<이름>_cuts' 폴더"))
        btn_out = QToolButton()
        btn_out.setText("…")
        btn_out.setToolTip(tr("출력 폴더 선택"))
        btn_out.clicked.connect(self.choose_outdir)
        outrow.addWidget(QLabel(tr("폴더")))
        outrow.addWidget(self.ed_outdir, 1)
        outrow.addWidget(btn_out)
        gv.addLayout(outrow)

        moderow = QHBoxLayout()
        moderow.addWidget(QLabel(tr("방식")))
        self.cb_mode = QComboBox()
        self.cb_mode.addItem(tr("빠르게 — 원본 그대로 잘라내기 (즉시, 기본)"), "fast")
        self.cb_mode.addItem(tr("스마트 — 시작점 정확 (앞 1~2초만 재인코딩)"), "smart")
        self.cb_mode.addItem(tr("정확하게 — 전체 재인코딩 (느림)"), "precise")
        self.cb_mode.setToolTip(
            tr("빠르게: 재인코딩 없이 복사. 시작점이 바로 앞 키프레임까지(보통 1~2초) 당겨질 수 있음.\n스마트: 시작~첫 키프레임만 재인코딩해서 시작점을 정확히 맞춤. 파일을 한 번 더 읽음.\n정확하게: 전부 재인코딩. 어떤 영상이든 되지만 가장 느림."))
        self._mode_tip = self.cb_mode.toolTip()
        self.cb_mode.setFocusPolicy(Qt.NoFocus)
        self.cb_mode.currentIndexChanged.connect(lambda _i: self._refresh_table())
        moderow.addWidget(self.cb_mode, 1)
        gv.addLayout(moderow)

        optrow = QHBoxLayout()
        optrow.addWidget(QLabel(tr("출력")))
        self.cb_audio = QComboBox()
        self.cb_audio.addItem(tr("영상 + 오디오"), "")
        self.cb_audio.addItem(tr("영상만 (소리 없음)"), "mute")
        self.cb_audio.addItem(tr("오디오만 (m4a)"), "aac")
        self.cb_audio.addItem(tr("오디오만 (mp3)"), "mp3")
        self.cb_audio.addItem(tr("세로 9:16 쇼츠 (재인코딩)"), "vertical")
        self.cb_audio.setFocusPolicy(Qt.NoFocus)
        self.cb_audio.currentIndexChanged.connect(self._on_output_changed)
        optrow.addWidget(self.cb_audio)
        self.btn_crop = QPushButton(tr("크롭 위치…"))
        self.btn_crop.setToolTip(tr("현재 화면에서 세로로 잘라낼 위치를 고릅니다"))
        self.btn_crop.setFocusPolicy(Qt.NoFocus)
        self.btn_crop.clicked.connect(self.choose_crop)
        self.btn_crop.hide()
        optrow.addWidget(self.btn_crop)
        self.cb_merge = QCheckBox(tr("하나로 합치기"))
        self.cb_merge.setToolTip(tr("켜진 구간들을 각각 저장하지 않고 순서대로 이어 붙여 파일 하나로 만듭니다"))
        self.cb_merge.setFocusPolicy(Qt.NoFocus)
        self.cb_merge.toggled.connect(lambda _c: self._refresh_table())
        optrow.addWidget(self.cb_merge)
        optrow.addStretch(1)
        gv.addLayout(optrow)
        optrow = QHBoxLayout()  # 완료 후 동작은 둘째 줄 (패널 폭을 줄이기 위해)
        self.cb_open = QCheckBox(tr("완료 후 폴더 열기"))
        self.cb_open.setChecked(True)
        self.cb_open.setFocusPolicy(Qt.NoFocus)
        optrow.addWidget(self.cb_open)
        self.cb_youtube = QCheckBox(tr("완료 후 유튜브에 올리기"))
        self.cb_youtube.setToolTip(tr("내보내기가 끝나면 잘린 파일들을 유튜브(비공개)에 올리는 창을 엽니다. 설정 ▸ 유튜브 계정 연결 필요"))
        self.cb_youtube.setFocusPolicy(Qt.NoFocus)
        optrow.addWidget(self.cb_youtube)
        self.cb_discord = QCheckBox(tr("디스코드로 보내기"))
        self.cb_discord.setToolTip(tr("내보내기가 끝나면 잘린 파일들을 디스코드 웹훅으로 보냅니다 (크기 한도 이하만). 설정 ▸ 디스코드 웹훅… 필요"))
        self.cb_discord.setFocusPolicy(Qt.NoFocus)
        optrow.addWidget(self.cb_discord)
        optrow.addStretch(1)
        gv.addLayout(optrow)

        fxrow = QHBoxLayout()
        self.cb_normalize = QCheckBox(tr("음량 정규화"))
        self.cb_normalize.setToolTip(tr("loudnorm(-14 LUFS)으로 소리 크기를 고르게 맞춥니다. 오디오만 aac 로 다시 인코딩하고 영상은 그대로 복사합니다"))
        self._normalize_tip = self.cb_normalize.toolTip()
        self.cb_normalize.setFocusPolicy(Qt.NoFocus)
        fxrow.addWidget(self.cb_normalize)
        self.cb_layout = QComboBox()
        self.cb_layout.addItem(tr("크롭 (화면 일부 잘라내기)"), "crop")
        self.cb_layout.addItem(tr("블러 배경 (전체 화면 + 흐린 배경)"), "blur")
        self.cb_layout.setToolTip(tr("세로 9:16 출력 레이아웃. 블러 배경은 16:9 화면 전체를 가운데 두고 위아래를 흐린 확대 화면으로 채웁니다"))
        self.cb_layout.setFocusPolicy(Qt.NoFocus)
        self.cb_layout.hide()
        fxrow.addWidget(self.cb_layout)
        fxrow.addStretch(1)
        gv.addLayout(fxrow)

        caprow = QHBoxLayout()
        caprow.addWidget(QLabel(tr("캡션")))
        self.ed_caption = QLineEdit()
        self.ed_caption.setPlaceholderText(tr("영상 아래쪽에 굽는 글자 (비우면 없음 · 재인코딩)"))
        self.ed_caption.setToolTip(tr("여기에 쓴 글자를 영상에 새깁니다. 글자·자막·워터마크가 있으면 '빠르게' 방식이라도 재인코딩합니다"))
        self.ed_caption.textChanged.connect(lambda _t: self._refresh_table())
        caprow.addWidget(self.ed_caption, 1)
        gv.addLayout(caprow)

        subrow = QHBoxLayout()
        subrow.addWidget(QLabel(tr("자막")))
        self.ed_subtitle = QLineEdit()
        self.ed_subtitle.setPlaceholderText(tr("굽을 자막 파일 (.srt/.ass) — 비우면 없음"))
        self.ed_subtitle.setToolTip(tr("원본 영상 기준 자막 파일. 잘라낸 구간에 맞춰 시각을 옮긴 뒤 영상에 새깁니다"))
        self.ed_subtitle.textChanged.connect(lambda _t: self._refresh_table())
        btn_sub = QToolButton()
        btn_sub.setText("…")
        btn_sub.setToolTip(tr("자막 파일 선택"))
        btn_sub.clicked.connect(self.choose_subtitle)
        subrow.addWidget(self.ed_subtitle, 1)
        subrow.addWidget(btn_sub)
        gv.addLayout(subrow)

        btnrow = QHBoxLayout()
        self.btn_export_cur = QPushButton(tr("현재 영상"))
        self.btn_export_cur.setToolTip(tr("현재 영상의 켜진 구간만 내보내기 (Ctrl+Shift+E)"))
        self.btn_export_cur.clicked.connect(lambda: self.start_export(all_files=False))
        self.btn_export_all = QPushButton(tr("모든 영상 내보내기"))
        self.btn_export_all.setObjectName("exportBtn")
        self.btn_export_all.setToolTip(tr("목록의 모든 영상을 내보내기 (Ctrl+E)"))
        self.btn_export_all.clicked.connect(lambda: self.start_export(all_files=True))
        self.btn_cancel = QPushButton(tr("취소"))
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
        self.log.setMaximumHeight(120)
        self.log.setObjectName("log")
        self.log.setPlaceholderText(tr("내보내기 결과가 여기에 표시됩니다"))
        gv.addWidget(self.log)
        rv.addWidget(grp)
        # 오른쪽 패널은 좁아지면 스크롤 (창 최소 폭을 키우지 않게)
        right_sa = QScrollArea()
        right_sa.setWidget(right)
        right_sa.setWidgetResizable(True)
        right_sa.setFrameShape(QFrame.NoFrame)
        right_sa.setMinimumWidth(260)
        root.addWidget(right_sa)
        self.right_panel = right_sa

        root.setStretchFactor(0, 0)
        root.setStretchFactor(1, 1)
        root.setStretchFactor(2, 0)
        root.setSizes([210, 760, 380])
        self.splitter = root

        # 상태 표시줄
        self.btn_update = QPushButton("")
        self.btn_update.setObjectName("updateBtn")
        self.btn_update.setToolTip(tr("새 버전 보기"))
        self.btn_update.setFocusPolicy(Qt.NoFocus)
        self.btn_update.clicked.connect(self.show_update_dialog)
        self.btn_update.hide()
        self.statusBar().addPermanentWidget(self.btn_update)
        self.lbl_export = QLabel("")
        self.lbl_export.setToolTip(tr("내보내기 진행 상황 (오른쪽 패널을 숨겨도 보입니다)"))
        self.lbl_zoom = QLabel("")
        self.lbl_gpu = QLabel(tr("GPU 확인 중…"))
        self.lbl_saved = QLabel("")
        for w in (self.lbl_export, self.lbl_zoom, self.lbl_gpu, self.lbl_saved):
            w.setObjectName("statusChip")
            self.statusBar().addPermanentWidget(w)
        self.statusBar().showMessage(tr("영상을 끌어다 놓거나 Ctrl+O 로 열어 주세요"))

    def _build_menus(self):
        mb = self.menuBar()

        m_file = mb.addMenu(tr("파일(&F)"))
        a = QAction(tr("영상 열기…"), self)
        a.setShortcut(QKeySequence.Open)
        a.triggered.connect(self.open_files)
        m_file.addAction(a)
        a = QAction(tr("URL 에서 열기… (yt-dlp)"), self)
        a.setShortcut("Ctrl+L")
        a.triggered.connect(self.open_url)
        m_file.addAction(a)
        a = QAction(tr("사이트에서 녹화… (내장 브라우저)"), self)
        a.setShortcut("Ctrl+Alt+L")
        a.setToolTip(tr("rplay 처럼 로그인이 필요한 방송 페이지를 열고, 재생되면 버튼 한 번으로 녹화합니다"))
        a.triggered.connect(lambda: self.open_site_recorder())
        m_file.addAction(a)
        a = QAction(tr("방송 북마크 모드…"), self)
        a.triggered.connect(self.show_bookmark_window)
        m_file.addAction(a)
        self.menu_recent = QMenu(tr("최근 파일"), self)
        m_file.addMenu(self.menu_recent)
        m_file.addSeparator()
        a = QAction(tr("현재 화면을 PNG 로 저장"), self)
        a.setShortcut("Ctrl+P")
        a.triggered.connect(self.save_screenshot)
        m_file.addAction(a)
        m_file.addSeparator()
        a = QAction(tr("유튜브에 올리기… (파일 선택)"), self)
        a.setShortcut("Ctrl+U")
        a.triggered.connect(self.upload_files_to_youtube)
        m_file.addAction(a)
        a = QAction(tr("업로드 이력…"), self)
        a.triggered.connect(lambda: HistoryDialog(self).exec())
        m_file.addAction(a)
        m_file.addSeparator()
        a = QAction(tr("현재 영상 내보내기"), self)
        a.setShortcut("Ctrl+Shift+E")
        a.triggered.connect(lambda: self.start_export(all_files=False))
        m_file.addAction(a)
        a = QAction(tr("모든 영상 내보내기"), self)
        a.setShortcut("Ctrl+E")
        a.triggered.connect(lambda: self.start_export(all_files=True))
        m_file.addAction(a)
        m_file.addSeparator()
        a = QAction(tr("종료"), self)
        a.triggered.connect(self.close)
        m_file.addAction(a)

        m_edit = mb.addMenu(tr("편집(&E)"))
        self.act_undo = QAction(tr("실행 취소"), self)
        self.act_undo.setShortcut(QKeySequence.Undo)
        self.act_undo.triggered.connect(self.undo)
        self.act_redo = QAction(tr("다시 실행"), self)
        self.act_redo.setShortcut("Ctrl+Y")
        self.act_redo.triggered.connect(self.redo)
        m_edit.addActions([self.act_undo, self.act_redo])
        m_edit.addSeparator()
        a = QAction(tr("현재 위치에 마커"), self)
        a.setShortcut("S")
        a.triggered.connect(self.add_marker_here)
        m_edit.addAction(a)
        a = QAction(tr("가까운 마커 삭제"), self)
        a.setShortcut("Delete")
        a.triggered.connect(self.delete_nearest_marker)
        m_edit.addAction(a)
        m_edit.addSeparator()
        self.act_import_bookmarks = QAction(tr("북마크 가져오기…"), self)
        self.act_import_bookmarks.triggered.connect(self.import_bookmarks)
        m_edit.addAction(self.act_import_bookmarks)
        m_edit.addSeparator()
        a = QAction(tr("현재 구간 켜기/끄기"), self)
        a.setShortcut("E")
        a.triggered.connect(self.toggle_current_segment)
        m_edit.addAction(a)
        m_edit.addSeparator()
        a = QAction(tr("클립 시작 (In)"), self)
        a.setShortcut("I")
        a.triggered.connect(self.clip_in)
        m_edit.addAction(a)
        a = QAction(tr("클립 끝 (Out) — 사이만 켜기"), self)
        a.setShortcut("O")
        a.triggered.connect(self.clip_out)
        m_edit.addAction(a)
        a = QAction(tr("마커 모두 지우기"), self)
        a.triggered.connect(self.clear_markers)
        m_edit.addAction(a)
        m_edit.addSeparator()
        a = QAction(tr("무음 구간에 자동 마커…"), self)
        a.setShortcut("Ctrl+Shift+M")
        a.triggered.connect(self.auto_markers_silence)
        m_edit.addAction(a)
        a = QAction(tr("장면 전환에 자동 마커…"), self)
        a.setShortcut("Ctrl+Shift+S")
        a.triggered.connect(self.auto_markers_scene)
        m_edit.addAction(a)
        a = QAction(tr("큰 소리에 자동 마커 (웃음·환호)…"), self)
        a.setShortcut("Ctrl+Shift+L")
        a.triggered.connect(self.auto_markers_loud)
        m_edit.addAction(a)
        a = QAction(tr("타임스탬프 붙여넣기 → 마커…"), self)
        a.setShortcut("Ctrl+Shift+V")
        a.triggered.connect(self.paste_timestamps)
        m_edit.addAction(a)
        a = QAction(tr("채팅 반응 그래프·마커…"), self)
        a.setShortcut("Ctrl+Shift+C")
        a.triggered.connect(self.chat_markers)
        m_edit.addAction(a)

        m_view = mb.addMenu(tr("보기(&V)"))
        a = QAction(tr("확대"), self)
        a.setShortcut("Ctrl+=")
        a.triggered.connect(lambda: self.timeline.canvas.zoom(1.5))
        m_view.addAction(a)
        a = QAction(tr("축소"), self)
        a.setShortcut("Ctrl+-")
        a.triggered.connect(lambda: self.timeline.canvas.zoom(1 / 1.5))
        m_view.addAction(a)
        a = QAction(tr("전체 보기"), self)
        a.setShortcut("Ctrl+0")
        a.triggered.connect(self.timeline.canvas.zoom_reset)
        m_view.addAction(a)
        m_view.addSeparator()
        self.act_keyframes = QAction(tr("키프레임 표시"), self, checkable=True, checked=True)
        self.act_keyframes.toggled.connect(self._on_toggle_keyframes)
        m_view.addAction(self.act_keyframes)
        self.act_right_panel = QAction(tr("오른쪽 패널 (구간 목록·내보내기)"), self, checkable=True, checked=True)
        self.act_right_panel.setShortcut("Ctrl+Shift+R")
        self.act_right_panel.toggled.connect(self._on_toggle_right_panel)
        m_view.addAction(self.act_right_panel)

        m_set = mb.addMenu(tr("설정(&S)"))
        self.act_snap = QAction(tr("마커를 키프레임에 맞추기"), self, checkable=True)
        self.act_snap.setToolTip(tr("마커를 찍을 때 0.5초 안에 키프레임이 있으면 거기에 붙입니다"))
        m_set.addAction(self.act_snap)
        self.act_gpu = QAction(tr("GPU 인코딩 사용"), self, checkable=True, checked=True)
        m_set.addAction(self.act_gpu)
        self.act_autosave = QAction(tr("작업 자동 저장 (.clipslicer.json)"), self, checkable=True, checked=True)
        m_set.addAction(self.act_autosave)
        self.act_cache = QAction(tr("분석 결과 캐시 저장 (.clipslicer.cache)"), self, checkable=True, checked=True)
        self.act_cache.setToolTip(tr("썸네일·파형·키프레임을 저장해 두고 다음에 열 때 바로 씁니다"))
        m_set.addAction(self.act_cache)
        self.act_update = QAction(tr("시작할 때 새 버전 확인 (GitHub 조회)"), self, checkable=True, checked=True)
        m_set.addAction(self.act_update)
        self.act_compat = QAction(tr("호환 모드 — 화면이 검게 나올 때 (재시작 필요)"), self, checkable=True)
        self.act_compat.setChecked(self.settings.value("compat_mode", "0") == "1")
        self.act_compat.toggled.connect(self._on_compat_toggled)
        m_set.addAction(self.act_compat)
        m_set.addSeparator()
        m_lang = QMenu(tr("언어 / Language"), self)
        self.lang_actions = []
        cur = self.settings.value("lang", "auto")
        for code, label in i18n.LANGUAGES:
            a = QAction(tr(label), self, checkable=True, checked=(code == cur))
            a.triggered.connect(lambda _c=False, code=code: self._set_language(code))
            m_lang.addAction(a)
            self.lang_actions.append((code, a))
        m_set.addMenu(m_lang)
        m_set.addSeparator()
        a = QAction(tr("유튜브 계정 연결…"), self)
        a.triggered.connect(lambda: ConnectDialog(self).exec())
        m_set.addAction(a)
        a = QAction(tr("유튜브 설명 템플릿…"), self)
        a.triggered.connect(self.edit_yt_template)
        m_set.addAction(a)
        a = QAction(tr("디스코드 웹훅…"), self)
        a.triggered.connect(lambda: discord.DiscordSettingsDialog(self, self.settings).exec())
        m_set.addAction(a)
        m_set.addSeparator()
        a = QAction(tr("파일명 규칙…"), self)
        a.triggered.connect(self.edit_pattern)
        m_set.addAction(a)
        a = QAction(tr("워터마크 / 인트로·아웃트로…"), self)
        a.triggered.connect(self.edit_render_assets)
        m_set.addAction(a)

        m_help = mb.addMenu(tr("도움말(&H)"))
        a = QAction(tr("도움말"), self)
        a.setShortcut("F1")
        a.triggered.connect(lambda: self.show_help(0))
        m_help.addAction(a)
        a = QAction(tr("단축키"), self)
        a.triggered.connect(lambda: self.show_help(1))
        m_help.addAction(a)
        a = QAction(tr("자르기 모드 설명"), self)
        a.triggered.connect(lambda: self.show_help(3))
        m_help.addAction(a)
        a = QAction(tr("처음 사용 안내…"), self)
        a.triggered.connect(self.show_first_run)
        m_help.addAction(a)
        m_help.addSeparator()
        a = QAction(tr("GitHub 저장소 열기"), self)
        a.triggered.connect(lambda: os.startfile("https://github.com/vtubeadmirer/clipslicer"))
        m_help.addAction(a)
        a = QAction(tr("로그 폴더 열기"), self)
        a.triggered.connect(lambda: os.startfile(log_dir()))
        m_help.addAction(a)
        m_help.addSeparator()
        a = QAction(tr("업데이트 확인…"), self)
        a.triggered.connect(lambda: self.check_updates(manual=True))
        m_help.addAction(a)
        self._rebuild_recent_menu()

    def _build_shortcuts(self):
        def sc(keys, fn):
            s = QShortcut(QKeySequence(keys), self)
            s.setContext(Qt.WindowShortcut)
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
        sc("L", self._on_loop_shortcut)
        sc("R", self.toggle_preview_around)
        sc("M", lambda: self.btn_mute.toggle())
        sc("[", lambda: self._change_speed(-1))
        sc("]", lambda: self._change_speed(1))
        sc("\\", lambda: self.cb_speed.setCurrentIndex(SPEEDS.index(1.0)))
        sc("Escape", self.clip_cancel)
        sc("Up", self._jump_segment_prev)
        sc("Down", self._jump_segment_next)
        sc("Ctrl+Up", lambda: self._select_file_offset(-1))
        sc("Ctrl+Down", lambda: self._select_file_offset(1))
        sc("Ctrl+Shift+Up", lambda: self._move_segment_order(self.table.currentRow(), -1))
        sc("Ctrl+Shift+Down", lambda: self._move_segment_order(self.table.currentRow(), 1))
        sc("N", lambda: self._edit_segment_name(self.current.segment_at(self.player.position) if self.current else -1))
        sc("F2", lambda: self._edit_segment_name(self.table.currentRow()))

    def show_help(self, page: int = 0):
        HelpDialog(self, page).exec()

    def _edit_segment_name(self, row: int):
        """구간 row 의 파일명 칸을 바로 편집 (N: 현재 위치 구간, F2: 선택한 행)."""
        if not self.current or not (0 <= row < len(self.current.segments)):
            return
        if self.cb_merge.isChecked():
            self.statusBar().showMessage(tr("'하나로 합치기' 가 켜져 있으면 구간별 파일명을 쓰지 않습니다"), 3000)
            return
        if not self.right_panel.isVisible():
            self.act_right_panel.setChecked(True)
        it = self.table.item(row, COL_NAME)
        if it is None:
            return
        self.table.setCurrentCell(row, COL_NAME)
        self.table.setFocus()
        self.table.editItem(it)

    def _on_toggle_right_panel(self, on: bool):
        self.right_panel.setVisible(on)
        self.settings.setValue("right_panel", "1" if on else "0")

    # ------------------------------------------------------------ 설정
    def _restore_settings(self):
        s = self.settings
        self.ed_outdir.setText(s.value("out_dir", ""))
        mode = s.value("mode", "fast")
        idx = self.cb_mode.findData(mode)
        self.cb_mode.setCurrentIndex(idx if idx >= 0 else 0)
        self.cb_open.setChecked(s.value("open_after", "1") == "1")
        self.cb_youtube.setChecked(s.value("yt_after", "0") == "1")
        self.cb_discord.setChecked(s.value("discord_after", "0") == "1")
        self.cb_normalize.setChecked(s.value("normalize", "0") == "1")
        idx = self.cb_layout.findData(s.value("layout", "crop"))
        self.cb_layout.setCurrentIndex(idx if idx >= 0 else 0)
        self.act_right_panel.setChecked(s.value("right_panel", "1") == "1")
        self.right_panel.setVisible(self.act_right_panel.isChecked())
        self.act_snap.setChecked(s.value("snap_keyframes", "0") == "1")
        self.act_gpu.setChecked(s.value("use_gpu", "1") == "1")
        self.act_autosave.setChecked(s.value("autosave", "1") == "1")
        self.act_cache.setChecked(s.value("use_cache", "1") == "1")
        self.act_update.setChecked(s.value("check_updates", "1") == "1")
        self.act_keyframes.setChecked(s.value("show_keyframes", "1") == "1")
        self.pattern = s.value("pattern", DEFAULT_PATTERN) or DEFAULT_PATTERN
        self._on_output_changed(0)
        self.sl_volume.setValue(int(s.value("volume", 100)))
        geo = s.value("geometry")
        if geo:
            self.restoreGeometry(geo)
        sizes = s.value("splitter")
        if sizes:
            try:
                self.splitter.setSizes([int(x) for x in sizes])
            except (TypeError, ValueError):
                pass

    def _save_settings(self):
        s = self.settings
        s.setValue("out_dir", self.ed_outdir.text())
        s.setValue("mode", self._mode())
        s.setValue("open_after", "1" if self.cb_open.isChecked() else "0")
        s.setValue("yt_after", "1" if self.cb_youtube.isChecked() else "0")
        s.setValue("discord_after", "1" if self.cb_discord.isChecked() else "0")
        s.setValue("normalize", "1" if self.cb_normalize.isChecked() else "0")
        s.setValue("layout", self.cb_layout.currentData() or "crop")
        s.setValue("right_panel", "1" if self.act_right_panel.isChecked() else "0")
        s.setValue("snap_keyframes", "1" if self.act_snap.isChecked() else "0")
        s.setValue("use_gpu", "1" if self.act_gpu.isChecked() else "0")
        s.setValue("autosave", "1" if self.act_autosave.isChecked() else "0")
        s.setValue("use_cache", "1" if self.act_cache.isChecked() else "0")
        s.setValue("check_updates", "1" if self.act_update.isChecked() else "0")
        s.setValue("show_keyframes", "1" if self.act_keyframes.isChecked() else "0")
        s.setValue("pattern", self.pattern)
        s.setValue("volume", self.sl_volume.value())
        s.setValue("geometry", self.saveGeometry())
        s.setValue("splitter", self.splitter.sizes())

    def _recent(self) -> list[str]:
        v = self.settings.value("recent", [])
        if isinstance(v, str):
            v = [v]
        return [p for p in (v or []) if isinstance(p, str)]

    def _add_recent(self, path: str):
        rec = [p for p in self._recent() if p != path]
        rec.insert(0, path)
        self.settings.setValue("recent", rec[:MAX_RECENT])
        self._rebuild_recent_menu()

    def _rebuild_recent_menu(self):
        self.drop_label.set_recent(self._recent())
        self.menu_recent.clear()
        rec = self._recent()
        if not rec:
            a = QAction(tr("(없음)"), self)
            a.setEnabled(False)
            self.menu_recent.addAction(a)
            return
        for p in rec:
            a = QAction(os.path.basename(p), self)
            a.setToolTip(p)
            a.triggered.connect(lambda _c=False, p=p: self.add_files([p]))
            self.menu_recent.addAction(a)
        self.menu_recent.addSeparator()
        a = QAction(tr("목록 지우기"), self)
        a.triggered.connect(lambda: (self.settings.setValue("recent", []), self._rebuild_recent_menu()))
        self.menu_recent.addAction(a)

    def _set_language(self, code: str):
        for c, a in self.lang_actions:
            a.setChecked(c == code)
        self.settings.setValue("lang", code)
        self.settings.sync()
        QMessageBox.information(self, tr("언어 / Language"), tr("언어는 다음 실행부터 적용됩니다.") + "\nThe language changes the next time the app starts.")

    def _on_compat_toggled(self, on: bool):
        self.settings.setValue("compat_mode", "1" if on else "0")
        self.settings.sync()
        QMessageBox.information(self, tr("호환 모드"), tr("다음 실행부터 적용됩니다.\n")
                                + (tr("GPU 가속 없이 화면을 그립니다. 원격 데스크톱·가상머신·구형 그래픽에서 화면이 검게 나올 때 쓰세요.")
                                   if on else tr("GPU 가속 재생으로 돌아갑니다.")))

    def edit_pattern(self):
        d = PatternDialog(self, self.pattern)
        if d.exec():
            self.pattern = d.pattern
            self._refresh_table()

    def _start_gpu_detect(self):
        self.gpu_worker = GpuDetectWorker(self)
        self.gpu_worker.done.connect(self._on_gpu_detected)
        self.gpu_worker.start()

    def _on_gpu_detected(self, enc):
        self.gpu_encoder = enc
        LOG.info("GPU 인코더: %s", enc)
        if enc:
            self.lbl_gpu.setText(f"GPU: {enc}")
            self.act_gpu.setText(tr("GPU 인코딩 사용 ({0})").format(enc))
        else:
            self.lbl_gpu.setText(tr("GPU 인코더 없음 (CPU)"))
            self.act_gpu.setText(tr("GPU 인코딩 사용 (감지 안 됨)"))
            self.act_gpu.setEnabled(False)

    def _on_toggle_keyframes(self, on: bool):
        self.timeline.canvas.show_keyframes = on
        self.timeline.canvas.update()

    def _update_zoom_label(self):
        z = self.timeline.canvas.zoom_factor()
        self.lbl_zoom.setText("" if z <= 1.01 else tr("확대 {0:.1f}x").format(z))

    def closeEvent(self, e):
        if self.export_worker and self.export_worker.isRunning():
            if QMessageBox.question(self, tr("종료"), tr("내보내기가 진행 중입니다. 취소하고 종료할까요?")) != QMessageBox.Yes:
                e.ignore()
                return
            self.export_worker.cancel()
            self.export_worker.wait(3000)
        if self.discord_worker and self.discord_worker.isRunning():
            self.discord_worker.cancel()
            self.discord_worker.wait(3000)
        if self.current:
            self.current.last_position = self.player.position
            self.current.dirty = True
        self._save_dirty(force=True)
        self._save_settings()
        self.timeline.canvas.popup.hide()
        for w in self.workers.values():
            if w.isRunning():
                w.wait(2000)
        if self.bookmark_window is not None:
            self.bookmark_window.close()
        self.notifier.hide()
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
        paths, _ = QFileDialog.getOpenFileNames(self, tr("영상 열기"), start, tr("영상 파일 ({0});;모든 파일 (*.*)").format(exts))
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
            if p.endswith(".clipslicer.json"):
                p = p[: -len(".clipslicer.json")]
            added = self._add_file(p) or added
        if added is not None:
            row = list(self.projects.keys()).index(added)
            self.file_list.setCurrentRow(row)

    def _add_file(self, path: str) -> str | None:
        path = os.path.abspath(path)
        if path in self.projects:
            return path
        if not os.path.isfile(path):
            self._log(tr("파일 없음: {0}").format(path))
            return None
        try:
            info = ffmpeg_tools.probe(path)
        except Exception as ex:
            LOG.warning("열기 실패 %s: %s", path, ex)
            self._log(tr("열기 실패: {0} — {1}").format(os.path.basename(path), ex))
            return None
        LOG.info("열기 %s | %sx%s %.2ffps %.1fs %s/%s", path, info["width"], info["height"], info["fps"],
                 info["duration"], info["vcodec"], info["acodec"])
        if info["duration"] <= 0:
            self._log(tr("길이를 알 수 없음: {0}").format(os.path.basename(path)))
            return None
        proj = ClipProject(path=path, duration=info["duration"], fps=info["fps"],
                           width=info["width"], height=info["height"], info=info)
        proj.rebuild_segments()
        restored = proj.has_project_file() and proj.load()
        proj.chat = ChatData.load(path)   # <영상>.clipslicer.chat.json 이 있으면 반응 그래프를 바로 그린다
        self.projects[path] = proj
        item = QListWidgetItem(os.path.basename(path))
        item.setToolTip(f"{path}\n{info['width']}x{info['height']}  {info['fps']:.2f}fps  {fmt_time(info['duration'])}"
                        f"  {info['vcodec']}/{info['acodec']}")
        item.setData(Qt.UserRole, path)
        self.file_list.addItem(item)
        self._update_file_item(proj)
        self._add_recent(path)
        if bookmarks.bookmarks_for_file(path, proj.duration):
            QTimer.singleShot(300, lambda p=path: self._offer_bookmarks(p))
        self._start_analyze(proj)
        if restored:
            self.statusBar().showMessage(tr("{0}: 저장된 작업 복원 (마커 {1}개)").format(os.path.basename(path), len(proj.markers)), 5000)
        return path

    def _update_file_item(self, proj: ClipProject):
        for i in range(self.file_list.count()):
            it = self.file_list.item(i)
            if it.data(Qt.UserRole) == proj.path:
                n = len(proj.enabled_segments())
                it.setText(f"{os.path.basename(proj.path)}" + (f"   [{n}]" if proj.markers else ""))

    def _start_analyze(self, proj: ClipProject):
        w = AnalyzeWorker(proj.path, proj.duration, self, use_cache=self.act_cache.isChecked())
        w.thumbsReady.connect(self._on_thumbs_ready)
        w.waveformReady.connect(self._on_waveform_ready)
        w.keyframesReady.connect(self._on_keyframes_ready)
        w.finished.connect(lambda p=proj.path: self.workers.pop(p, None))
        self.workers[proj.path] = w
        w.start()

    def _on_thumbs_ready(self, path: str, thumbs: list):
        proj = self.projects.get(os.path.abspath(path))
        if not proj:
            return
        out = []
        for t, data in thumbs:
            pix = QPixmap()
            if pix.loadFromData(data, "JPEG"):
                out.append((t, pix))
        proj.thumbs = out
        if proj is self.current:
            self.timeline.canvas.update()

    def _on_waveform_ready(self, path: str, wave):
        proj = self.projects.get(os.path.abspath(path))
        if proj:
            proj.waveform = wave
            if proj is self.current:
                self.timeline.canvas.update()

    def _on_keyframes_ready(self, path: str, kfs: list):
        proj = self.projects.get(os.path.abspath(path))
        if proj:
            proj.keyframes = kfs
            if proj is self.current:
                self.timeline.canvas.update()
                if len(kfs) > 1:
                    gap = proj.duration / len(kfs)
                    self.statusBar().showMessage(tr("키프레임 {0}개, 평균 간격 {1:.1f}초").format(len(kfs), gap), 4000)

    def remove_current_file(self):
        row = self.file_list.currentRow()
        if row < 0:
            return
        item = self.file_list.takeItem(row)
        path = item.data(Qt.UserRole)
        proj = self.projects.pop(path, None)
        if proj and proj.dirty and self.act_autosave.isChecked():
            proj.save()
        if self.current and self.current.path == path:
            self.current = None
            self._set_loop(-1)
            self.player.unload()
            self.timeline.canvas.set_project(None)
            self._refresh_table()
            self.time_edit.set_times(0, 0)
            self.stack.setCurrentWidget(self.drop_label)
            self.setWindowTitle(f"ClipSlicer {__version__}")
        if self.file_list.count() == 0:
            self.file_list.setCurrentRow(-1)

    def _select_file_offset(self, d: int):
        n = self.file_list.count()
        if n == 0:
            return
        self.file_list.setCurrentRow((self.file_list.currentRow() + d) % n)

    def _on_file_selected(self, row: int):
        if row < 0:
            return
        path = self.file_list.item(row).data(Qt.UserRole)
        proj = self.projects.get(path)
        if not proj or proj is self.current:
            return
        if self.current:
            self.current.last_position = self.player.position
            self.current.dirty = True
            self._save_dirty()
        self._set_loop(-1)
        if self.current:
            self.current.pending_in = None
        self.current = proj
        self.stack.setCurrentWidget(self.player)
        self.player.load(path)
        self.timeline.canvas.set_project(proj)
        self._hl_row = -1
        self._refresh_table()
        self._update_title()
        self._update_undo_actions()
        info = proj.info
        self.statusBar().showMessage(
            f"{proj.width}x{proj.height}  {proj.fps:.2f}fps  {fmt_time(proj.duration)}  "
            f"{info.get('vcodec', '')}/{info.get('acodec', '') or tr('오디오 없음')}")

    def _on_file_loaded(self):
        if self.current and self.current.last_position > 0:
            self.player.seek(self.current.last_position)
        self.player.set_speed(self.cb_speed.currentData())
        self.player.set_volume(self.sl_volume.value())
        self.player.set_mute(self.btn_mute.isChecked())

    def _update_title(self):
        if self.current:
            self.setWindowTitle(f"ClipSlicer {__version__} — {os.path.basename(self.current.path)}")
        else:
            self.setWindowTitle(f"ClipSlicer {__version__}")

    # ------------------------------------------------------------ 자동 저장
    def _schedule_save(self):
        if self.current:
            self.current.dirty = True
            self._update_file_item(self.current)
        if self.act_autosave.isChecked():
            self.save_timer.start()

    def _save_dirty(self, force: bool = False):
        if not self.act_autosave.isChecked() and not force:
            return
        if not self.act_autosave.isChecked():
            return
        n = 0
        for proj in self.projects.values():
            if proj.dirty and (proj.markers or proj.source_url or proj.has_project_file() or any(s.name or not s.enabled for s in proj.segments)):
                if proj.save():
                    n += 1
        if n:
            self.lbl_saved.setText(tr("자동 저장됨"))
            QTimer.singleShot(2500, lambda: self.lbl_saved.setText(""))

    # ------------------------------------------------------------ 재생 상태
    def _on_position(self, t: float):
        self.timeline.canvas.set_position(t)
        self.time_edit.set_times(t, self.current.duration if self.current else 0.0)
        if self.current:
            idx = self.current.segment_at(t)
            if idx != self._hl_row:
                self._highlight_row(idx)

    def _on_duration(self, d: float):
        if self.current and d > 0 and abs(self.current.duration - d) > 0.5:
            self.current.duration = d
            self.current.rebuild_segments()
            if self.current.chat is not None:
                self.current.chat.build_buckets(d)
            self.timeline.canvas.set_project(self.current)
            self._refresh_table()

    def _on_pause_changed(self, paused: bool):
        self.btn_play.setText("▶" if paused else "⏸")

    def _on_seek_requested(self, t: float, final: bool):
        self.player.seek(t, exact=final)

    def _on_mute(self, on: bool):
        self.player.set_mute(on)
        self.btn_mute.setText("🔇" if on else "🔊")

    def _change_speed(self, d: int):
        i = max(0, min(len(SPEEDS) - 1, self.cb_speed.currentIndex() + d))
        self.cb_speed.setCurrentIndex(i)
        self.statusBar().showMessage(tr("재생 속도 {0:g}x").format(SPEEDS[i]), 1500)

    def _snap(self, t: float) -> float:
        if not self.current:
            return t
        fps = self.current.fps if self.current.fps > 0 else 30.0
        t = round(t * fps) / fps
        if self.act_snap.isChecked():
            k = self.current.nearest_keyframe(t, 0.5)
            if k is not None:
                return k
        return t

    # ------------------------------------------------------------ 마커 / 구간
    def _changed(self):
        """마커·구간이 바뀐 뒤 공통 처리."""
        self.timeline.canvas.update()
        self._refresh_table()
        self._update_undo_actions()
        self._schedule_save()

    def add_marker_here(self):
        if not self.current:
            return
        self.player.pause()
        self._add_marker_at(self.player.position)

    def _add_marker_at(self, t: float):
        if not self.current:
            return
        t = self._snap(t)
        snap = self.current.snapshot()
        if self.current.add_marker(t):
            self.current.undo_stack.append(snap)
            self.current.redo_stack.clear()
            self._set_loop(-1)
            self._changed()
            self.statusBar().showMessage(tr("마커 추가: {0}  (구간 {1}개)").format(fmt_time(t), len(self.current.segments)), 3000)

    def delete_nearest_marker(self):
        if not self.current or not self.current.markers:
            return
        pos = self.player.position
        idx = min(range(len(self.current.markers)), key=lambda i: abs(self.current.markers[i] - pos))
        self._on_marker_deleted(idx)

    def _on_marker_deleted(self, idx: int):
        if not self.current:
            return
        self.current.push_undo()
        t = self.current.markers[idx]
        self.current.remove_marker(idx)
        self._set_loop(-1)
        self._changed()
        self.statusBar().showMessage(tr("마커 삭제: {0}").format(fmt_time(t)), 3000)

    def _on_marker_drag_started(self):
        if self.current:
            self.current.push_undo()
            self._set_loop(-1)

    def _on_marker_moved(self, idx: int, t: float, final: bool):
        if not self.current:
            return
        self.current.move_marker(idx, self._snap(t) if final else t)
        if final:
            self._changed()
        else:
            self.timeline.canvas.update()
            self._refresh_table()

    def clear_markers(self):
        if not self.current or not self.current.markers:
            return
        self.current.push_undo()
        self.current.clear_markers()
        self._set_loop(-1)
        self._changed()
        self.statusBar().showMessage(tr("마커를 모두 지웠습니다 (Ctrl+Z 로 되돌리기)"), 4000)

    def toggle_segment(self, idx: int):
        if not self.current or not (0 <= idx < len(self.current.segments)):
            return
        self.current.push_undo()
        seg = self.current.segments[idx]
        seg.enabled = not seg.enabled
        self._changed()

    def toggle_current_segment(self):
        if self.current:
            self.toggle_segment(self.current.segment_at(self.player.position))

    def undo(self):
        if self.current and self.current.undo():
            self._set_loop(-1)
            self._changed()
            self.statusBar().showMessage(tr("실행 취소"), 1500)

    def redo(self):
        if self.current and self.current.redo():
            self._set_loop(-1)
            self._changed()
            self.statusBar().showMessage(tr("다시 실행"), 1500)

    def _update_undo_actions(self):
        self.act_undo.setEnabled(bool(self.current and self.current.undo_stack))
        self.act_redo.setEnabled(bool(self.current and self.current.redo_stack))

    def _jump_segment_prev(self):
        if not self.current:
            return
        pos = self.player.position
        prev = [s.start for s in self.current.segments if s.start < pos - 0.3]
        self.player.seek(prev[-1] if prev else 0.0)

    def _jump_segment_next(self):
        if not self.current:
            return
        pos = self.player.position
        nxt = [s.start for s in self.current.segments if s.start > pos + 0.01]
        if nxt:
            self.player.seek(nxt[0])

    # ---- 무음 자동 마커 ----
    def auto_markers_silence(self):
        if not self.current:
            return
        if self.silence_worker and self.silence_worker.isRunning():
            return
        if not self.current.info.get("has_audio"):
            QMessageBox.information(self, tr("무음 자동 마커"), tr("이 영상에는 오디오가 없습니다."))
            return
        d = SilenceDialog(self, float(self.settings.value("silence_db", -35.0)),
                          float(self.settings.value("silence_dur", 1.0)))
        if not d.exec():
            return
        self.settings.setValue("silence_db", d.noise_db)
        self.settings.setValue("silence_dur", d.min_dur)
        self._silence_mode = d.mode
        self.statusBar().showMessage(tr("무음 구간 분석 중…"))
        self.silence_worker = SilenceWorker(self.current.path, d.noise_db, d.min_dur, self)
        self.silence_worker.done.connect(self._on_silence_done)
        self.silence_worker.start()

    def _on_silence_done(self, path: str, spans: list):
        proj = self.projects.get(os.path.abspath(path))
        if not proj:
            return
        spans = [(a, min(b, proj.duration)) for a, b in spans if a < proj.duration]
        if not spans:
            self.statusBar().showMessage(tr("조건에 맞는 무음 구간이 없습니다. 기준 음량을 올려 보세요."), 5000)
            return
        proj.push_undo()
        if self._silence_mode == "edges":
            times = []
            for a, b in spans:
                times += [a, b]
            n = proj.add_markers(times)
            for a, b in spans:
                for s in proj.segments:
                    if abs(s.start - a) < 0.06 and abs(s.end - b) < 0.06:
                        s.enabled = False
                    elif s.start >= a - 0.01 and s.end <= b + 0.01:
                        s.enabled = False
            msg = tr("무음 구간 {0}개를 찾아 마커 {1}개 추가, 무음 구간은 껐습니다").format(len(spans), n)
        else:
            n = proj.add_markers([(a + b) / 2 for a, b in spans])
            msg = tr("무음 구간 {0}개 가운데에 마커 {1}개 추가").format(len(spans), n)
        if proj is self.current:
            self._set_loop(-1)
            self._changed()
        else:
            proj.dirty = True
            self._schedule_save()
        self.statusBar().showMessage(msg + tr(" (Ctrl+Z 로 되돌리기)"), 6000)

    # ---- 큰 소리 자동 마커 ----
    def auto_markers_loud(self):
        if not self.current:
            return
        if not self.current.info.get("has_audio"):
            QMessageBox.information(self, tr("큰 소리 마커"), tr("이 영상에는 오디오가 없습니다."))
            return
        wave = self.current.waveform
        if not wave:
            QMessageBox.information(self, tr("큰 소리 마커"), tr("파형 분석이 아직 끝나지 않았거나 오디오가 없습니다.\n잠시 뒤 다시 시도해 주세요."))
            return
        s = self.settings
        d = LoudDialog(self, float(s.value("loud_factor", 3.0)), float(s.value("loud_gap", 10.0)), float(s.value("loud_lead", 2.0)))
        if not d.exec():
            return
        s.setValue("loud_factor", d.factor)
        s.setValue("loud_gap", d.min_gap)
        s.setValue("loud_lead", d.lead)
        times = loud_peaks(wave, self.current.duration, factor=d.factor, min_gap=d.min_gap, lead=d.lead)
        if not times:
            self.statusBar().showMessage(tr("두드러지게 큰 소리를 찾지 못했습니다"), 5000)
            return
        self.current.push_undo()
        n = self.current.add_markers([self._snap(t) for t in times])
        self._set_loop(-1)
        self._changed()
        self.statusBar().showMessage(tr("큰 소리 {0}곳 → 마커 {1}개 추가 (Ctrl+Z 로 되돌리기)").format(len(times), n), 6000)

    # ---- 클립 모드 (I/O) ----
    def clip_in(self):
        if not self.current:
            return
        self.current.pending_in = self._snap(self.player.position)
        self.timeline.canvas.update()
        self.statusBar().showMessage(tr("클립 시작 {0} — 끝 지점에서 O (Esc 취소)").format(fmt_time(self.current.pending_in)), 6000)

    def clip_out(self):
        p = self.current
        if not p:
            return
        if p.pending_in is None:
            self.statusBar().showMessage(tr("먼저 I 로 클립 시작을 찍으세요"), 3000)
            return
        b = self._snap(self.player.position)
        a = p.pending_in
        if b < a:
            a, b = b, a
        p.push_undo()
        self.player.pause()
        ok = p.apply_clip(a, b)
        p.pending_in = None
        if ok:
            self._set_loop(-1)
            self._changed()
            n = len(p.enabled_segments())
            self.statusBar().showMessage(tr("클립 {0} ~ {1} 추가 (켜진 구간 {2}개, 나머지는 꺼짐)").format(fmt_time(a), fmt_time(b), n), 6000)
        else:
            self.timeline.canvas.update()
            self.statusBar().showMessage(tr("클립이 너무 짧습니다 (0.1초 이상)"), 3000)

    def clip_cancel(self):
        if self.current and self.current.pending_in is not None:
            self.current.pending_in = None
            self.timeline.canvas.update()
            self.statusBar().showMessage(tr("클립 시작 취소"), 2000)

    def copy_chapters(self):
        if not self.current:
            return
        text = self.current.chapter_text()
        if not text:
            self.statusBar().showMessage(tr("켜진 구간이 없습니다"), 3000)
            return
        QApplication.clipboard().setText(text)
        self.statusBar().showMessage(tr("챕터 {0}줄을 클립보드에 복사했습니다").format(text.count(chr(10)) + 1), 4000)

    # ---- 화면 저장 / 세로 크롭 ----
    def save_screenshot(self):
        if not self.current:
            return
        t = self.player.position
        try:
            data = ffmpeg_tools.grab_frame(self.current.path, t, "png")
        except Exception as ex:
            QMessageBox.warning(self, tr("화면 저장"), tr("프레임을 읽지 못했습니다.\n{0}").format(ex))
            return
        out = os.path.join(os.path.dirname(self.current.path), f"{self.current.stem}_{fmt_time_file(t)}.png")
        out = self._unique_path(out) if os.path.exists(out) else out
        with open(out, "wb") as f:
            f.write(data)
        self.statusBar().showMessage(tr("저장: {0}").format(os.path.basename(out)), 5000)

    def _on_output_changed(self, _i: int):
        vertical = self.cb_audio.currentData() == "vertical"
        self.btn_crop.setVisible(vertical)
        self.cb_layout.setVisible(vertical)
        self.cb_mode.setEnabled(not vertical)
        self.cb_mode.setToolTip(tr("세로 출력은 항상 재인코딩합니다") if vertical else self._mode_tip)
        mute = self.cb_audio.currentData() == "mute"
        self.cb_normalize.setEnabled(not mute)
        self.cb_normalize.setToolTip(tr("영상만 출력은 소리를 빼므로 음량 정규화를 하지 않습니다") if mute else self._normalize_tip)
        self._refresh_table()

    def choose_crop(self):
        if not self.current:
            return
        try:
            data = ffmpeg_tools.grab_frame(self.current.path, self.player.position, "jpeg")
        except Exception as ex:
            QMessageBox.warning(self, tr("크롭 위치"), tr("프레임을 읽지 못했습니다.\n{0}").format(ex))
            return
        pix = QPixmap()
        pix.loadFromData(data, "JPEG")
        d = CropDialog(self, pix, self.current.crop_x)
        if d.exec():
            self.current.crop_x = d.frac
            self._schedule_save()
            self.statusBar().showMessage(tr("세로 크롭 위치 {0:.0f}%").format(d.frac * 100), 3000)

    def choose_subtitle(self):
        start = os.path.dirname(self.current.path) if self.current else self.settings.value("last_dir", "")
        path, _ = QFileDialog.getOpenFileName(self, tr("자막 파일 선택"), start,
                                              tr("자막 파일 (*.srt *.ass *.ssa *.vtt);;모든 파일 (*)"))
        if path:
            self.ed_subtitle.setText(path)

    def edit_render_assets(self):
        d = RenderAssetsDialog(self, self.settings)
        if d.exec():
            d.save()
            self._refresh_table()

    def _render_kwargs(self, vertical: bool) -> dict:
        """내보내기 효과 옵션 → ExportJob 키워드 인자 (내보내기 패널 + 설정)."""
        s = self.settings
        try:
            opacity = float(s.value("wm_opacity", 0.8))
        except (TypeError, ValueError):
            opacity = 0.8
        return dict(
            normalize=self.cb_normalize.isChecked(),
            caption=self.ed_caption.text().strip(),
            subtitle_path=self.ed_subtitle.text().strip(),
            layout=(self.cb_layout.currentData() or "crop") if vertical else "crop",
            watermark=s.value("wm_path", "") or "",
            watermark_pos=s.value("wm_pos", "br") or "br",
            watermark_opacity=opacity,
            intro=s.value("intro_path", "") or "",
            outro=s.value("outro_path", "") or "",
        )

    def _needs_render(self) -> bool:
        """캡션 · 자막 · 워터마크가 있으면 재인코딩(.mp4) 출력."""
        return bool(self.ed_caption.text().strip() or self.ed_subtitle.text().strip() or self.settings.value("wm_path", ""))

    # ---- 타임스탬프 / 장면 전환 ----
    def paste_timestamps(self):
        if not self.current:
            return
        d = TimestampDialog(self, self.current.duration)
        d.text.setPlainText(QApplication.clipboard().text()[:20000])
        if not d.exec() or not d.times:
            return
        self.current.push_undo()
        n = self.current.add_markers([self._snap(t) for t in d.times])
        self._set_loop(-1)
        self._changed()
        self.statusBar().showMessage(tr("타임스탬프 {0}개 중 마커 {1}개 추가 (Ctrl+Z 로 되돌리기)").format(len(d.times), n), 6000)

    def chat_markers(self):
        """편집 ▸ 채팅 반응 그래프·마커… (Ctrl+Shift+C): 채팅을 받아 그래프를 그리고 반응 피크에 마커."""
        if not self.current:
            return
        proj = self.current
        s = self.settings
        d = ChatDialog(self, url=proj.source_url, duration=proj.duration, chat=proj.chat,
                       top_n=int(s.value("chat_top", 20)), min_gap=float(s.value("chat_gap", 60.0)),
                       keywords=s.value("chat_keywords", DEFAULT_KEYWORDS) or DEFAULT_KEYWORDS,
                       use_peaks=s.value("chat_use_peaks", "1") == "1",
                       use_keywords=s.value("chat_use_keywords", "0") == "1")
        ok = d.exec()
        # 받은 채팅은 취소해도 유지·저장 (다시 받지 않게) 하고 그래프를 바로 보여 준다
        if d.chat is not None and d.chat is not proj.chat:
            proj.chat = d.chat
            d.chat.save(proj.path)
            if d.url and not proj.source_url:
                proj.source_url = d.url
                proj.dirty = True
                self._schedule_save()
            self.timeline.canvas.update()
        s.setValue("chat_top", d.top_n)
        s.setValue("chat_gap", d.min_gap)
        s.setValue("chat_keywords", d.keywords)
        s.setValue("chat_use_peaks", "1" if d.use_peaks else "0")
        s.setValue("chat_use_keywords", "1" if d.use_keywords else "0")
        if not ok:
            return
        times = d.marker_times
        if not times:
            return
        proj.push_undo()
        n = proj.add_markers([self._snap(t) for t in times])
        self._set_loop(-1)
        self._changed()
        self.statusBar().showMessage(tr("채팅 반응 {0}곳 → 마커 {1}개 추가 (Ctrl+Z 로 되돌리기)").format(len(times), n), 6000)

    def auto_markers_scene(self):
        if not self.current:
            return
        if self.scene_worker and self.scene_worker.isRunning():
            return
        d = SceneDialog(self, float(self.settings.value("scene_th", 0.4)), float(self.settings.value("scene_gap", 2.0)))
        if not d.exec():
            return
        self.settings.setValue("scene_th", d.threshold)
        self.settings.setValue("scene_gap", d.min_gap)
        self.progress.setValue(0)
        self.progress.setFormat(tr("장면 전환 분석 %p%"))
        self.statusBar().showMessage(tr("장면 전환 분석 중… (내보내기 패널 진행률)"))
        self.scene_worker = SceneWorker(self.current.path, self.current.duration, d.threshold, d.min_gap, self)
        self.scene_worker.progress.connect(lambda f: self.progress.setValue(int(f * 1000)))
        self.scene_worker.done.connect(self._on_scene_done)
        self.scene_worker.start()

    def _on_scene_done(self, path: str, times: list):
        self.progress.setFormat("%p%")
        proj = self.projects.get(os.path.abspath(path))
        if not proj:
            return
        times = [t for t in times if 0.5 < t < proj.duration - 0.5]
        if not times:
            self.statusBar().showMessage(tr("장면 전환을 찾지 못했습니다. 민감도를 낮춰 보세요."), 5000)
            return
        proj.push_undo()
        n = proj.add_markers([self._snap(t) for t in times])
        if proj is self.current:
            self._set_loop(-1)
            self._changed()
        self.statusBar().showMessage(tr("장면 전환 {0}개 → 마커 {1}개 추가 (Ctrl+Z 로 되돌리기)").format(len(times), n), 6000)

    # ---- 업데이트 ----
    def _auto_check_updates(self):
        if not self.act_update.isChecked():
            return
        import time
        # 시작할 때마다 확인하되 1시간 안에는 다시 묻지 않는다 (같은 날 나온 새 버전도 바로 보이게)
        try:
            last = float(self.settings.value("last_update_check_ts", 0) or 0)
        except (TypeError, ValueError):
            last = 0.0
        if time.time() - last < 3600:
            return
        self.settings.setValue("last_update_check_ts", time.time())
        self.check_updates(manual=False)

    def check_updates(self, manual: bool):
        if self.update_worker and self.update_worker.isRunning():
            return
        self._update_manual = manual
        if manual:
            self.statusBar().showMessage(tr("업데이트 확인 중…"), 5000)
        self.update_worker = updater.UpdateCheckWorker(__version__, self)
        self.update_worker.result.connect(self._on_update_result)
        self.update_worker.start()

    def _on_update_result(self, rel):
        if not rel:
            if self._update_manual:
                QMessageBox.information(self, tr("업데이트 확인"), tr("지금 버전 {0} 이 최신입니다.\n(또는 확인에 실패했습니다 — 로그 참고)").format(__version__))
            return
        if not self._update_manual and self.settings.value("skip_version", "") == rel["version"]:
            return
        self.update_info = rel
        self.btn_update.setText(tr("⬆ 새 버전 {0}").format(rel['version']))
        self.btn_update.show()
        self.statusBar().showMessage(tr("새 버전 {0} 이 있습니다. 오른쪽 아래 버튼을 누르세요.").format(rel['version']), 8000)
        if self._update_manual:
            self.show_update_dialog()

    def show_update_dialog(self):
        if not self.update_info:
            return
        can, why = updater.can_self_update()
        if self.export_worker and self.export_worker.isRunning():
            can, why = False, tr("내보내기가 진행 중입니다. 끝난 뒤 다시 시도하세요")
        d = UpdateDialog(self, self.update_info, __version__,
                         lambda rel: updater.UpdateDownloadWorker(rel, self), can, why)
        d.exec()
        if d.action == "skip":
            self.settings.setValue("skip_version", self.update_info["version"])
            self.btn_update.hide()
        elif d.action == "update" and d.new_dir:
            self._apply_update(d.new_dir)

    def _apply_update(self, new_dir: str):
        others = updater.other_instances()
        if others:
            QMessageBox.warning(self, tr("업데이트"), tr("같은 폴더에서 ClipSlicer 창이 {0}개 더 열려 있습니다.\n"
                                                      "그 창들을 모두 닫은 뒤 다시 업데이트해 주세요 (열려 있으면 파일이 잠겨 교체가 실패합니다).").format(len(others)))
            return
        if QMessageBox.question(self, tr("업데이트"), tr("프로그램을 닫고 새 버전으로 교체한 뒤 다시 엽니다 (보통 10~30초).\n"
                                                      "다시 열릴 때까지 ClipSlicer 를 직접 실행하지 마세요.\n계속할까요?")) != QMessageBox.Yes:
            return
        try:
            updater.launch_replacer(new_dir, lite=updater.is_lite_dir(new_dir))
        except Exception as ex:
            LOG.exception("교체 스크립트 실행 실패")
            QMessageBox.critical(self, tr("업데이트"), tr("교체를 시작하지 못했습니다.\n{0}").format(ex))
            return
        self._updating = True
        self.close()

    def notify_startup_flag(self, flag: str):
        if flag == "--updated":
            self.statusBar().showMessage(tr("업데이트 완료 — ClipSlicer {0}").format(__version__), 10000)
            LOG.info("업데이트 완료 후 재시작")
        elif flag == "--update-blocked":
            QMessageBox.warning(self, tr("업데이트 보류"), tr("다른 ClipSlicer 창이 열려 있어 업데이트를 적용하지 않았습니다.\n"
                                                         "모든 ClipSlicer 창을 닫고 다시 업데이트해 주세요."))
        elif flag == "--update-failed":
            QMessageBox.warning(self, tr("업데이트 실패"), tr("파일 교체에 실패해 이전 버전으로 되돌렸습니다.\nlogs\\update.log 를 확인해 주세요."))

    # ---- 유튜브 ----
    def _yt_template(self) -> str:
        return self.settings.value("yt_desc_template", tr("{source} 에서 잘라낸 클립 ({start} ~ {end})")) or tr("{source} 에서 잘라낸 클립 ({start} ~ {end})")

    def edit_yt_template(self):
        from PySide6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getMultiLineText(
            self, tr("유튜브 설명 템플릿"),
            tr("올릴 때 설명란에 미리 채울 내용. 자리표시자: {title} {source} {start} {end} {n}"), self._yt_template())
        if ok:
            self.settings.setValue("yt_desc_template", text.strip() or tr("{source} 에서 잘라낸 클립 ({start} ~ {end})"))

    def _open_upload_for_jobs(self, jobs):
        files = []
        for j in jobs:
            proj = self.projects.get(j.src)
            seg_info = {"title": os.path.splitext(os.path.basename(j.dst))[0],
                        "source": proj.stem if proj else os.path.splitext(os.path.basename(j.src))[0],
                        "start": j.parts[0].start, "end": j.parts[-1].end, "n": ""}
            files.append((j.dst, seg_info))
        self._open_upload(files)

    def _open_upload(self, files):
        if not yt.is_connected():
            if QMessageBox.question(self, tr("유튜브"), tr("유튜브 계정이 연결되어 있지 않습니다. 지금 연결할까요?")) == QMessageBox.Yes:
                ConnectDialog(self).exec()
            if not yt.is_connected():
                return
        items = make_items(files, self._yt_template())
        UploadDialog(self, items, self.settings).exec()

    def upload_files_to_youtube(self):
        start = self.ed_outdir.text().strip() or (os.path.dirname(self.current.path) if self.current else "")
        paths, _ = QFileDialog.getOpenFileNames(self, tr("유튜브에 올릴 영상"), start, tr("영상 (*.mp4 *.mkv *.mov *.webm *.avi);;모든 파일 (*.*)"))
        if not paths:
            return
        files = [(p, {"title": os.path.splitext(os.path.basename(p))[0], "source": "", "start": 0.0, "end": 0.0, "n": ""}) for p in paths]
        self._open_upload(files)

    # ---- 디스코드 ----
    def _send_to_discord(self, jobs):
        cfg = discord.config(self.settings)
        if not discord.is_webhook_url(cfg["webhook"]):
            self._log(tr("디스코드: 웹훅 URL 이 없습니다. 설정 ▸ 디스코드 웹훅… 에서 등록하세요."))
            return
        ok_paths, too_big = discord.split_by_limit([j.dst for j in jobs], cfg["limit_mb"])
        for p, size in too_big:
            self._log(tr("디스코드 건너뜀 (한도 {0} MB 초과): {1} ({2:.1f} MB)").format(cfg["limit_mb"], os.path.basename(p), size / 1024 ** 2))
        if not ok_paths:
            return
        items = []
        for j in jobs:
            if j.dst in ok_paths:
                proj = self.projects.get(j.src)
                items.append((j.dst, {"title": os.path.splitext(os.path.basename(j.dst))[0],
                                      "source": proj.stem if proj else os.path.splitext(os.path.basename(j.src))[0]}))
        self._log(tr("디스코드로 {0}개 파일 보내는 중…").format(len(items)))
        self.discord_worker = discord.DiscordWorker(items, cfg["webhook"], cfg["limit_mb"], cfg["template"], parent=self)
        self.discord_worker.fileDone.connect(self._on_discord_file)
        self.discord_worker.allDone.connect(self._on_discord_done)
        self.discord_worker.start()

    def _on_discord_file(self, i: int, ok: bool, msg: str):
        name = os.path.basename(self.discord_worker.items[i][0])
        self._log(tr("디스코드 ✔ {0}").format(name) if ok else tr("디스코드 ✖ {0}: {1}").format(name, msg))

    def _on_discord_done(self, ok: int, fail: int):
        self._log(tr("디스코드 전송 완료 — 성공 {0}, 실패 {1}").format(ok, fail))
        self.statusBar().showMessage(tr("디스코드 전송 완료: 성공 {0}, 실패 {1}").format(ok, fail), 6000)

    # ---- URL 다운로드 ----
    def open_site_recorder(self, url: str = ""):
        """내장 브라우저로 방송 페이지를 열고 스트림을 잡아 녹화한다 (창은 하나만)."""
        try:
            from .sitebrowser import SiteRecordWindow
        except ImportError as ex:
            QMessageBox.warning(self, tr("사이트에서 녹화"), tr("내장 브라우저를 불러오지 못했습니다: {0}").format(ex))
            return
        w = getattr(self, "site_window", None)
        if w is None or not w.isVisible():
            w = SiteRecordWindow(self, self.settings, url)
            w.fileReady.connect(self._on_site_file)
            w.setAttribute(Qt.WA_DeleteOnClose)
            w.destroyed.connect(lambda *_: setattr(self, "site_window", None))
            self.site_window = w
        elif url:
            w.ed_url.setText(url)
            w._go()
        w.show()
        w.raise_()
        w.activateWindow()

    def _on_site_file(self, path: str, page: str):
        self.add_files([path])
        self.notifier.notify(tr("녹화 저장 완료"), os.path.basename(path))
        proj = self.projects.get(os.path.abspath(path))
        if proj and not proj.source_url:
            proj.source_url = page
            proj.dirty = True
            self._schedule_save()

    def open_url(self):
        default_dir = self.settings.value("dl_dir", "") or os.path.join(
            os.environ.get("USERPROFILE", os.path.expanduser("~")), "Videos", "ClipSlicer")
        d = DownloadDialog(self, lambda u, o, q, sec=None, ck="", ref="": DownloadWorker(u, o, q, sec, self, ck, ref),
                           default_dir, self.settings.value("dl_quality", "best"),
                           self.settings.value("dl_cookies", "") or "", self.settings.value("dl_referer", "") or "")
        d.siteRequested.connect(lambda u: (d.reject(), QTimer.singleShot(0, lambda: self.open_site_recorder(u))))
        accepted = d.exec()
        self.settings.setValue("dl_cookies", d.cookies)
        self.settings.setValue("dl_referer", d.referer)
        if accepted and d.result_path:
            self.settings.setValue("dl_dir", d.out_dir)
            self.settings.setValue("dl_quality", d.quality)
            self.add_files([d.result_path])
            self.notifier.notify(tr("다운로드 완료"), os.path.basename(d.result_path))
            proj = self.projects.get(os.path.abspath(d.result_path))
            if proj and not proj.source_url:
                proj.source_url = d.ed_url.text().strip()   # DownloadDialog 의 URL 입력칸 (dialogs.py)
                proj.dirty = True
                self._schedule_save()

    # ---- 방송 북마크 ----
    def show_bookmark_window(self):
        if self.bookmark_window is None:
            self.bookmark_window = BookmarkWindow(self, self.settings)
        self.bookmark_window.show()
        self.bookmark_window.raise_()
        self.bookmark_window.activateWindow()

    def import_bookmarks(self):
        if not self.current:
            return
        n = bookmarks.apply_to_project(self.current)
        if n == 0:
            QMessageBox.information(self, tr("북마크 가져오기"),
                                    tr("이 영상의 녹화 시간대에 기록된 북마크가 없습니다.\n(파일 수정 시각을 녹화 끝으로 보고 계산합니다)"))
            return
        self._set_loop(-1)
        self._changed()
        self.statusBar().showMessage(tr("북마크 {0}개를 마커로 가져왔습니다 (Ctrl+Z 로 되돌리기)").format(n), 6000)

    def _offer_bookmarks(self, path: str):
        """파일을 열었을 때 그 녹화 시간대의 북마크가 있으면 가져올지 묻는다."""
        proj = self.projects.get(path)
        if not proj:
            return
        new = [t for t, _ in bookmarks.bookmarks_for_file(path, proj.duration)
               if not any(abs(m - t) < 0.05 for m in proj.markers)]
        if not new:
            return
        if QMessageBox.question(self, tr("방송 북마크"),
                                tr("{0}\n이 영상이 녹화되던 시간에 기록한 북마크가 {1}개 있습니다. 마커로 가져올까요?")
                                .format(os.path.basename(path), len(new))) != QMessageBox.Yes:
            return
        n = bookmarks.apply_to_project(proj)
        if proj is self.current:
            self._set_loop(-1)
            self._changed()
        else:
            self._update_file_item(proj)
            self._schedule_save()
        self.statusBar().showMessage(tr("북마크 {0}개를 마커로 가져왔습니다 (Ctrl+Z 로 되돌리기)").format(n), 6000)

    # ---- 샘플 영상 / 처음 실행 ----
    def open_sample(self):
        dst = sample_path()  # <youtube.config_dir()>/samples/sample.mp4
        if os.path.isfile(dst):
            self.add_files([dst])
            return
        if self.sample_worker and self.sample_worker.isRunning():
            return
        self.statusBar().showMessage(tr("샘플 영상 만드는 중… (ffmpeg, 몇 초 걸립니다)"))
        self.sample_worker = SampleWorker(dst, self)
        self.sample_worker.done.connect(self._on_sample_done)
        self.sample_worker.start()

    def _on_sample_done(self, path: str, error: str):
        if not path:
            self.statusBar().clearMessage()
            QMessageBox.warning(self, tr("샘플 영상"), tr("샘플 영상을 만들지 못했습니다.\n{0}").format(error))
            return
        self.add_files([path])
        self.statusBar().showMessage(tr("샘플 영상을 열었습니다 — S 로 마커, I·O 로 클립, Ctrl+E 로 내보내기를 해 보세요"), 8000)

    def show_first_run(self):
        d = FirstRunDialog(self)
        d.sampleRequested.connect(self.open_sample)
        d.exec()
        self.settings.setValue("first_run_done", "1" if d.dont_show_again else "0")
        self.settings.sync()

    def _maybe_first_run(self):
        if FirstRunDialog.should_show(self.settings):
            self.show_first_run()

    # ---- 구간 반복 / 미리보기 ----
    def _set_loop(self, idx: int):
        self.loop_idx = idx
        self.preview_active = False
        self.btn_preview.setChecked(False)
        if idx < 0 or not self.current or idx >= len(self.current.segments):
            self.loop_idx = -1
            self.player.set_loop(None, None)
        else:
            seg = self.current.segments[idx]
            self.player.set_loop(seg.start, seg.end)
        self.timeline.canvas.set_loop_segment(self.loop_idx)
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
            self.statusBar().showMessage(tr("구간 {0} 반복 재생 (L 또는 더블클릭으로 해제)").format(idx + 1), 3000)

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

    def toggle_preview_around(self):
        if not self.current:
            return
        if self.preview_active:
            self._set_loop(-1)
            self.player.pause()
            return
        pos = self.player.position
        a, b = max(0.0, pos - 2.0), min(self.current.duration, pos + 2.0)
        self._set_loop(-1)
        self.preview_active = True
        self.btn_preview.setChecked(True)
        self.player.set_loop(a, b)
        self.player.seek(a)
        if self.player.paused:
            self.player.toggle_pause()
        self.statusBar().showMessage(tr("{0} ~ {1} 반복 중 (R 로 해제)").format(fmt_time(a), fmt_time(b)), 3000)

    def _on_preview_button(self, checked: bool):
        if checked and not self.preview_active:
            self.toggle_preview_around()
        elif not checked and self.preview_active:
            self.toggle_preview_around()

    # ---- 테이블 ----
    def _mode(self) -> str:
        return self.cb_mode.currentData() or "fast"

    def _output_ext(self) -> str:
        audio = self.cb_audio.currentData()
        if audio == "aac":
            return ".m4a"
        if audio == "mp3":
            return ".mp3"
        if audio == "vertical":
            return ".mp4"
        if self._mode() == "precise" or self._needs_render():
            return ".mp4"
        return self.current.ext if self.current else ".mp4"

    def _refresh_table(self):
        self._table_updating = True
        self.table.setRowCount(0)
        if self.current:
            ext = self._output_ext()
            merge = self.cb_merge.isChecked()
            for i, s in enumerate(self.current.segments):
                self.table.insertRow(i)
                use = QTableWidgetItem()
                use.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                use.setCheckState(Qt.Checked if s.enabled else Qt.Unchecked)
                self.table.setItem(i, COL_USE, use)
                no = QTableWidgetItem(str(i + 1))
                no.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                no.setTextAlignment(Qt.AlignCenter)
                c = seg_color(i) if s.enabled else QColor(70, 70, 76)
                no.setBackground(QBrush(c))
                no.setForeground(QBrush(QColor(0, 0, 0) if s.enabled else QColor(160, 160, 160)))
                self.table.setItem(i, COL_NO, no)
                for col, text in ((COL_START, fmt_time(s.start)), (COL_END, fmt_time(s.end)), (COL_DUR, fmt_time(s.duration))):
                    it = QTableWidgetItem(text)
                    it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    self.table.setItem(i, col, it)
                if merge:
                    name = QTableWidgetItem(tr("(합쳐짐)") if s.enabled else "")
                    name.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                    name.setForeground(Qt.gray)
                else:
                    name = QTableWidgetItem(self.current.output_name(i, ext, self.pattern))
                    name.setToolTip(tr("더블클릭해서 파일명 변경 (비우면 자동 이름)"))
                    if not s.name:
                        name.setForeground(Qt.gray)
                self.table.setItem(i, COL_NAME, name)
                note = QTableWidgetItem(s.note)
                note.setToolTip(tr("더블클릭해서 메모 입력 (파일명·내보내기에는 영향 없음)"))
                if not s.note:
                    note.setForeground(Qt.gray)
                self.table.setItem(i, COL_NOTE, note)
                self.table.setCellWidget(i, COL_ORDER, self._make_order_widget(i, s.enabled, merge))
                if not s.enabled:
                    for col in (COL_START, COL_END, COL_DUR, COL_NAME, COL_NOTE):
                        self.table.item(i, col).setForeground(Qt.darkGray)
            self.table.setColumnHidden(COL_ORDER, not merge)
            self._hl_row = -1
            self._highlight_row(self.current.segment_at(self.player.position))
            self._update_file_item(self.current)
        self._table_updating = False

    def _make_order_widget(self, row: int, enabled: bool, merge: bool) -> QWidget:
        """합치기 순서 칸: '3 ▲ ▼' (순번은 켜진 구간만, 꺼진 구간은 '–')."""
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(2, 0, 2, 0)
        lay.setSpacing(0)
        pos = self.current.merge_position(row) if self.current else -1
        lab = QLabel(str(pos + 1) if pos >= 0 else "–")
        lab.setAlignment(Qt.AlignCenter)
        lab.setMinimumWidth(18)
        lay.addWidget(lab)
        for text, delta, tip in (("▲", -1, tr("합치기 순서에서 앞으로")), ("▼", 1, tr("합치기 순서에서 뒤로"))):
            b = QToolButton(w)
            b.setText(text)
            b.setAutoRaise(True)
            b.setFocusPolicy(Qt.NoFocus)
            b.setToolTip(tip)
            b.setEnabled(merge and enabled)
            b.clicked.connect(lambda _c=False, r=row, d=delta: self._move_segment_order(r, d))
            lay.addWidget(b)
        return w

    def _move_segment_order(self, row: int, delta: int):
        """구간 row 를 합치기 순서에서 delta 칸 이동 (실행 취소 가능)."""
        if not self.current or not (0 <= row < len(self.current.segments)):
            return
        pos = self.current.merge_position(row)
        n = len(self.current.ordered_enabled())
        if pos < 0 or not (0 <= pos + delta < n):
            return
        self.current.push_undo()
        self.current.move_in_order(row, delta)
        self._changed()
        self.table.selectRow(row)

    def _highlight_row(self, idx: int):
        base = QBrush()
        hl = QBrush(QColor(66, 165, 245, 40))
        for row in (self._hl_row, idx):
            if 0 <= row < self.table.rowCount():
                for col in (COL_USE, COL_START, COL_END, COL_DUR, COL_NAME, COL_NOTE):
                    it = self.table.item(row, col)
                    if it:
                        it.setBackground(hl if row == idx else base)
        self._hl_row = idx

    def _on_table_item_changed(self, item: QTableWidgetItem):
        if self._table_updating or not self.current:
            return
        row = item.row()
        if row >= len(self.current.segments):
            return
        seg = self.current.segments[row]
        if item.column() == COL_USE:
            self.current.push_undo()
            seg.enabled = item.checkState() == Qt.Checked
            self._changed()
        elif item.column() == COL_NAME:
            text = os.path.splitext(item.text().strip())[0]
            auto = self.current.auto_name(row, self.pattern)
            new = "" if text in ("", auto) else text
            if new != seg.name:
                self.current.push_undo()
                seg.name = new
                self._changed()
            else:
                self._refresh_table()
        elif item.column() == COL_NOTE:
            new = item.text().strip()
            if new != seg.note:
                self.current.push_undo()
                seg.note = new
                self._changed()
            else:
                self._refresh_table()
        self.setFocus()

    def _on_table_cell_clicked(self, row: int, col: int):
        if self.current and 0 <= row < len(self.current.segments) and col != COL_USE:
            self.player.seek(self.current.segments[row].start)

    def _on_table_cell_double_clicked(self, row: int, col: int):
        if col not in (COL_NAME, COL_NOTE) and self.current and 0 <= row < len(self.current.segments):
            self.toggle_loop_segment(row)

    # ------------------------------------------------------------ 내보내기
    def choose_outdir(self):
        d = QFileDialog.getExistingDirectory(self, tr("출력 폴더"), self.ed_outdir.text() or "")
        if d:
            self.ed_outdir.setText(d)

    def _out_dir_for(self, proj: ClipProject) -> str:
        custom = self.ed_outdir.text().strip()
        return custom if custom else os.path.join(os.path.dirname(proj.path), f"{proj.stem}_cuts")

    def _build_jobs(self, projects: list[ClipProject]) -> list[ExportJob]:
        mode = self._mode()
        out_kind = self.cb_audio.currentData()
        vertical = out_kind == "vertical"
        mute = out_kind == "mute"
        audio = "" if vertical or mute else out_kind
        merge = self.cb_merge.isChecked()
        gpu = self.gpu_encoder if self.act_gpu.isChecked() else None
        fx = self._render_kwargs(vertical)
        if mute:
            fx["normalize"] = False
        needs_render = not audio and bool(fx["caption"] or fx["subtitle_path"] or fx["watermark"])
        jobs: list[ExportJob] = []
        for proj in projects:
            if audio:
                ext = ".m4a" if audio == "aac" else ".mp3"
            elif mode == "precise" or vertical or needs_render:
                ext = ".mp4"
            else:
                ext = proj.ext
            vert = proj.crop_x if vertical else None
            outdir = self._out_dir_for(proj)
            segs = proj.ordered_enabled() if merge else proj.enabled_segments()
            if not segs:
                continue
            if merge:
                dst = os.path.join(outdir, f"{proj.stem}_merged{ext}")
                jobs.append(ExportJob(proj.path, proj.info, proj.keyframes,
                                      [ExportPart(s.start, s.end) for _, s in segs], dst, mode, audio, vert, gpu, mute=mute, **fx))
            else:
                for i, seg in segs:
                    dst = os.path.join(outdir, proj.output_name(i, ext, self.pattern))
                    if os.path.abspath(dst) == os.path.abspath(proj.path):
                        dst = os.path.join(outdir, f"{proj.stem}_cut{ext}")
                    jobs.append(ExportJob(proj.path, proj.info, proj.keyframes,
                                          [ExportPart(seg.start, seg.end)], dst, mode, audio, vert, gpu, mute=mute, **fx))
        return jobs

    @staticmethod
    def _unique_path(path: str) -> str:
        base, ext = os.path.splitext(path)
        n = 1
        while os.path.exists(f"{base}_{n}{ext}"):
            n += 1
        return f"{base}_{n}{ext}"

    def start_export(self, all_files: bool):
        if self.export_worker and self.export_worker.isRunning():
            return
        projects = list(self.projects.values()) if all_files else ([self.current] if self.current else [])
        jobs = self._build_jobs([p for p in projects if p])
        if not jobs:
            QMessageBox.information(self, tr("내보내기"), tr("내보낼 구간이 없습니다.\n타임라인에서 S 키로 마커를 찍거나, 구간을 켜 주세요."))
            return
        existing = [j.dst for j in jobs if os.path.exists(j.dst)]
        if existing:
            choice = ask_overwrite(self, [os.path.basename(p) for p in existing])
            if choice == "cancel":
                return
            if choice == "rename":
                for j in jobs:
                    if os.path.exists(j.dst):
                        j.dst = self._unique_path(j.dst)
        self.player.pause()
        self.log.clear()
        mode_name = {"fast": tr("빠르게"), "smart": tr("스마트"), "precise": tr("정확하게")}[jobs[0].mode]
        extra = []
        if jobs[0].audio:
            extra.append(tr("오디오만"))
        if jobs[0].mute:
            extra.append(tr("영상만"))
        if jobs[0].vertical is not None:
            extra.append(tr("세로 9:16"))
        if self.cb_merge.isChecked():
            extra.append(tr("합치기"))
        if jobs[0].normalize:
            extra.append(tr("음량 정규화"))
        if jobs[0].has_overlays:
            extra.append(tr("캡션/자막/워터마크"))
        if (jobs[0].intro or jobs[0].outro) and jobs[0].needs_encode:
            extra.append(tr("인트로/아웃트로"))
        if jobs[0].gpu and (jobs[0].mode != "fast" or jobs[0].needs_encode) and not jobs[0].audio:
            extra.append(jobs[0].gpu)
        self._log(tr("{0}개 작업 시작 — {1}").format(len(jobs), mode_name) + (f" ({', '.join(extra)})" if extra else ""))
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
            self._log(tr("취소 요청…"))

    def _set_export_running(self, running: bool):
        self.btn_export_cur.setEnabled(not running)
        self.btn_export_all.setEnabled(not running)
        self.btn_cancel.setEnabled(running)

    def _on_job_started(self, i: int, label: str):
        self.progress.setFormat(f"[{i + 1}/{self._job_total}] {label}  %p%")
        self._update_export_chip(i, 0.0)

    def _on_job_progress(self, i: int, frac: float):
        self.progress.setValue(int((i + frac) / self._job_total * 1000))
        self._update_export_chip(i, frac)

    def _update_export_chip(self, i: int, frac: float):
        """상태 표시줄 칩: '내보내기 3/12 45%' (전체 진행률)."""
        total = max(1, self._job_total)
        pct = int((i + max(0.0, min(1.0, frac))) / total * 100)
        self.lbl_export.setText(tr("내보내기 {0}/{1} {2}%").format(i + 1, total, pct))

    def _on_job_finished(self, i: int, ok: bool, msg: str):
        job = self.export_worker.jobs[i] if self.export_worker else None
        label = job.label if job else str(i)
        dur = fmt_time(job.total_duration, ms=False) if job else ""
        if ok:
            self._log(f"✔ {label}  ({dur}, {msg})")
        else:
            self._log(f"✖ {label}\n   {msg}")

    def _on_export_finished(self, ok_n: int, fail_n: int):
        self._set_export_running(False)
        if fail_n == 0:
            self.progress.setValue(1000)
        self.progress.setFormat(tr("완료: 성공 {0}, 실패 {1}").format(ok_n, fail_n))
        self._log(tr("완료 — 성공 {0}, 실패 {1}").format(ok_n, fail_n))
        self.statusBar().showMessage(tr("내보내기 완료: 성공 {0}, 실패 {1}").format(ok_n, fail_n), 6000)
        self.lbl_export.setText("")
        self.notifier.notify(tr("내보내기 완료"), tr("성공 {0}, 실패 {1}").format(ok_n, fail_n))
        if self.cb_open.isChecked() and ok_n and self._export_dirs and not self.cb_youtube.isChecked():
            for d in self._export_dirs[:3]:
                try:
                    os.startfile(d)
                except OSError:
                    subprocess.Popen(["explorer", d])
        if self.cb_youtube.isChecked() and ok_n and self.export_worker:
            done = [(j, i) for i, j in enumerate(self.export_worker.jobs) if os.path.exists(j.dst) and not j.audio]
            if done:
                QTimer.singleShot(200, lambda: self._open_upload_for_jobs([j for j, _ in done]))
        if self.cb_discord.isChecked() and ok_n and self.export_worker:
            self._send_to_discord([j for j in self.export_worker.jobs if os.path.exists(j.dst)])

    def _log(self, text: str):
        self.log.appendPlainText(text)
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())
