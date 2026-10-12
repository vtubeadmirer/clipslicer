"""백그라운드 작업: 영상 분석, 무음 감지, GPU 감지, 내보내기 큐."""
from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass, field

import logging

from PySide6.QtCore import QThread, Signal

from . import ffmpeg_tools, cache
from .ffmpeg_tools import Cutter, Cancelled

LOG = logging.getLogger("clipslicer")


class AnalyzeWorker(QThread):
    """썸네일 · 파형 · 키프레임을 뽑아서 신호로 돌려준다. (썸네일 → 파형 → 키프레임 순)"""
    thumbsReady = Signal(str, list)        # path, [(t, jpeg bytes)]
    waveformReady = Signal(str, object)    # path, list[float] | None
    keyframesReady = Signal(str, list)     # path, [t, ...]

    def __init__(self, path: str, duration: float, parent=None, use_cache: bool = True):
        super().__init__(parent)
        self.path = path
        self.duration = duration
        self.use_cache = use_cache

    def run(self):
        if self.use_cache:
            data = cache.load(self.path)
            if data:
                LOG.info("분석 캐시 사용: %s", self.path)
                self.thumbsReady.emit(self.path, data["thumbs"])
                self.waveformReady.emit(self.path, data["waveform"])
                self.keyframesReady.emit(self.path, data["keyframes"])
                return
        try:
            thumbs = ffmpeg_tools.extract_thumbnails(self.path, self.duration)
        except Exception:
            LOG.exception("썸네일 실패: %s", self.path)
            thumbs = []
        self.thumbsReady.emit(self.path, thumbs)
        try:
            wave = ffmpeg_tools.compute_waveform(self.path)
        except Exception:
            LOG.exception("파형 실패: %s", self.path)
            wave = None
        self.waveformReady.emit(self.path, wave)
        try:
            kfs = ffmpeg_tools.keyframes(self.path)
        except Exception:
            LOG.exception("키프레임 실패: %s", self.path)
            kfs = []
        self.keyframesReady.emit(self.path, kfs)
        if self.use_cache and (thumbs or wave is not None or kfs):
            cache.save(self.path, thumbs, wave, kfs)


class SilenceWorker(QThread):
    done = Signal(str, list)  # path, [(start, end)]

    def __init__(self, path: str, noise_db: float, min_dur: float, parent=None):
        super().__init__(parent)
        self.path, self.noise_db, self.min_dur = path, noise_db, min_dur

    def run(self):
        try:
            spans = ffmpeg_tools.detect_silence(self.path, self.noise_db, self.min_dur)
        except Exception:
            LOG.exception("무음 감지 실패: %s", self.path)
            spans = []
        self.done.emit(self.path, spans)


class SceneWorker(QThread):
    progress = Signal(float)
    done = Signal(str, list)  # path, [t, ...]

    def __init__(self, path: str, duration: float, threshold: float, min_gap: float, parent=None):
        super().__init__(parent)
        self.path, self.duration, self.threshold, self.min_gap = path, duration, threshold, min_gap
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            times = ffmpeg_tools.detect_scenes(self.path, self.duration, self.threshold, self.min_gap,
                                               self.progress.emit, lambda: self._cancel)
        except Exception:
            LOG.exception("장면 전환 감지 실패: %s", self.path)
            times = []
        self.done.emit(self.path, [] if self._cancel else times)


class DownloadWorker(QThread):
    """yt-dlp 로 URL 다운로드. progress(0~1, 상태글), done(파일경로 또는 '', 오류)."""
    progress = Signal(float, str)
    done = Signal(str, str)

    def __init__(self, url: str, out_dir: str, quality: str = "best", parent=None):
        super().__init__(parent)
        self.url, self.out_dir, self.quality = url, out_dir, quality
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def _fmt(self) -> str:
        if self.quality in ("1080", "720", "480"):
            h = self.quality
            return f"bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<={h}]+bestaudio/best[height<={h}]/best"
        return "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best"

    def run(self):
        try:
            import yt_dlp
        except ImportError:
            self.done.emit("", "yt-dlp 모듈이 없습니다 (pip install yt-dlp)")
            return
        result = {"path": ""}

        def hook(d):
            if self._cancel:
                raise yt_dlp.utils.DownloadCancelled()
            st = d.get("status")
            if st == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                got = d.get("downloaded_bytes") or 0
                frac = got / total if total else 0.0
                spd = d.get("_speed_str") or d.get("speed") or ""
                eta = d.get("_eta_str") or ""
                self.progress.emit(min(frac, 0.99), f"받는 중 {spd} {eta}".strip())
            elif st == "finished":
                self.progress.emit(0.99, "합치는 중…")

        def pp_hook(d):
            if d.get("status") == "finished" and d.get("postprocessor") in ("MoveFiles", "Merger"):
                info = d.get("info_dict") or {}
                p = info.get("filepath") or info.get("_filename")
                if p:
                    result["path"] = p

        ffdir = os.path.dirname(ffmpeg_tools.find_tool("ffmpeg") or "")
        opts = {
            "format": self._fmt(),
            "outtmpl": os.path.join(self.out_dir, "%(title).80s [%(id)s].%(ext)s"),
            "merge_output_format": "mp4",
            "noplaylist": True,
            "quiet": True,
            "noprogress": True,
            "no_warnings": True,
            "progress_hooks": [hook],
            "postprocessor_hooks": [pp_hook],
            "windowsfilenames": True,
            "retries": 3,
        }
        if ffdir:
            opts["ffmpeg_location"] = ffdir
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(self.url, download=True)
            path = result["path"]
            if not path:
                req = (info or {}).get("requested_downloads") or []
                if req:
                    path = req[0].get("filepath") or ""
            if not path and info:
                path = ydl.prepare_filename(info)
                base = os.path.splitext(path)[0]
                if not os.path.exists(path) and os.path.exists(base + ".mp4"):
                    path = base + ".mp4"
            if path and os.path.exists(path):
                self.progress.emit(1.0, "완료")
                self.done.emit(path, "")
            else:
                self.done.emit("", "다운로드는 끝났지만 파일을 찾지 못했습니다")
        except Exception as ex:  # DownloadCancelled 포함
            if self._cancel:
                self.done.emit("", "취소됨")
            else:
                LOG.exception("다운로드 실패: %s", self.url)
                msg = str(ex)
                if "ERROR:" in msg:
                    msg = msg.split("ERROR:", 1)[1].strip()
                self.done.emit("", msg[:400])


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
    vertical: float | None = None    # 세로 9:16 크롭 위치 (None 이면 원본 비율)
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
        if job.vertical is not None:
            cutter.cut_vertical(job.src, part.start, part.end, dst, job.info, job.vertical, cb, job.gpu)
            return "세로 9:16"
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
        if job.mode == "fast" and not job.audio and job.vertical is None:
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
                if job.mode == "smart" and not job.audio and job.vertical is None:
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
            LOG.info("내보내기 [%d/%d] %s mode=%s audio=%s parts=%d gpu=%s", i + 1, len(self.jobs), job.dst,
                     job.mode, job.audio or "-", len(job.parts), job.gpu)
            os.makedirs(os.path.dirname(job.dst) or ".", exist_ok=True)
            try:
                note = self._run_job(i, job)
                ok, msg = True, note
            except Cancelled:
                ok, msg = False, "취소됨"
            except Exception as ex:
                LOG.exception("내보내기 실패: %s", job.dst)
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
