"""백그라운드 작업: 영상 분석(썸네일/파형), 내보내기 큐."""
from __future__ import annotations

import os
from dataclasses import dataclass

from PySide6.QtCore import QThread, Signal

from . import ffmpeg_tools


class AnalyzeWorker(QThread):
    """썸네일과 파형을 뽑아서 신호로 돌려준다."""
    thumbsReady = Signal(str, list)      # path, [(t, jpeg bytes)]
    waveformReady = Signal(str, object)  # path, np.ndarray | None

    def __init__(self, path: str, duration: float, parent=None):
        super().__init__(parent)
        self.path = path
        self.duration = duration

    def run(self):
        try:
            thumbs = ffmpeg_tools.extract_thumbnails(self.path, self.duration)
        except Exception:
            thumbs = []
        self.thumbsReady.emit(self.path, thumbs)
        try:
            wave = ffmpeg_tools.compute_waveform(self.path)
        except Exception:
            wave = None
        self.waveformReady.emit(self.path, wave)


@dataclass
class ExportJob:
    src: str
    start: float
    end: float
    dst: str
    precise: bool

    @property
    def label(self) -> str:
        return os.path.basename(self.dst)


class ExportWorker(QThread):
    jobStarted = Signal(int, str)
    jobProgress = Signal(int, float)
    jobFinished = Signal(int, bool, str)
    allFinished = Signal(int, int)  # ok count, fail count

    def __init__(self, jobs: list[ExportJob], parent=None):
        super().__init__(parent)
        self.jobs = jobs
        self._current: ffmpeg_tools.CutProcess | None = None
        self._cancel = False

    def cancel(self):
        self._cancel = True
        if self._current:
            self._current.cancel()

    def run(self):
        ok_n = fail_n = 0
        for i, job in enumerate(self.jobs):
            if self._cancel:
                break
            self.jobStarted.emit(i, job.label)
            os.makedirs(os.path.dirname(job.dst) or ".", exist_ok=True)
            cmd = ffmpeg_tools.build_cut_cmd(job.src, job.start, job.end, job.dst, job.precise)
            self._current = ffmpeg_tools.CutProcess(cmd, job.end - job.start)
            try:
                ok, msg = self._current.run(lambda p, i=i: self.jobProgress.emit(i, p))
            except Exception as ex:  # ffmpeg 실행 실패 등
                ok, msg = False, str(ex)
            self._current = None
            if ok:
                ok_n += 1
            else:
                fail_n += 1
                if os.path.exists(job.dst):
                    try:
                        os.remove(job.dst)
                    except OSError:
                        pass
            self.jobFinished.emit(i, ok, msg)
        self.allFinished.emit(ok_n, fail_n)
