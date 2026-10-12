"""작은 대화상자들: 무음 자동 마커, 덮어쓰기 확인, 파일명 규칙."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QDoubleSpinBox, QRadioButton,
    QDialogButtonBox, QLineEdit, QMessageBox, QGroupBox, QPushButton,
)

from .segments import DEFAULT_PATTERN


class SilenceDialog(QDialog):
    """무음 구간 감지 조건과 마커 배치 방식."""

    def __init__(self, parent=None, noise_db: float = -35.0, min_dur: float = 1.0):
        super().__init__(parent)
        self.setWindowTitle("무음 구간에 자동 마커")
        lay = QVBoxLayout(self)
        intro = QLabel("소리가 거의 없는 구간을 찾아 그 위치에 마커를 넣습니다.\n"
                       "강의·방송 녹화처럼 말이 끊기는 지점으로 나누고 싶을 때 쓰세요.")
        intro.setWordWrap(True)
        lay.addWidget(intro)

        form = QFormLayout()
        self.sp_db = QDoubleSpinBox()
        self.sp_db.setRange(-80, 0)
        self.sp_db.setSingleStep(5)
        self.sp_db.setValue(noise_db)
        self.sp_db.setSuffix(" dB")
        self.sp_db.setToolTip("이 값보다 작은 소리는 '무음'으로 봅니다. -35dB 가 무난하고, 잡음이 많으면 -25dB 정도로 올리세요.")
        form.addRow("무음 기준 음량", self.sp_db)
        self.sp_dur = QDoubleSpinBox()
        self.sp_dur.setRange(0.2, 60)
        self.sp_dur.setSingleStep(0.5)
        self.sp_dur.setValue(min_dur)
        self.sp_dur.setSuffix(" 초")
        self.sp_dur.setToolTip("이 시간 이상 이어지는 무음만 찾습니다.")
        form.addRow("최소 무음 길이", self.sp_dur)
        lay.addLayout(form)

        grp = QGroupBox("마커 배치")
        gl = QVBoxLayout(grp)
        self.rb_middle = QRadioButton("무음 구간 가운데에 마커 1개 (깔끔하게 나누기)")
        self.rb_edges = QRadioButton("무음 구간 양쪽 끝에 마커 2개, 무음 구간은 끄기 (무음 잘라내기)")
        self.rb_middle.setChecked(True)
        gl.addWidget(self.rb_middle)
        gl.addWidget(self.rb_edges)
        lay.addWidget(grp)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("찾기")
        bb.button(QDialogButtonBox.Cancel).setText("취소")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    @property
    def noise_db(self) -> float:
        return self.sp_db.value()

    @property
    def min_dur(self) -> float:
        return self.sp_dur.value()

    @property
    def mode(self) -> str:
        return "edges" if self.rb_edges.isChecked() else "middle"


class PatternDialog(QDialog):
    """출력 파일명 규칙."""

    def __init__(self, parent=None, pattern: str = DEFAULT_PATTERN):
        super().__init__(parent)
        self.setWindowTitle("파일명 규칙")
        lay = QVBoxLayout(self)
        help_text = QLabel(
            "저장되는 파일 이름을 정하는 규칙입니다. 아래 자리표시자를 조합하세요.\n\n"
            "  {name}   원본 파일 이름 (확장자 제외)\n"
            "  {n}      구간 번호 (01, 02 …)\n"
            "  {start}  구간 시작 시각 (예: 01m23s)\n"
            "  {end}    구간 끝 시각\n"
            "  {dur}    구간 길이\n\n"
            "구간 목록에서 파일명을 직접 입력한 구간은 그 이름이 우선합니다."
        )
        help_text.setStyleSheet("font-family: Consolas, monospace;")
        lay.addWidget(help_text)
        row = QHBoxLayout()
        self.ed = QLineEdit(pattern)
        row.addWidget(QLabel("규칙"))
        row.addWidget(self.ed, 1)
        lay.addLayout(row)
        self.preview = QLabel()
        self.preview.setStyleSheet("color: #8ab;")
        lay.addWidget(self.preview)
        self.ed.textChanged.connect(self._update_preview)
        self._update_preview()
        btns = QHBoxLayout()
        b_reset = QPushButton("기본값")
        b_reset.clicked.connect(lambda: self.ed.setText(DEFAULT_PATTERN))
        btns.addWidget(b_reset)
        btns.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("확인")
        bb.button(QDialogButtonBox.Cancel).setText("취소")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        btns.addWidget(bb)
        lay.addLayout(btns)

    def _update_preview(self):
        sample = {"name": "방송녹화", "n": "03", "start": "12m05s", "end": "15m40s", "dur": "03m35s"}
        try:
            self.preview.setText("예: " + self.ed.text().format(**sample) + ".mp4")
        except (KeyError, IndexError, ValueError):
            self.preview.setText("규칙이 올바르지 않습니다. 중괄호 안 이름을 확인하세요.")

    @property
    def pattern(self) -> str:
        p = self.ed.text().strip()
        try:
            p.format(name="a", n="01", start="0", end="0", dur="0")
        except (KeyError, IndexError, ValueError):
            return DEFAULT_PATTERN
        return p or DEFAULT_PATTERN


def ask_overwrite(parent, existing: list[str]) -> str:
    """'overwrite' | 'rename' | 'cancel'"""
    shown = "\n".join(existing[:8]) + ("\n…" if len(existing) > 8 else "")
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Warning)
    box.setWindowTitle("같은 이름의 파일이 있습니다")
    box.setText(f"{len(existing)}개 파일이 이미 있습니다.")
    box.setInformativeText(shown)
    b_over = box.addButton("덮어쓰기", QMessageBox.DestructiveRole)
    b_ren = box.addButton("번호 붙여 저장", QMessageBox.AcceptRole)
    b_cancel = box.addButton("취소", QMessageBox.RejectRole)
    box.setDefaultButton(b_ren)
    box.exec()
    clicked = box.clickedButton()
    if clicked == b_over:
        return "overwrite"
    if clicked == b_ren:
        return "rename"
    return "cancel"
