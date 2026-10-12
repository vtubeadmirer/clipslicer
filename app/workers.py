"""백그라운드 작업: 영상 분석, 무음 감지, GPU 감지, 내보내기 큐."""
from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass, field

from PySide6.QtCore import QThread, Signal

from . import ffmpeg_tools
from .ffmpeg_tools import Cutter, Cancelled


class AnalyzeWorker(QThread):
    """썸네일 · 파형 · 키프레임을 뽑아서 신호로 돌려준다. (썸네일 → 파형 → 키프레임 순)"""
    thumbsReady = Signal(str, list)        # path, [(t, jpeg bytes)]
    waveformReady = Signal(str, object)    # path, list[float] | None
    keyframesReady = Signal(str, list)     # path, [t, ...]

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
        try:
            self.keyframesReady.emit(self.path, ffmpeg_tools.keyframes(self.path))
        except Exception:
            self.keyframesReady.emit(self.path, [])


class SilenceWorker(QThread):
    done = Signal(str, list)  # path, [(start, end)]

    def __init__(self, path: str, noise_db: float, min_dur: float, parent=None):
        super().__init__(parent)
        self.path, self.noise_db, self.min_dur = path, noise_db, min_dur

    def run(self):
        try:
            spans = ffmpeg_tools.detect_silence(self.path, self.noise_db, self.min_dur)
        except Exception:
            spans = []
        self.done.emit(self.path, spans)


class GpuDetectWorker(QThread):
    done = Signal(object)  # encoder name | None

    def run(self):
        try:
            self.done.emit(ffmpeg_tools.detect_gpu_encoder("h264"))
        except Exception:
            self.done.emit(None)


# --------------------------------------------------------------------------- 내보내기
@dataclass
class ExportPart:
    start: float
    end: float


@dataclass
class ExportJob:
    src: str
    info: dict                       # probe 결과
    keyframes: list[float]
    parts: list[ExportPart]          # 1개면 단일 구간, 여러 개면 합치기
    dst: str
    mode: str = "fast"               # fast | smart | precise
    audio: str = ""                  # '' (영상+오디오) | 'aac' | 'mp3'
    gpu: str | None = None
    note: str = field(default="")

    @property
    def label(self) -> str:
        return os.path.basename(self.dst)

    @property
    def total_duration(self) -> float:
        return sum(p.end - p.start for p in self.parts)


class ExportWorker(QThread):
    jobStarted = Signal(int, str)
    jobProgress = Signal(int, float)
    jobFinished = Signal(int, bool, str)
    allFinished = Signal(int, int)  # ok count, fail count

    def __init__(self, jobs: list[ExportJob], parent=None):
        super().__init__(parent)
        self.jobs = jobs
        self._cutter: Cutter | None = None
        self._cancel = False

    def cancel(self):
        self._cancel = True
        if self._cutter:
            self._cutter.cancel()

    # ---- 단일 구간 ----
    def _cut_one(self, cutter: Cutter, job: ExportJob, part: ExportPart, dst: str, cb) -> str:
        if job.audio:
            cutter.cut_audio(job.src, part.start, part.end, dst, job.audio, job.info.get("acodec", ""), cb)
            return "오디오"
        if job.mode == "precise":
            cutter.cut_encode(job.src, part.start, part.end, dst, cb, "h264", job.gpu)
            return "재인코딩"
        if job.mode == "smart":
            how = cutter.cut_smart(job.src, part.start, part.end, dst, job.info, job.keyframes, cb, job.gpu)
            return {"copy": "복사", "smart": "스마트", "encode": "재인코딩"}.get(how, how)
        cutter.cut_copy(job.src, part.start, part.end, dst, cb)
        return "복사"

    # ---- 합치기 ----
    def _merge(self, i: int, cutter: Cutter, job: ExportJob) -> str:
        total = job.total_duration
        cb = lambda p: self.jobProgress.emit(i, p)  # noqa: E731
        if job.mode == "fast" and not job.audio:
            # 원본에서 구간들을 바로 읽어 한 번에 이어 붙인다 (임시 파일 없음)
            cutter.concat([(job.src, p.start, p.end) for p in job.parts], job.dst, cb, total)
            return f"{len(job.parts)}개 구간 합침"
        tmp = tempfile.mkdtemp(prefix="clipslicer_merge_")
        try:
            ext = os.path.splitext(job.dst)[1]
            entries: list = []
            done = 0.0
            heads = 0
            for n, part in enumerate(job.parts):
                plen = part.end - part.start
                prog = lambda p, d=done, l=plen: self.jobProgress.emit(i, 0.9 * (d + p * l) / total)  # noqa: E731
                if job.mode == "smart" and not job.audio:
                    plan = Cutter.smart_plan(job.info, job.keyframes, part.start, part.end)
                    if plan is not None and plan[2] is None:
                        entries.append((job.src, part.start, part.end))          # 키프레임에서 시작 → 그대로
                    elif plan is not None:
                        family, audio_args, k = plan
                        head = os.path.join(tmp, f"head{n:03d}{ext}")
                        cutter.encode_head(job.src, part.start, k, head, job.info, job.gpu, family, audio_args, prog)
                        entries += [head, (job.src, k, part.end)]
                        heads += 1
                    else:
                        f = os.path.join(tmp, f"part{n:03d}{ext}")
                        cutter.cut_encode(job.src, part.start, part.end, f, prog, "h264", job.gpu)
                        entries.append(f)
                else:
                    f = os.path.join(tmp, f"part{n:03d}{ext}")
                    self._cut_one(cutter, job, part, f, prog)
                    entries.append(f)
                done += plen
            cutter.concat(entries, job.dst, lambda p: self.jobProgress.emit(i, 0.9 + 0.1 * p), total)
            return f"{len(job.parts)}개 구간 합침" + (f", 앞조각 {heads}개 재인코딩" if heads else "")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _run_job(self, i: int, job: ExportJob) -> str:
        cutter = Cutter()
        self._cutter = cutter
        try:
            if job.mode == "smart" and not job.keyframes and not job.audio:
                # 키프레임 분석이 아직 안 끝났으면 지금 한다 (없으면 전체 재인코딩으로 빠져 느려짐)
                job.keyframes = ffmpeg_tools.keyframes(job.src)
            if len(job.parts) == 1:
                return self._cut_one(cutter, job, job.parts[0], job.dst, lambda p: self.jobProgress.emit(i, p))
            return self._merge(i, cutter, job)
        finally:
            self._cutter = None

    def run(self):
        ok_n = fail_n = 0
        for i, job in enumerate(self.jobs):
            if self._cancel:
                break
            self.jobStarted.emit(i, job.label)
            os.makedirs(os.path.dirname(job.dst) or ".", exist_ok=True)
            try:
                note = self._run_job(i, job)
                ok, msg = True, note
            except Cancelled:
                ok, msg = False, "취소됨"
            except Exception as ex:
                ok, msg = False, str(ex)
            if ok:
                ok_n += 1
                self.jobProgress.emit(i, 1.0)
            else:
                fail_n += 1
                if os.path.exists(job.dst):
                    try:
                        os.remove(job.dst)
                    except OSError:
                        pass
            self.jobFinished.emit(i, ok, msg)
            if self._cancel:
                break
        self.allFinished.emit(ok_n, fail_n)
