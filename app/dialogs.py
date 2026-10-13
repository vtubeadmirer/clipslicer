"""대화상자: 무음 마커, 덮어쓰기, 파일명 규칙, 타임스탬프 붙여넣기, 장면 전환, 세로 크롭 위치, URL 다운로드."""
from __future__ import annotations

from .i18n import tr
import os

from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtGui import QPixmap, QPainter, QColor, QPen
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QDoubleSpinBox, QRadioButton,
    QDialogButtonBox, QLineEdit, QMessageBox, QGroupBox, QPushButton, QPlainTextEdit, QComboBox,
    QProgressBar, QWidget, QToolButton, QFileDialog,
)

from .segments import DEFAULT_PATTERN, parse_timestamps, fmt_time, parse_time


def _buttons(dialog, ok_text=tr("확인")):
    bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    bb.button(QDialogButtonBox.Ok).setText(ok_text)
    bb.button(QDialogButtonBox.Cancel).setText(tr("취소"))
    bb.accepted.connect(dialog.accept)
    bb.rejected.connect(dialog.reject)
    return bb


class SilenceDialog(QDialog):
    """무음 구간 감지 조건과 마커 배치 방식."""

    def __init__(self, parent=None, noise_db: float = -35.0, min_dur: float = 1.0):
        super().__init__(parent)
        self.setWindowTitle(tr("무음 구간에 자동 마커"))
        lay = QVBoxLayout(self)
        intro = QLabel(tr("소리가 거의 없는 구간을 찾아 그 위치에 마커를 넣습니다.\n강의·방송 녹화처럼 말이 끊기는 지점으로 나누고 싶을 때 쓰세요."))
        intro.setWordWrap(True)
        lay.addWidget(intro)
        form = QFormLayout()
        self.sp_db = QDoubleSpinBox()
        self.sp_db.setRange(-80, 0)
        self.sp_db.setSingleStep(5)
        self.sp_db.setValue(noise_db)
        self.sp_db.setSuffix(" dB")
        self.sp_db.setToolTip(tr("이 값보다 작은 소리는 '무음'으로 봅니다. -35dB 가 무난하고, 잡음이 많으면 -25dB 정도로 올리세요."))
        form.addRow(tr("무음 기준 음량"), self.sp_db)
        self.sp_dur = QDoubleSpinBox()
        self.sp_dur.setRange(0.2, 60)
        self.sp_dur.setSingleStep(0.5)
        self.sp_dur.setValue(min_dur)
        self.sp_dur.setSuffix(tr(" 초"))
        form.addRow(tr("최소 무음 길이"), self.sp_dur)
        lay.addLayout(form)
        grp = QGroupBox(tr("마커 배치"))
        gl = QVBoxLayout(grp)
        self.rb_middle = QRadioButton(tr("무음 구간 가운데에 마커 1개 (깔끔하게 나누기)"))
        self.rb_edges = QRadioButton(tr("무음 구간 양쪽 끝에 마커 2개, 무음 구간은 끄기 (무음 잘라내기)"))
        self.rb_middle.setChecked(True)
        gl.addWidget(self.rb_middle)
        gl.addWidget(self.rb_edges)
        lay.addWidget(grp)
        lay.addWidget(_buttons(self, tr("찾기")))

    @property
    def noise_db(self) -> float:
        return self.sp_db.value()

    @property
    def min_dur(self) -> float:
        return self.sp_dur.value()

    @property
    def mode(self) -> str:
        return "edges" if self.rb_edges.isChecked() else "middle"


class SceneDialog(QDialog):
    """장면 전환 감지 조건."""

    def __init__(self, parent=None, threshold: float = 0.4, min_gap: float = 2.0):
        super().__init__(parent)
        self.setWindowTitle(tr("장면 전환에 자동 마커"))
        lay = QVBoxLayout(self)
        intro = QLabel(tr("화면이 크게 바뀌는 지점(컷 편집점, 화면 전환)을 찾아 마커를 넣습니다.\n영상 전체를 훑기 때문에 길이에 따라 수십 초~몇 분 걸립니다."))
        intro.setWordWrap(True)
        lay.addWidget(intro)
        form = QFormLayout()
        self.sp_th = QDoubleSpinBox()
        self.sp_th.setRange(0.05, 1.0)
        self.sp_th.setSingleStep(0.05)
        self.sp_th.setValue(threshold)
        self.sp_th.setToolTip(tr("낮을수록 작은 변화도 잡습니다. 0.3~0.5 가 보통. 너무 많이 잡히면 올리세요."))
        form.addRow(tr("민감도 (0~1, 낮을수록 많이)"), self.sp_th)
        self.sp_gap = QDoubleSpinBox()
        self.sp_gap.setRange(0.2, 120)
        self.sp_gap.setSingleStep(0.5)
        self.sp_gap.setValue(min_gap)
        self.sp_gap.setSuffix(tr(" 초"))
        self.sp_gap.setToolTip(tr("이 간격보다 가까운 전환은 하나로 칩니다."))
        form.addRow(tr("마커 최소 간격"), self.sp_gap)
        lay.addLayout(form)
        lay.addWidget(_buttons(self, tr("찾기")))

    @property
    def threshold(self) -> float:
        return self.sp_th.value()

    @property
    def min_gap(self) -> float:
        return self.sp_gap.value()


class TimestampDialog(QDialog):
    """텍스트에서 시각(12:34, 1:02:03 …)을 찾아 마커로."""

    def __init__(self, parent=None, duration: float = 0.0):
        super().__init__(parent)
        self.setWindowTitle(tr("타임스탬프 붙여넣기 → 마커"))
        self.duration = duration
        self.resize(520, 420)
        lay = QVBoxLayout(self)
        intro = QLabel(tr("유튜브 챕터 목록, 댓글 타임라인 등 시각이 적힌 텍스트를 붙여넣으세요.\n<code>12:34</code>, <code>1:02:03</code>, <code>0:45.5</code> 형식을 모두 찾아 마커로 만듭니다."))
        intro.setTextFormat(Qt.RichText)
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText(tr("0:00 인트로\n3:12 본편 시작\n15:40 하이라이트\n…"))
        self.text.textChanged.connect(self._update)
        lay.addWidget(self.text, 1)
        self.preview = QLabel("")
        self.preview.setWordWrap(True)
        self.preview.setStyleSheet("color: #8ab;")
        lay.addWidget(self.preview)
        self.bb = _buttons(self, tr("마커 추가"))
        lay.addWidget(self.bb)
        self._update()

    def _update(self):
        ts = [t for t in parse_timestamps(self.text.toPlainText()) if 0 < t < (self.duration or 1e12)]
        self._times = ts
        if ts:
            shown = ", ".join(fmt_time(t, ms=False) for t in ts[:12]) + (" …" if len(ts) > 12 else "")
            self.preview.setText(tr("{0}개 발견: {1}").format(len(ts), shown))
        else:
            self.preview.setText(tr("시각을 찾지 못했습니다. (0초나 영상 길이 밖의 값은 제외)"))
        self.bb.button(QDialogButtonBox.Ok).setEnabled(bool(ts))

    @property
    def times(self) -> list[float]:
        return self._times


class PatternDialog(QDialog):
    """출력 파일명 규칙."""

    def __init__(self, parent=None, pattern: str = DEFAULT_PATTERN):
        super().__init__(parent)
        self.setWindowTitle(tr("파일명 규칙"))
        lay = QVBoxLayout(self)
        help_text = QLabel(
            tr("저장되는 파일 이름을 정하는 규칙입니다. 아래 자리표시자를 조합하세요.\n\n  {name}   원본 파일 이름 (확장자 제외)\n  {n}      구간 번호 (01, 02 …)\n  {start}  구간 시작 시각 (예: 01m23s)\n  {end}    구간 끝 시각\n  {dur}    구간 길이\n\n구간 목록에서 파일명을 직접 입력한 구간은 그 이름이 우선합니다.")
        )
        help_text.setStyleSheet("font-family: Consolas, monospace;")
        lay.addWidget(help_text)
        row = QHBoxLayout()
        self.ed = QLineEdit(pattern)
        row.addWidget(QLabel(tr("규칙")))
        row.addWidget(self.ed, 1)
        lay.addLayout(row)
        self.preview = QLabel()
        self.preview.setStyleSheet("color: #8ab;")
        lay.addWidget(self.preview)
        self.ed.textChanged.connect(self._update_preview)
        self._update_preview()
        btns = QHBoxLayout()
        b_reset = QPushButton(tr("기본값"))
        b_reset.clicked.connect(lambda: self.ed.setText(DEFAULT_PATTERN))
        btns.addWidget(b_reset)
        btns.addStretch(1)
        btns.addWidget(_buttons(self))
        lay.addLayout(btns)

    def _update_preview(self):
        sample = {"name": tr("방송녹화"), "n": "03", "start": "12m05s", "end": "15m40s", "dur": "03m35s"}
        try:
            self.preview.setText(tr("예: ") + self.ed.text().format(**sample) + ".mp4")
        except (KeyError, IndexError, ValueError):
            self.preview.setText(tr("규칙이 올바르지 않습니다. 중괄호 안 이름을 확인하세요."))

    @property
    def pattern(self) -> str:
        p = self.ed.text().strip()
        try:
            p.format(name="a", n="01", start="0", end="0", dur="0")
        except (KeyError, IndexError, ValueError):
            return DEFAULT_PATTERN
        return p or DEFAULT_PATTERN


class CropPreview(QWidget):
    """프레임 위에서 9:16 크롭 창을 좌우(또는 상하)로 드래그."""
    changed = Signal(float)

    def __init__(self, pix: QPixmap, frac: float = 0.5):
        super().__init__()
        self.pix = pix
        self.frac = frac
        self.setMinimumSize(480, 270)
        self.setCursor(Qt.SizeHorCursor)

    def _geom(self):
        w, h = self.width(), self.height()
        pw, ph = self.pix.width(), self.pix.height()
        scale = min(w / pw, h / ph)
        dw, dh = pw * scale, ph * scale
        ox, oy = (w - dw) / 2, (h - dh) / 2
        if dw / dh > 9 / 16:
            cw, ch = dh * 9 / 16, dh
            cx, cy = ox + (dw - cw) * self.frac, oy
        else:
            cw, ch = dw, dw * 16 / 9
            cx, cy = ox, oy + (dh - ch) * self.frac
        return QRectF(ox, oy, dw, dh), QRectF(cx, cy, cw, ch)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0))
        img, crop = self._geom()
        p.drawPixmap(img.toRect(), self.pix)
        p.fillRect(img, QColor(0, 0, 0, 140))
        p.setClipRect(crop)
        p.drawPixmap(img.toRect(), self.pix)
        p.setClipping(False)
        p.setPen(QPen(QColor(255, 235, 59), 2))
        p.drawRect(crop)

    def _set_from_pos(self, x, y):
        img, crop = self._geom()
        if img.width() / img.height() > 9 / 16:
            free = img.width() - crop.width()
            self.frac = 0.5 if free <= 0 else min(1.0, max(0.0, (x - img.left() - crop.width() / 2) / free))
        else:
            free = img.height() - crop.height()
            self.frac = 0.5 if free <= 0 else min(1.0, max(0.0, (y - img.top() - crop.height() / 2) / free))
        self.changed.emit(self.frac)
        self.update()

    def mousePressEvent(self, e):
        self._set_from_pos(e.position().x(), e.position().y())

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton:
            self._set_from_pos(e.position().x(), e.position().y())


class CropDialog(QDialog):
    """세로 9:16 크롭 위치 선택."""

    def __init__(self, parent, pix: QPixmap, frac: float = 0.5):
        super().__init__(parent)
        self.setWindowTitle(tr("세로 9:16 크롭 위치"))
        self.resize(760, 520)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(tr("노란 창이 세로 영상으로 잘려 나갈 부분입니다. 드래그해서 위치를 정하세요. (이 영상의 모든 구간에 적용)")))
        self.preview = CropPreview(pix, frac)
        lay.addWidget(self.preview, 1)
        row = QHBoxLayout()
        self.lbl = QLabel()
        row.addWidget(self.lbl)
        row.addStretch(1)
        for text, f in ((tr("왼쪽"), 0.0), (tr("가운데"), 0.5), (tr("오른쪽"), 1.0)):
            b = QPushButton(text)
            b.clicked.connect(lambda _c=False, f=f: self._set(f))
            row.addWidget(b)
        lay.addLayout(row)
        lay.addWidget(_buttons(self))
        self.preview.changed.connect(lambda f: self.lbl.setText(tr("위치 {0:.0f}%").format(f * 100)))
        self.lbl.setText(tr("위치 {0:.0f}%").format(frac * 100))

    def _set(self, f):
        self.preview.frac = f
        self.preview.update()
        self.lbl.setText(tr("위치 {0:.0f}%").format(f * 100))

    @property
    def frac(self) -> float:
        return self.preview.frac


class DownloadDialog(QDialog):
    """URL 에서 영상 받기 (yt-dlp). 받은 파일 경로는 .result_path."""

    def __init__(self, parent, worker_factory, default_dir: str, last_quality: str = "best"):
        super().__init__(parent)
        self.setWindowTitle(tr("URL 에서 영상 열기"))
        self.resize(560, 260)
        self.worker_factory = worker_factory
        self.worker = None
        self.result_path = None
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(tr("유튜브 · 치지직 · 트위치 VOD · 아프리카 등 yt-dlp 가 지원하는 주소를 붙여넣으세요.")))
        self.ed_url = QLineEdit()
        self.ed_url.setPlaceholderText("https://www.youtube.com/watch?v=…")
        lay.addWidget(self.ed_url)
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("화질")))
        self.cb_q = QComboBox()
        for label, key in ((tr("최고 화질"), "best"), (tr("1080p 이하"), "1080"), (tr("720p 이하"), "720"), (tr("480p 이하"), "480")):
            self.cb_q.addItem(label, key)
        i = self.cb_q.findData(last_quality)
        self.cb_q.setCurrentIndex(i if i >= 0 else 0)
        row.addWidget(self.cb_q)
        row.addSpacing(12)
        row.addWidget(QLabel(tr("저장 폴더")))
        self.ed_dir = QLineEdit(default_dir)
        row.addWidget(self.ed_dir, 1)
        b = QToolButton()
        b.setText("…")
        b.clicked.connect(self._choose_dir)
        row.addWidget(b)
        lay.addLayout(row)
        srow = QHBoxLayout()
        from PySide6.QtWidgets import QCheckBox
        self.cb_section = QCheckBox(tr("구간만 받기"))
        self.cb_section.setToolTip(tr("긴 다시보기는 필요한 구간만 받으세요. 예: 1:02:00 ~ 1:15:30"))
        self.ed_start = QLineEdit()
        self.ed_start.setPlaceholderText(tr("시작 (예: 1:02:00)"))
        self.ed_end = QLineEdit()
        self.ed_end.setPlaceholderText(tr("끝 (예: 1:15:30)"))
        for w in (self.ed_start, self.ed_end):
            w.setEnabled(False)
            w.setFixedWidth(130)
        self.cb_section.toggled.connect(lambda on: (self.ed_start.setEnabled(on), self.ed_end.setEnabled(on)))
        srow.addWidget(self.cb_section)
        srow.addWidget(self.ed_start)
        srow.addWidget(QLabel("~"))
        srow.addWidget(self.ed_end)
        srow.addStretch(1)
        lay.addLayout(srow)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setFormat(tr("대기 중"))
        lay.addWidget(self.progress)
        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        lay.addWidget(self.lbl_status)
        btns = QHBoxLayout()
        btns.addStretch(1)
        self.b_start = QPushButton(tr("받기"))
        self.b_start.setDefault(True)
        self.b_start.clicked.connect(self._start)
        self.b_cancel = QPushButton(tr("취소"))
        self.b_cancel.clicked.connect(self._cancel)
        btns.addWidget(self.b_start)
        btns.addWidget(self.b_cancel)
        lay.addLayout(btns)

    def _choose_dir(self):
        d = QFileDialog.getExistingDirectory(self, tr("저장 폴더"), self.ed_dir.text())
        if d:
            self.ed_dir.setText(d)

    @property
    def quality(self) -> str:
        return self.cb_q.currentData()

    @property
    def out_dir(self) -> str:
        return self.ed_dir.text().strip()

    def _start(self):
        url = self.ed_url.text().strip()
        if not url.lower().startswith(("http://", "https://")):
            QMessageBox.warning(self, "URL", tr("http:// 또는 https:// 로 시작하는 주소를 넣어 주세요."))
            return
        if not self.out_dir:
            QMessageBox.warning(self, tr("저장 폴더"), tr("저장 폴더를 지정해 주세요."))
            return
        section = None
        if self.cb_section.isChecked():
            a, b = parse_time(self.ed_start.text()), parse_time(self.ed_end.text())
            if a is None or b is None or b <= a:
                QMessageBox.warning(self, tr("구간"), tr("시작과 끝 시각을 1:02:00 같은 형식으로 넣어 주세요 (끝이 시작보다 커야 함)."))
                return
            section = (a, b)
        os.makedirs(self.out_dir, exist_ok=True)
        self.b_start.setEnabled(False)
        self.ed_url.setEnabled(False)
        self.worker = self.worker_factory(url, self.out_dir, self.quality, section)
        self.worker.progress.connect(self._on_progress)
        self.worker.done.connect(self._on_done)
        self.worker.start()

    def _on_progress(self, frac: float, text: str):
        self.progress.setValue(int(frac * 1000))
        self.progress.setFormat(f"%p%  {text}")

    def _on_done(self, path: str, error: str):
        if path:
            self.result_path = path
            self.accept()
        else:
            self.lbl_status.setText(tr("실패: ") + error)
            self.b_start.setEnabled(True)
            self.ed_url.setEnabled(True)
            self.progress.setFormat(tr("실패"))

    def _cancel(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.lbl_status.setText(tr("취소 중…"))
            self.worker.wait(3000)
        self.reject()


class LoudDialog(QDialog):
    """큰 소리(웃음·환호) 감지 조건: 배율·최소 간격·앞당김."""

    def __init__(self, parent=None, factor: float = 3.0, min_gap: float = 10.0, lead: float = 2.0):
        super().__init__(parent)
        self.setWindowTitle(tr("큰 소리에 자동 마커"))
        lay = QVBoxLayout(self)
        intro = QLabel(tr("파형에서 평소보다 유난히 큰 소리가 난 곳(웃음·고함·환호)을 찾아 마커를 넣습니다.\n이미 분석된 파형을 쓰므로 바로 끝납니다."))
        intro.setWordWrap(True)
        lay.addWidget(intro)
        form = QFormLayout()
        self.sp_factor = QDoubleSpinBox()
        self.sp_factor.setRange(2.0, 8.0)
        self.sp_factor.setSingleStep(0.5)
        self.sp_factor.setValue(factor)
        self.sp_factor.setSuffix(tr(" 배"))
        self.sp_factor.setToolTip(tr("평소 음량(중앙값)의 몇 배를 넘어야 '큰 소리'로 볼지. 낮을수록 많이 잡힙니다."))
        form.addRow(tr("기준 배율"), self.sp_factor)
        self.sp_gap = QDoubleSpinBox()
        self.sp_gap.setRange(1.0, 600.0)
        self.sp_gap.setSingleStep(5.0)
        self.sp_gap.setValue(min_gap)
        self.sp_gap.setSuffix(tr(" 초"))
        self.sp_gap.setToolTip(tr("이 간격보다 가까운 큰 소리는 하나로 칩니다."))
        form.addRow(tr("마커 최소 간격"), self.sp_gap)
        self.sp_lead = QDoubleSpinBox()
        self.sp_lead.setRange(0.0, 30.0)
        self.sp_lead.setSingleStep(0.5)
        self.sp_lead.setValue(lead)
        self.sp_lead.setSuffix(tr(" 초"))
        self.sp_lead.setToolTip(tr("마커를 큰 소리보다 이만큼 앞에 둡니다 (클립이 반응 직전부터 시작하도록)."))
        form.addRow(tr("앞당김"), self.sp_lead)
        lay.addLayout(form)
        lay.addWidget(_buttons(self, tr("찾기")))

    @property
    def factor(self) -> float:
        return self.sp_factor.value()

    @property
    def min_gap(self) -> float:
        return self.sp_gap.value()

    @property
    def lead(self) -> float:
        return self.sp_lead.value()


class UpdateDialog(QDialog):
    """새 버전 안내 + 다운로드. 결과: self.action in ('update', 'later', 'skip'), self.new_dir."""

    def __init__(self, parent, rel: dict, current: str, worker_factory, can_update: bool, why_not: str):
        super().__init__(parent)
        self.setWindowTitle(tr("새 버전이 있습니다"))
        self.resize(600, 460)
        self.rel = rel
        self.worker_factory = worker_factory
        self.worker = None
        self.action = "later"
        self.new_dir = ""
        lay = QVBoxLayout(self)
        size = rel.get("download_size") or rel.get("zip_size") or 0  # updater.UpdateCheckWorker 가 고른 zip (경량/전체) 의 크기
        tail = f" &nbsp;·&nbsp; {size / 1e6:.0f} MB" if size else ""
        if rel.get("kind") == "update":
            tail += " " + tr("(경량: ffmpeg/libmpv 는 그대로)")
        head = QLabel(tr("<b style='font-size:15px'>ClipSlicer {0}</b> &nbsp; (지금 {1})").format(rel['version'], current) + tail)
        head.setTextFormat(Qt.RichText)
        lay.addWidget(head)
        from PySide6.QtWidgets import QTextBrowser
        notes = QTextBrowser()
        notes.setOpenExternalLinks(True)
        notes.setMarkdown(rel.get("notes") or tr("_변경 내용이 적혀 있지 않습니다._"))
        lay.addWidget(notes, 1)
        if can_update:
            info = QLabel(tr("'지금 업데이트'를 누르면 받아서 검증한 뒤, 프로그램을 닫고 파일을 교체하고 다시 엽니다.\n설정·로그·작업 파일은 그대로 유지되고, 이전 버전은 _backup 폴더에 남습니다."))
        else:
            info = QLabel(tr("이 환경에서는 자동 교체가 안 됩니다: {0}\n아래 '다운로드 페이지'에서 받아 직접 바꿔 주세요.").format(why_not))
        info.setWordWrap(True)
        info.setStyleSheet("color: #9aa0a6;")
        lay.addWidget(info)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setFormat("")
        self.progress.hide()
        lay.addWidget(self.progress)
        row = QHBoxLayout()
        b_page = QPushButton(tr("다운로드 페이지"))
        b_page.clicked.connect(lambda: os.startfile(rel.get("url") or "https://github.com/vtubeadmirer/clipslicer/releases"))
        row.addWidget(b_page)
        b_skip = QPushButton(tr("이 버전 건너뛰기"))
        b_skip.clicked.connect(self._skip)
        row.addWidget(b_skip)
        row.addStretch(1)
        self.b_later = QPushButton(tr("나중에"))
        self.b_later.clicked.connect(self._later)
        row.addWidget(self.b_later)
        self.b_update = QPushButton(tr("지금 업데이트"))
        self.b_update.setObjectName("exportBtn")
        self.b_update.setEnabled(can_update)
        self.b_update.setDefault(True)
        self.b_update.clicked.connect(self._start)
        row.addWidget(self.b_update)
        lay.addLayout(row)

    def _skip(self):
        self.action = "skip"
        self.reject()

    def _later(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(3000)
        self.action = "later"
        self.reject()

    def _start(self):
        self.b_update.setEnabled(False)
        self.progress.show()
        self.worker = self.worker_factory(self.rel)
        self.worker.progress.connect(lambda f, t: (self.progress.setValue(int(f * 1000)), self.progress.setFormat(f"%p%  {t}")))
        self.worker.done.connect(self._done)
        self.worker.start()

    def _done(self, new_dir: str, error: str):
        if error:
            self.progress.setFormat(tr("실패: ") + error)
            self.b_update.setEnabled(True)
            return
        self.new_dir = new_dir
        self.action = "update"
        self.accept()


def ask_overwrite(parent, existing: list[str]) -> str:
    """'overwrite' | 'rename' | 'cancel'"""
    shown = "\n".join(existing[:8]) + ("\n…" if len(existing) > 8 else "")
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Warning)
    box.setWindowTitle(tr("같은 이름의 파일이 있습니다"))
    box.setText(tr("{0}개 파일이 이미 있습니다.").format(len(existing)))
    box.setInformativeText(shown)
    b_over = box.addButton(tr("덮어쓰기"), QMessageBox.DestructiveRole)
    b_ren = box.addButton(tr("번호 붙여 저장"), QMessageBox.AcceptRole)
    box.addButton(tr("취소"), QMessageBox.RejectRole)
    box.setDefaultButton(b_ren)
    box.exec()
    clicked = box.clickedButton()
    if clicked == b_over:
        return "overwrite"
    if clicked == b_ren:
        return "rename"
    return "cancel"


class RenderAssetsDialog(QDialog):
    """워터마크 PNG(위치·투명도) 와 인트로/아웃트로 영상. 설정 키: wm_path, wm_pos, wm_opacity, intro_path, outro_path."""

    POSITIONS = [("tl", "왼쪽 위"), ("tr", "오른쪽 위"), ("bl", "왼쪽 아래"), ("br", "오른쪽 아래")]
    VIDEO_FILTER = "영상 파일 (*.mp4 *.mkv *.mov *.webm);;모든 파일 (*)"

    def __init__(self, parent, settings):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle(tr("워터마크 / 인트로·아웃트로"))
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        intro = QLabel(tr("워터마크를 지정하면 모든 영상 출력이 재인코딩됩니다 (출력 mp4). 인트로/아웃트로는 재인코딩되는 출력(정확하게 · 세로 · 캡션 · 자막 · 워터마크)에만 붙습니다. 비워 두면 쓰지 않습니다."))
        intro.setWordWrap(True)
        lay.addWidget(intro)
        form = QFormLayout()
        self.ed_wm = self._file_row(form, tr("워터마크 PNG"), settings.value("wm_path", ""), tr("PNG 이미지 (*.png)"))
        self.cb_pos = QComboBox()
        for code, label in self.POSITIONS:
            self.cb_pos.addItem(tr(label), code)
        idx = self.cb_pos.findData(settings.value("wm_pos", "br"))
        self.cb_pos.setCurrentIndex(idx if idx >= 0 else 3)
        form.addRow(tr("워터마크 위치"), self.cb_pos)
        self.sp_opacity = QDoubleSpinBox()
        self.sp_opacity.setRange(0.05, 1.0)
        self.sp_opacity.setSingleStep(0.05)
        try:
            self.sp_opacity.setValue(float(settings.value("wm_opacity", 0.8)))
        except (TypeError, ValueError):
            self.sp_opacity.setValue(0.8)
        form.addRow(tr("워터마크 불투명도"), self.sp_opacity)
        self.ed_intro = self._file_row(form, tr("인트로 영상"), settings.value("intro_path", ""), tr(self.VIDEO_FILTER))
        self.ed_outro = self._file_row(form, tr("아웃트로 영상"), settings.value("outro_path", ""), tr(self.VIDEO_FILTER))
        lay.addLayout(form)
        lay.addWidget(_buttons(self))

    def _file_row(self, form, label: str, value: str, filt: str) -> QLineEdit:
        row = QHBoxLayout()
        ed = QLineEdit(value or "")
        ed.setPlaceholderText(tr("비워 두면 사용 안 함"))
        btn = QToolButton()
        btn.setText("…")
        btn.clicked.connect(lambda: self._pick(ed, label, filt))
        clr = QToolButton()
        clr.setText("✕")
        clr.setToolTip(tr("지우기"))
        clr.clicked.connect(ed.clear)
        row.addWidget(ed, 1)
        row.addWidget(btn)
        row.addWidget(clr)
        form.addRow(label, row)
        return ed

    def _pick(self, ed: QLineEdit, title: str, filt: str):
        start = os.path.dirname(ed.text()) if ed.text() else ""
        path, _ = QFileDialog.getOpenFileName(self, title, start, filt)
        if path:
            ed.setText(path)

    def save(self):
        s = self.settings
        s.setValue("wm_path", self.ed_wm.text().strip())
        s.setValue("wm_pos", self.cb_pos.currentData() or "br")
        s.setValue("wm_opacity", f"{self.sp_opacity.value():.2f}")
        s.setValue("intro_path", self.ed_intro.text().strip())
        s.setValue("outro_path", self.ed_outro.text().strip())
        s.sync()
