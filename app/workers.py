"""백그라운드 작업: 영상 분석, 무음 감지, GPU 감지, 내보내기 큐."""
from __future__ import annotations

from .i18n import tr
import os
import time
import urllib.parse
import shutil
import tempfile
from dataclasses import dataclass, field

import logging

from PySide6.QtCore import QThread, Signal

from . import ffmpeg_tools, cache
from .ffmpeg_tools import Cutter, Cancelled, RenderOptions, audio_normalize_args

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
    """yt-dlp 로 URL 다운로드. progress(0~1, 상태글), done(파일경로 또는 '', 오류).

    section=(start, end) 를 주면 그 구간만 받는다. HLS(네이버 VOD 등)는 세그먼트를 직접 골라 받고,
    그 외(유튜브 등)는 yt-dlp 의 구간 다운로드(ffmpeg)를 쓴다.
    """
    progress = Signal(float, str)
    done = Signal(str, str)
    liveStarted = Signal()   # m3u8 라이브 녹화를 시작함 → 대화상자가 '녹화 중지' 버튼을 보여 준다

    def __init__(self, url: str, out_dir: str, quality: str = "best", section: tuple[float, float] | None = None,
                 parent=None, cookies: str = "", referer: str = "", headers: dict | None = None, title: str = "",
                 stream: bool = False):
        super().__init__(parent)
        self.url, self.out_dir, self.quality, self.section = url, out_dir, quality, section
        self.cookies, self.referer = cookies, referer
        self.headers = headers or {}  # 브라우저 확장이 넘긴 실제 요청 헤더 (쿠키 · 인증 포함) — 있으면 그대로 다시 보낸다
        self.title = title
        # 확장이 응답 형식(mpegurl)으로 알아낸 재생 목록: 주소가 .m3u8 로 끝나지 않아도 (rplay 다시보기의
        # .../content/hlsstream 등) 재생 목록으로 받는다 (페이지 주소로 오해해 거절하던 0.9.13 버그)
        self.stream = stream
        self._cancel = False
        self._stop = False
        self._recorder = None

    def cancel(self):
        self._cancel = True
        if self._recorder is not None:
            self._recorder.stop()

    def live_state(self) -> tuple[str, float, str] | None:
        """녹화 중이면 (자라는 .ts 경로, 지금까지 녹화된 초, 파일 이름 바탕), 아니면 None. 실시간 클립용."""
        rec = self._recorder
        if rec is None or rec.proc is None or rec.proc.poll() is not None:
            return None
        return rec.dst_ts, rec.out_time, getattr(self, "live_base", os.path.splitext(rec.dst_ts)[0])

    def stop_recording(self):
        """라이브 녹화를 멈추고 그때까지 받은 분량을 저장한다."""
        self._stop = True
        if self._recorder is not None:
            self._recorder.stop()

    def _fmt(self) -> str:
        if self.quality in ("1080", "720", "480"):
            h = self.quality
            return (f"bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<={h}]+bestaudio"
                    f"/best[height<={h}]/worstvideo[height>{h}]+bestaudio/worst[height>{h}]/best")
        return "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best"

    def _base_opts(self, hook) -> dict:
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
            "windowsfilenames": True,
            "retries": 3,
        }
        if ffdir:
            opts["ffmpeg_location"] = ffdir
        from . import live_record
        opts.update(live_record.ytdlp_cookie_opts(self.cookies))
        if self.headers:
            opts["http_headers"] = live_record.browser_headers(self.headers)
        elif self.referer:
            hdr = live_record.request_headers(self.referer)
            hdr.pop("User-Agent", None)
            opts["http_headers"] = hdr
        return opts

    def run(self):
        try:
            import yt_dlp
            from . import ytdlp_patches
            ytdlp_patches.apply()
        except ImportError:
            self.done.emit("", tr("yt-dlp 모듈이 없습니다 (pip install yt-dlp)"))
            return

        def hook(d):
            if self._cancel:
                raise yt_dlp.utils.DownloadCancelled()
            st = d.get("status")
            if st == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                got = d.get("downloaded_bytes") or 0
                frac = got / total if total else 0.0
                spd = d.get("_speed_str") or ""
                eta = d.get("_eta_str") or ""
                self.progress.emit(min(frac, 0.99), tr("받는 중 {0} {1}").format(spd, eta).strip())
            elif st == "finished":
                self.progress.emit(0.99, tr("합치는 중…"))

        try:
            from . import live_record
            msg = "" if self.stream else live_record.unsupported_page(self.url)
            if msg:
                raise live_record.LiveError(msg)
            if (self.stream or live_record.is_m3u8(self.url)) and not self.section:
                path = self._download_m3u8(yt_dlp, hook)
            elif self.section:
                path = self._download_section(yt_dlp, hook)
            else:
                path = self._download_full(yt_dlp, hook)
            if path and os.path.exists(path):
                self.progress.emit(1.0, tr("완료"))
                self.done.emit(path, "")
            else:
                self.done.emit("", tr("다운로드는 끝났지만 파일을 찾지 못했습니다"))
        except Exception as ex:  # DownloadCancelled 포함
            if self._cancel:
                self.done.emit("", tr("취소됨"))
            else:
                LOG.exception("다운로드 실패: %s", self.url)
                msg = str(ex)
                if "ERROR:" in msg:
                    msg = msg.split("ERROR:", 1)[1].strip()
                self.done.emit("", msg[:400])

    # ---- m3u8 주소 직접 (라이브면 녹화) ----
    def _download_m3u8(self, yt_dlp, hook) -> str:
        from . import live_record as lr
        from .segments import safe_filename
        self.progress.emit(0.0, tr("재생 목록 확인 중…"))
        if self.headers:
            cookie, headers = "", lr.browser_headers(self.headers)
        else:
            cookie = lr.cookie_header(self.cookies, self.url)
            headers = lr.request_headers(self.referer, cookie)
        max_h = int(self.quality) if self.quality in ("1080", "720", "480") else 0
        media_url, live = lr.resolve(self.url, headers, max_h)
        host = urllib.parse.urlparse(self.url).netloc.split(":")[0] or "stream"
        stamp = time.strftime("%Y%m%d_%H%M%S")
        base = os.path.join(self.out_dir, safe_filename(f"{(self.title or host)[:80]} {stamp}"))
        if not live:
            LOG.info("m3u8 VOD 받기: %s", media_url[:120])
            opts = self._base_opts(hook)
            opts["outtmpl"] = base + ".%(ext)s"
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(media_url, download=True)
                req = (info or {}).get("requested_downloads") or []
                path = req[0].get("filepath") if req else ydl.prepare_filename(info)
            return path or ""
        return self._record_live(yt_dlp, media_url, base, self.referer, cookie, headers if self.headers else None)

    def _record_live(self, yt_dlp, media_url: str, base: str, referer: str = "", cookie: str = "",
                     headers: dict | None = None) -> str:
        """라이브 HLS 를 우리 녹화기로: '녹화 중지 (저장)' · 취소가 바로 듣는다. base + .ts → .mp4"""
        from . import live_record as lr
        LOG.info("라이브 녹화 시작: %s", media_url[:120])
        ts = base + ".ts"
        rec = lr.LiveRecorder(media_url, ts, referer, cookie, headers=headers)
        self.live_base = base   # 실시간 클립은 base + '_clips' 폴더에
        self._recorder = rec
        rec.start()
        self.liveStarted.emit()
        t0 = time.time()

        def prog(out_t, size):
            self.progress.emit(0.5, tr("녹화 중 {0} · {1:.0f} MB (녹화 중지를 누르면 저장)").format(
                time.strftime("%H:%M:%S", time.gmtime(out_t or (time.time() - t0))), size / 1e6))
        code = rec.poll_progress(prog, lambda: self._cancel or self._stop)
        self._recorder = None
        if self._cancel and not self._stop:
            for p in (ts,):
                try:
                    os.remove(p)
                except OSError:
                    pass
            raise yt_dlp.utils.DownloadCancelled()
        if not os.path.isfile(ts) or os.path.getsize(ts) < 1024:
            raise lr.LiveError(tr("녹화된 내용이 없습니다. ") + " / ".join(rec.stderr_tail[-3:]))
        LOG.info("라이브 녹화 종료 code=%s %.1fs %.1fMB", code, rec.out_time, rec.size / 1e6)
        self.progress.emit(0.97, tr("mp4 로 정리 중…"))
        mp4 = base + ".mp4"
        if lr.remux_to_mp4(ts, mp4):
            for _ in range(20):   # 막 딴 실시간 클립이 아직 .ts 를 읽고 있으면 지워지지 않으므로 잠깐 기다렸다 다시
                try:
                    os.remove(ts)
                    break
                except FileNotFoundError:
                    break
                except OSError:
                    time.sleep(0.5)
            return mp4
        return ts  # 정리에 실패해도 .ts 는 그대로 열 수 있다

    @staticmethod
    def _live_hls(ydl, info: dict) -> tuple[str, dict] | None:
        """라이브이고 골라진 포맷이 HLS 하나면 (재생 목록 주소, 보낼 헤더). 아니면 None (yt-dlp 가 받음)."""
        if not info or info.get("_type") == "playlist" or not info.get("is_live"):
            return None
        fmts = info.get("requested_formats") or [info]
        if len(fmts) != 1 or not (fmts[0].get("protocol") or "").startswith("m3u8") or not fmts[0].get("url"):
            return None
        f = fmts[0]
        headers = dict(info.get("http_headers") or {})
        headers.update(f.get("http_headers") or {})
        try:
            cookie = ydl.cookiejar.get_cookie_header(f["url"])
        except Exception:
            cookie = ""
        if cookie:
            headers["Cookie"] = cookie
        return f["url"], headers

    @staticmethod
    def _allow_hls_extensions(params: dict, info: dict):
        """골라진 포맷이 모두 HLS 면 ffmpeg 입력의 조각 확장자 검사를 끈다 (치지직 라이브의 .m4v 조각).
        HLS 가 아닌 입력에 주면 ffmpeg 가 'Option not found' 로 실패하므로 HLS 일 때만."""
        from .live_record import HLS_INPUT_ARGS
        if not info or info.get("_type") == "playlist":
            return
        fmts = info.get("requested_formats") or [info]
        if all((f.get("protocol") or "").startswith("m3u8") for f in fmts):
            params["external_downloader_args"] = {"ffmpeg_i": list(HLS_INPUT_ARGS)}

    # ---- 전체 ----
    def _download_full(self, yt_dlp, hook) -> str:
        result = {"path": ""}

        def pp_hook(d):
            if d.get("status") == "finished" and d.get("postprocessor") in ("MoveFiles", "Merger"):
                info = d.get("info_dict") or {}
                p = info.get("filepath") or info.get("_filename")
                if p:
                    result["path"] = p

        opts = self._base_opts(hook)
        opts["postprocessor_hooks"] = [pp_hook]
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(self.url, download=False)   # 먼저 어떤 포맷이 골라지는지 보고
            live = self._live_hls(ydl, info)
            if live:
                # 라이브(치지직 · 유튜브 라이브 등): yt-dlp 는 주소만 찾고 녹화는 우리 녹화기로
                # (yt-dlp 의 ffmpeg 녹화는 취소가 안 듣고 '녹화 중지 (저장)' 도 없다)
                from .segments import safe_filename
                stamp = time.strftime("%Y%m%d_%H%M%S")
                name = self.title or str(info.get("uploader") or info.get("channel") or info.get("title") or "live")
                base = os.path.join(self.out_dir, safe_filename(f"{name[:80]} {stamp}"))
                return self._record_live(yt_dlp, live[0], base, headers=live[1])
            self._allow_hls_extensions(ydl.params, info)
            info = ydl.process_ie_result(info, download=True)
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
        return path

    # ---- 구간 ----
    def _download_section(self, yt_dlp, hook) -> str:
        from . import hls_section
        from .segments import fmt_time_file, safe_filename
        start, end = self.section
        self.progress.emit(0.0, tr("영상 정보 읽는 중…"))
        opts = self._base_opts(hook)
        with yt_dlp.YoutubeDL(dict(opts, skip_download=True)) as ydl:
            info = ydl.extract_info(self.url, download=False)
        if info.get("_type") == "playlist":
            info = (info.get("entries") or [None])[0] or info
        title = safe_filename(str(info.get("title") or info.get("id") or "video"))[:80]
        vid = info.get("id") or "x"
        duration = float(info.get("duration") or 0)
        if duration and start >= duration:
            raise RuntimeError(tr("시작 시각이 영상 길이({0})를 넘습니다").format(fmt_time_file(duration)))
        if duration:
            end = min(end, duration)
        base = os.path.join(self.out_dir, f"{title} [{vid}] {fmt_time_file(start)}-{fmt_time_file(end)}")
        dst = base + ".mp4"

        fmts = info.get("requested_formats") or [info]
        hls = [f for f in fmts if (f.get("protocol") or "").startswith("m3u8")]
        if len(fmts) == 1 and hls:
            # 묶인(muxed) HLS → 세그먼트 직접 선택 (토큰 붙은 네이버 VOD 포함)
            f = fmts[0]
            ts = base + ".ts"
            self.progress.emit(0.02, tr("세그먼트 목록 읽는 중…"))
            seg_start, _seg_end = hls_section.download_section(
                f["url"], start, end, ts, f.get("extra_param_to_segment_url", ""),
                lambda p, t: self.progress.emit(0.02 + p * 0.9, t), lambda: self._cancel)
            self.progress.emit(0.93, tr("잘라서 mp4 로 저장 중…"))
            cutter = ffmpeg_tools.Cutter()
            # 받은 조각의 앞부분(seg_start~start)을 잘라낸다. 키프레임 단위.
            cutter.cut_copy(ts, max(0.0, start - seg_start), max(0.0, start - seg_start) + (end - start), dst,
                            lambda p: self.progress.emit(0.93 + p * 0.06, tr("저장 중…")))
            try:
                os.remove(ts)
            except OSError:
                pass
            return dst
        # 그 외: yt-dlp 구간 다운로드 (ffmpeg 필요)
        opts["download_ranges"] = yt_dlp.utils.download_range_func(None, [(start, end)])
        opts["force_keyframes_at_cuts"] = False
        opts["outtmpl"] = base + ".%(ext)s"
        self._allow_hls_extensions(opts, info)   # 구간 받기는 ffmpeg 가 HLS 를 직접 연다
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([self.url])
        if os.path.exists(dst):
            return dst
        for name in os.listdir(self.out_dir):
            if name.startswith(os.path.basename(base)):
                return os.path.join(self.out_dir, name)
        return ""


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
    # ---- 출력 효과 (키워드 인자, 기본값이면 예전과 같은 동작) ----
    normalize: bool = False          # 음량 정규화: loudnorm → aac (영상은 복사 가능)
    caption: str = ""                # 영상에 굽는 캡션 글자 (재인코딩)
    subtitle_path: str = ""          # 굽는 자막 파일 .srt/.ass (재인코딩, 구간 시작에 맞춰 시각 이동)
    layout: str = "crop"             # 세로 출력 레이아웃: crop | blur
    watermark: str = ""              # 워터마크 PNG 경로 (재인코딩)
    watermark_pos: str = "br"        # tl | tr | bl | br
    watermark_opacity: float = 0.8
    intro: str = ""                  # 앞에 붙일 영상 (재인코딩 출력에만)
    outro: str = ""                  # 뒤에 붙일 영상 (재인코딩 출력에만)
    mute: bool = False               # 영상만: 다 만든 뒤 오디오를 빼고 비디오만 복사 (audio 와 함께 쓰지 않음)

    @property
    def label(self) -> str:
        return os.path.basename(self.dst)

    @property
    def total_duration(self) -> float:
        return sum(p.end - p.start for p in self.parts)

    @property
    def has_overlays(self) -> bool:
        """캡션 · 자막 · 워터마크 중 하나라도 있으면 (재인코딩이 필요)."""
        return bool(self.caption.strip() or self.subtitle_path or self.watermark)

    @property
    def needs_encode(self) -> bool:
        """비디오를 재인코딩하는 출력인지 (정확하게 · 세로 · 캡션/자막/워터마크). 오디오만 출력은 False."""
        return not self.audio and (self.mode == "precise" or self.vertical is not None or self.has_overlays)

    def render_options(self, normalize: bool | None = None) -> RenderOptions:
        return RenderOptions(vertical=self.vertical, layout=self.layout, caption=self.caption,
                             subtitle_path=self.subtitle_path, watermark=self.watermark,
                             watermark_pos=self.watermark_pos, watermark_opacity=self.watermark_opacity,
                             normalize=self.normalize if normalize is None else normalize)


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
    @staticmethod
    def _effects_note(job: ExportJob) -> str:
        names = []
        if job.vertical is not None:
            names.append(tr("세로 9:16 블러") if job.layout == "blur" else tr("세로 9:16"))
        if job.caption.strip():
            names.append(tr("캡션"))
        if job.subtitle_path:
            names.append(tr("자막"))
        if job.watermark:
            names.append(tr("워터마크"))
        return tr("재인코딩") + (f" ({', '.join(names)})" if names else "")

    def _cut_one(self, cutter: Cutter, job: ExportJob, part: ExportPart, dst: str, cb,
                 normalize: bool | None = None) -> str:
        """구간 하나를 dst 로. normalize 를 넘기면 작업 설정 대신 그 값을 쓴다 (합치기는 마지막 단계에서 한 번만)."""
        norm = job.normalize if normalize is None else normalize
        if job.audio:
            cutter.cut_audio(job.src, part.start, part.end, dst, job.audio, job.info.get("acodec", ""), cb, normalize=norm)
            return tr("오디오")
        if job.has_overlays or (job.vertical is not None and job.layout == "blur"):
            cutter.cut_render(job.src, part.start, part.end, dst, job.info, job.render_options(norm), cb, job.gpu)
            return self._effects_note(job)
        if job.vertical is not None:
            cutter.cut_vertical(job.src, part.start, part.end, dst, job.info, job.vertical, cb, job.gpu, normalize=norm)
            return tr("세로 9:16")
        if job.mode == "precise":
            cutter.cut_encode(job.src, part.start, part.end, dst, cb, "h264", job.gpu,
                              audio_args=audio_normalize_args() if norm else None)
            return tr("재인코딩")
        if job.mode == "smart":
            how = cutter.cut_smart(job.src, part.start, part.end, dst, job.info, job.keyframes, cb, job.gpu, normalize=norm)
            return {"copy": tr("복사"), "smart": tr("스마트"), "encode": tr("재인코딩")}.get(how, how)
        cutter.cut_copy(job.src, part.start, part.end, dst, cb, normalize=norm)
        return tr("복사") + (tr(" + 음량 정규화") if norm else "")

    # ---- 합치기 ----
    def _merge(self, i: int, cutter: Cutter, job: ExportJob, dst: str | None = None, cb=None,
               normalize: bool | None = None) -> str:
        """여러 구간을 dst 하나로. 조각은 정규화 없이 만들고 마지막 concat 에서 한 번만 정규화한다."""
        total = job.total_duration
        dst = dst or job.dst
        cb = cb or (lambda p: self.jobProgress.emit(i, p))
        norm = job.normalize if normalize is None else normalize
        if job.mode == "fast" and not job.audio and not job.needs_encode:
            # 원본에서 구간들을 바로 읽어 한 번에 이어 붙인다 (임시 파일 없음)
            cutter.concat([(job.src, p.start, p.end) for p in job.parts], dst, cb, total, normalize=norm)
            return tr("{0}개 구간 합침").format(len(job.parts))
        tmp = tempfile.mkdtemp(prefix="clipslicer_merge_")
        try:
            ext = os.path.splitext(dst)[1]
            entries: list = []
            done = 0.0
            heads = 0
            for n, part in enumerate(job.parts):
                plen = part.end - part.start
                prog = lambda p, d=done, l=plen: cb(0.9 * (d + p * l) / total)  # noqa: E731
                if job.mode == "smart" and not job.audio and not job.needs_encode:
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
                    self._cut_one(cutter, job, part, f, prog, normalize=False)
                    entries.append(f)
                done += plen
            cutter.concat(entries, dst, lambda p: cb(0.9 + 0.1 * p), total, normalize=norm)
            return tr("{0}개 구간 합침").format(len(job.parts)) + (tr(", 앞조각 {0}개 재인코딩").format(heads) if heads else "")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _export_main(self, i: int, cutter: Cutter, job: ExportJob, dst: str, cb, normalize: bool | None = None) -> str:
        if len(job.parts) == 1:
            return self._cut_one(cutter, job, job.parts[0], dst, cb, normalize)
        return self._merge(i, cutter, job, dst, cb, normalize)

    def _run_job(self, i: int, job: ExportJob) -> str:
        if not job.mute or job.audio:
            return self._run_job_av(i, job)
        # 영상만: 평소대로 만든 뒤 오디오를 빼고 비디오만 복사 (모든 방식 · 합치기 · 인트로에 똑같이 적용)
        tmp = tempfile.mkdtemp(prefix="clipslicer_mute_")
        final = job.dst
        try:
            job.dst = os.path.join(tmp, "full" + (os.path.splitext(final)[1] or ".mp4"))
            job.normalize = False  # 소리를 버리니 정규화할 필요 없음
            note = self._run_job_av(i, job, lambda p: self.jobProgress.emit(i, 0.95 * p))
            cutter = Cutter()
            self._cutter = cutter
            try:
                cutter.strip_audio(job.dst, final, job.total_duration, lambda p: self.jobProgress.emit(i, 0.95 + 0.05 * p))
            finally:
                self._cutter = None
            return note + tr(", 소리 제거")
        finally:
            job.dst = final
            shutil.rmtree(tmp, ignore_errors=True)

    def _run_job_av(self, i: int, job: ExportJob, progress=None) -> str:
        progress = progress or (lambda p: self.jobProgress.emit(i, p))
        cutter = Cutter()
        self._cutter = cutter
        try:
            if job.mode == "smart" and not job.keyframes and not job.audio:
                # 키프레임 분석이 아직 안 끝났으면 지금 한다 (없으면 전체 재인코딩으로 빠져 느려짐)
                job.keyframes = ffmpeg_tools.keyframes(job.src)
            extras = [p for p in (job.intro, job.outro) if p]
            if extras and not job.needs_encode:
                LOG.info("인트로/아웃트로는 재인코딩 출력(정확하게·세로·캡션·자막·워터마크)에만 붙입니다 — 건너뜀: %s", job.dst)
                extras = []
            if not extras:
                return self._export_main(i, cutter, job, job.dst, progress)
            # 본편을 임시로 만든 뒤 인트로/아웃트로와 같은 규격으로 다시 인코딩해 이어 붙인다 (정규화는 이때 한 번만)
            tmp = tempfile.mkdtemp(prefix="clipslicer_intro_")
            try:
                main = os.path.join(tmp, "main" + (os.path.splitext(job.dst)[1] or ".mp4"))
                note = self._export_main(i, cutter, job, main, lambda p: progress(0.8 * p), normalize=False)
                m = ffmpeg_tools.probe(main)
                files = [f for f in (job.intro, main, job.outro) if f]
                cutter.concat_render(files, job.dst, lambda p: progress(0.8 + 0.2 * p),
                                     size=(m["width"], m["height"]), fps=m["fps"], gpu=job.gpu, normalize=job.normalize)
                return note + tr(", 인트로/아웃트로 붙임")
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        finally:
            self._cutter = None

    @staticmethod
    def _drop_missing_files(job: ExportJob):
        """없는 자막 · 워터마크 · 인트로 · 아웃트로 파일은 경고만 남기고 무시한다."""
        for name in ("subtitle_path", "watermark", "intro", "outro"):
            p = getattr(job, name)
            if p and not os.path.isfile(p):
                LOG.warning("%s 파일이 없어 무시: %s", name, p)
                setattr(job, name, "")

    def run(self):
        ok_n = fail_n = 0
        for i, job in enumerate(self.jobs):
            if self._cancel:
                break
            self.jobStarted.emit(i, job.label)
            self._drop_missing_files(job)
            LOG.info("내보내기 [%d/%d] %s mode=%s audio=%s parts=%d gpu=%s normalize=%s caption=%s subtitle=%s "
                     "layout=%s watermark=%s intro=%s outro=%s", i + 1, len(self.jobs), job.dst,
                     job.mode, job.audio or "-", len(job.parts), job.gpu, job.normalize, bool(job.caption.strip()),
                     job.subtitle_path or "-", job.layout, job.watermark or "-", job.intro or "-", job.outro or "-")
            if job.has_overlays and job.mode != "precise":
                LOG.info("캡션/자막/워터마크는 재인코딩이 필요해 '%s' 대신 '정확하게' 방식으로 처리: %s", job.mode, job.dst)
            os.makedirs(os.path.dirname(job.dst) or ".", exist_ok=True)
            try:
                note = self._run_job(i, job)
                ok, msg = True, note
            except Cancelled:
                ok, msg = False, tr("취소됨")
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
