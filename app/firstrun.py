"""처음 실행 안내 대화상자 + 연습용 샘플 영상 생성 (ffmpeg lavfi)."""
from __future__ import annotations

from .i18n import tr
import logging
import os
import subprocess

from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QCheckBox

from .ffmpeg_tools import find_tool, _popen_kwargs

LOG = logging.getLogger("clipslicer")
SETTINGS_KEY = "first_run_done"
SAMPLE_DURATION = 30
SAMPLE_SIZE = "640x360"

_HTML = """
<div style='font-size:13px; line-height:1.5'>
<p style='font-size:17px; margin-bottom:4px'><b>{title}</b></p>
<table cellspacing='0' cellpadding='6'>
<tr><td style='font-size:30px' valign='middle'>📂</td><td valign='middle'><b>{t1}</b><br>
<span style='color:#9aa0a6'>{b1}</span></td></tr>
<tr><td style='font-size:30px' valign='middle'>✂️</td><td valign='middle'><b>{t2}</b><br>
<span style='color:#9aa0a6'>{b2}</span></td></tr>
<tr><td style='font-size:30px' valign='middle'>📤</td><td valign='middle'><b>{t3}</b><br>
<span style='color:#9aa0a6'>{b3}</span></td></tr>
</table>
<p style='color:#7cc4ff; margin-top:6px'>{f1}</p>
</div>
"""


def sample_path() -> str:
    """기본 샘플 위치: <설정 폴더>/samples/sample.mp4."""
    from .youtube import config_dir
    return os.path.join(config_dir(), "samples", "sample.mp4")


def make_sample(dst_path: str, duration: int = SAMPLE_DURATION) -> str:
    """30초 640x360 연습용 영상을 만든다 (있으면 그대로 씀). 경로를 돌려준다.

    testsrc2 · 빨강 · SMPTE 바 · 파랑 · testsrc2 를 이어 붙여 8 · 12 · 20 · 24초에 장면 전환이 생기고,
    440Hz 사인파 오디오에 10~13초 무음 구간이 있어 장면 전환 감지 · 무음 마커를 바로 해 볼 수 있다.
    """
    if os.path.isfile(dst_path) and os.path.getsize(dst_path) > 0:
        return dst_path
    ffmpeg = find_tool("ffmpeg")
    if not ffmpeg:
        raise RuntimeError(tr("ffmpeg 를 찾을 수 없습니다"))
    os.makedirs(os.path.dirname(dst_path) or ".", exist_ok=True)
    d = max(int(duration), 10)
    # 장면 길이 (합이 d). 기본 30초면 8/4/8/4/6.
    seg = [round(d * 8 / 30), round(d * 4 / 30), round(d * 8 / 30), round(d * 4 / 30)]
    seg.append(d - sum(seg))
    s, r = SAMPLE_SIZE, 30
    sources = [
        f"testsrc2=s={s}:r={r}:d={seg[0]}",
        f"color=c=red:s={s}:r={r}:d={seg[1]}",
        f"smptebars=s={s}:r={r}:d={seg[2]}",
        f"color=c=blue:s={s}:r={r}:d={seg[3]}",
        f"testsrc2=s={s}:r={r}:d={seg[4]}",
    ]
    gap_a, gap_b = round(d / 3), round(d / 3) + 3
    cmd = [ffmpeg, "-v", "error", "-y"]
    for src in sources:
        cmd += ["-f", "lavfi", "-i", src]
    cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=44100:duration={d}"]
    cmd += ["-filter_complex",
            "[0][1][2][3][4]concat=n=5:v=1:a=0[v];"
            f"[5]volume=enable='between(t,{gap_a},{gap_b})':volume=0[a]",
            "-map", "[v]", "-map", "[a]", "-t", str(d),
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-g", str(r),
            "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart"]
    tmp = dst_path + ".part.mp4"
    cmd.append(tmp)
    LOG.info("샘플 영상 생성: %s", dst_path)
    out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", **_popen_kwargs())
    if out.returncode != 0 or not os.path.isfile(tmp):
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise RuntimeError(tr("샘플 영상 생성 실패: {0}").format((out.stderr or "").strip()[-300:] or out.returncode))
    os.replace(tmp, dst_path)
    return dst_path


class SampleWorker(QThread):
    """샘플 영상을 백그라운드에서 만든다. done(경로 또는 '', 오류)."""
    done = Signal(str, str)

    def __init__(self, dst_path: str, parent=None):
        super().__init__(parent)
        self.dst_path = dst_path

    def run(self):
        try:
            self.done.emit(make_sample(self.dst_path), "")
        except Exception as ex:
            LOG.exception("샘플 영상 생성 실패")
            self.done.emit("", str(ex))


class FirstRunDialog(QDialog):
    """처음 실행 때 한 번 보여 주는 3단계 안내. 설정 키 first_run_done."""
    sampleRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("ClipSlicer 처음 사용 안내"))
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        body = QLabel(_HTML.format(
            title=tr("영상 자르기, 세 단계면 끝납니다"),
            t1=tr("1. 끌어다 놓기"),
            b1=tr("영상 파일을 창에 끌어다 놓거나 Ctrl+O 로 엽니다. 여러 개를 한꺼번에 넣어도 됩니다."),
            t2=tr("2. S 로 마커 · I·O 로 클립"),
            b2=tr("재생하다가 자를 지점에서 S. 원하는 부분만 남기려면 시작에서 I, 끝에서 O 를 누르세요."),
            t3=tr("3. Ctrl+E 내보내기"),
            b3=tr("켜진 구간이 각각 파일로 저장됩니다. 재인코딩 없이 빠르게, 원본 화질 그대로."),
            f1=tr("막히면 언제든 F1 도움말"),
        ))
        body.setTextFormat(Qt.RichText)
        body.setWordWrap(True)
        lay.addWidget(body)

        self.cb_hide = QCheckBox(tr("다시 보지 않기"))
        self.cb_hide.setChecked(True)
        btns = QHBoxLayout()
        btns.addWidget(self.cb_hide)
        btns.addStretch(1)
        self.b_sample = QPushButton(tr("샘플 영상으로 해 보기"))
        self.b_sample.setToolTip(tr("ffmpeg 로 30초짜리 연습용 영상을 만들어 엽니다"))
        self.b_sample.clicked.connect(self._on_sample)
        btns.addWidget(self.b_sample)
        self.b_start = QPushButton(tr("시작하기"))
        self.b_start.setObjectName("exportBtn")
        self.b_start.setDefault(True)
        self.b_start.clicked.connect(self.accept)
        btns.addWidget(self.b_start)
        lay.addLayout(btns)

    @property
    def dont_show_again(self) -> bool:
        return self.cb_hide.isChecked()

    def _on_sample(self):
        self.sampleRequested.emit()
        self.accept()

    @staticmethod
    def should_show(settings) -> bool:
        if str(settings.value(SETTINGS_KEY, "0")) == "1":
            return False
        # 0.7 이하에서 올라온 기존 설치 (이미 쓰던 흔적이 있으면) 는 건너뛴다 — 새 설치에서만 보여준다
        return not any(settings.contains(k) for k in ("recent", "mode", "out_dir"))

    @staticmethod
    def mark_done(settings):
        settings.setValue(SETTINGS_KEY, "1")
