"""시작 화면: 영상이 없을 때 플레이어 자리에 보이는 안내 + 열기 버튼 + '최근 작업 이어서' 목록."""
from __future__ import annotations

from .i18n import tr
import json
import logging
import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QToolButton, QMenu

from .segments import PROJECT_SUFFIX

LOG = logging.getLogger("clipslicer")
MAX_RECENT_BUTTONS = 5

PANEL_QSS = """
QWidget#startPanel { background: #0e0e11; border: 1px dashed #3a3a44; border-radius: 6px; }
QWidget#startPanel QLabel { background: transparent; border: none; }
QLabel#startIcon { font-size: 46px; }
QLabel#startTitle { color: #dfe3e8; font-size: 18px; font-weight: bold; }
QLabel#startHint { color: #7d848c; font-size: 12px; }
QLabel#startRecentTitle { color: #9aa0a6; font-size: 12px; font-weight: bold; padding-top: 10px; }
QPushButton#startBtn { padding: 7px 16px; font-size: 13px; }
QPushButton#recentBtn { text-align: left; padding: 7px 14px; background: #1c1c20; border: 1px solid #38383f; }
QPushButton#recentBtn:hover { background: #2a2a30; border-color: #42a5f5; }
QToolButton#recentDel { color: #7d848c; background: transparent; border: none; padding: 2px 6px; font-size: 14px; }
QToolButton#recentDel:hover { color: #ef9a9a; }
"""


def project_summary(video: str) -> str:
    """<video>.clipslicer.json 을 읽어 '마커 n개 · 켜진 구간 m개'. 작업 파일이 없거나 깨졌으면 ''."""
    try:
        with open(video + PROJECT_SUFFIX, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return ""
    if not isinstance(data, dict):
        return ""
    markers = data.get("markers") or []
    n = len(markers) if isinstance(markers, list) else 0
    segs = data.get("segments")
    if isinstance(segs, list) and segs:
        m = sum(1 for s in segs if isinstance(s, dict) and bool(s.get("enabled", True)))
    else:
        m = n + 1
    return tr("마커 {0}개 · 켜진 구간 {1}개").format(n, m)


class StartPanel(QWidget):
    """빈 상태 안내. 빈 곳 클릭 → openRequested, 버튼 → open/url/sample, 최근 항목 → fileRequested(path).

    최근 항목마다 × (목록에서 빼기) 와 우클릭 메뉴(목록에서 빼기 · 폴더에서 보기 · 작업 파일 삭제)가 있다.
    """
    openRequested = Signal()
    urlRequested = Signal()
    sampleRequested = Signal()
    fileRequested = Signal(str)
    removeRequested = Signal(str)   # 최근 목록에서만 빼기
    revealRequested = Signal(str)   # 탐색기에서 보기
    forgetRequested = Signal(str)   # 작업 파일 · 캐시 삭제 (영상은 그대로)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("startPanel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(PANEL_QSS)
        self.recent_buttons: list[QPushButton] = []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(6)
        lay.addStretch(2)

        icon = QLabel("🎬")
        icon.setObjectName("startIcon")
        icon.setAlignment(Qt.AlignCenter)
        lay.addWidget(icon)
        title = QLabel(tr("영상을 여기에 끌어다 놓으세요"))
        title.setObjectName("startTitle")
        title.setAlignment(Qt.AlignCenter)
        lay.addWidget(title)
        hint = QLabel(tr("또는 클릭해서 파일 열기 (Ctrl+O)<br><br>재생하다가 자를 지점에서 <b>S</b> &nbsp;·&nbsp; <b>I</b>·<b>O</b> 로 클립 &nbsp;·&nbsp; 내보내기 <b>Ctrl+E</b> &nbsp;·&nbsp; 도움말 <b>F1</b>"))
        hint.setObjectName("startHint")
        hint.setAlignment(Qt.AlignCenter)
        hint.setTextFormat(Qt.RichText)
        hint.setWordWrap(True)   # 창을 좁히면 줄바꿈 (한 줄 고정이면 창 최소 폭을 키운다)
        title.setWordWrap(True)
        lay.addWidget(hint)
        lay.addSpacing(10)

        row = QHBoxLayout()
        row.addStretch(1)
        self.b_open = self._button(tr("파일 열기"), tr("영상 파일 선택 (Ctrl+O)"), self.openRequested)
        self.b_url = self._button(tr("URL 에서 열기"), tr("유튜브 · 치지직 · 트위치 등 주소로 받기 (Ctrl+L)"), self.urlRequested)
        self.b_sample = self._button(tr("샘플 영상으로 둘러보기"), tr("ffmpeg 로 30초짜리 연습용 영상을 만들어 엽니다"), self.sampleRequested)
        for b in (self.b_open, self.b_url, self.b_sample):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)

        self.recent_box = QWidget()
        self.recent_box.setMaximumWidth(640)
        self.recent_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        rl = QVBoxLayout(self.recent_box)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(4)
        self.lbl_recent = QLabel(tr("최근 작업 이어서"))
        self.lbl_recent.setObjectName("startRecentTitle")
        rl.addWidget(self.lbl_recent)
        self.recent_layout = QVBoxLayout()
        self.recent_layout.setSpacing(4)
        rl.addLayout(self.recent_layout)
        lay.addWidget(self.recent_box, 0, Qt.AlignHCenter)
        self.recent_box.hide()
        lay.addStretch(3)

    def _button(self, text: str, tip: str, signal) -> QPushButton:
        b = QPushButton(text)
        b.setObjectName("startBtn")
        b.setToolTip(tip)
        b.setCursor(Qt.PointingHandCursor)
        b.setFocusPolicy(Qt.NoFocus)
        b.clicked.connect(lambda _c=False: signal.emit())
        return b

    # ---- 최근 작업 ----
    def set_recent(self, paths: list[str]):
        """존재하는 파일만, 최대 5개. 각 버튼은 작업 파일 요약을 같이 보여 준다."""
        for b in self.recent_buttons:
            row = b.parentWidget()
            self.recent_layout.removeWidget(row)
            row.deleteLater()
        self.recent_buttons = []
        seen: set[str] = set()
        for p in paths or []:
            if not isinstance(p, str) or p in seen or not os.path.isfile(p):
                continue
            seen.add(p)
            summary = project_summary(p)
            name = os.path.basename(p)
            label = f"📝 {name} — {summary}" if summary else f"🎞 {name}"
            b = QPushButton(label)
            b.setObjectName("recentBtn")
            b.setToolTip(p)
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
            # 긴 파일 이름이 창 최소 폭을 키우지 않게: 좁으면 글자가 잘려 보이고 전체 경로는 툴팁으로
            b.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            b.setMinimumWidth(160)
            b.clicked.connect(lambda _c=False, p=p: self.fileRequested.emit(p))
            b.setContextMenuPolicy(Qt.CustomContextMenu)
            b.customContextMenuRequested.connect(lambda pos, b=b, p=p: self._recent_menu(b, pos, p))
            row = QWidget()
            hl = QHBoxLayout(row)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(2)
            hl.addWidget(b, 1)
            x = QToolButton()
            x.setObjectName("recentDel")
            x.setText("✕")
            x.setToolTip(tr("최근 목록에서 빼기 (파일은 그대로)"))
            x.setCursor(Qt.PointingHandCursor)
            x.setFocusPolicy(Qt.NoFocus)
            x.clicked.connect(lambda _c=False, p=p: self.removeRequested.emit(p))
            hl.addWidget(x)
            self.recent_layout.addWidget(row)
            self.recent_buttons.append(b)
            if len(self.recent_buttons) >= MAX_RECENT_BUTTONS:
                break
        self.recent_box.setVisible(bool(self.recent_buttons))

    def _recent_menu(self, button: QPushButton, pos, path: str):
        m = QMenu(self)
        m.addAction(tr("열기"), lambda: self.fileRequested.emit(path))
        m.addAction(tr("최근 목록에서 빼기"), lambda: self.removeRequested.emit(path))
        m.addAction(tr("폴더에서 보기"), lambda: self.revealRequested.emit(path))
        m.addSeparator()
        m.addAction(tr("작업 파일 · 분석 캐시 삭제 (영상은 그대로)…"), lambda: self.forgetRequested.emit(path))
        m.exec(button.mapToGlobal(pos))

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.openRequested.emit()
            e.accept()
            return
        super().mousePressEvent(e)
