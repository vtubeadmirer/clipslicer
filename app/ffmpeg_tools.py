"""ffmpeg / ffprobe 호출 유틸리티.

프로브 · 썸네일 · 파형 · 키프레임 · 무음 감지 · 자르기(빠르게/정확하게/스마트) · 합치기 · 오디오 추출 · GPU 인코더 감지
"""
from __future__ import annotations

import array
import json
import os
import re
import shutil
import subprocess
import tempfile
from typing import Callable

from .paths import find_tool

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
ProgressCb = Callable[[float], None]


def _popen_kwargs():
    return dict(creationflags=CREATE_NO_WINDOW, stdin=subprocess.DEVNULL)


def _run(cmd: list[str], timeout: float | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, **_popen_kwargs())


# --------------------------------------------------------------------------- 분석
def probe(path: str) -> dict:
    """duration(초), width, height, fps, vcodec, acodec, pix_fmt, has_audio."""
    cmd = [
        find_tool("ffprobe"), "-v", "error", "-print_format", "json",
        "-show_entries",
        "format=duration:stream=codec_type,codec_name,width,height,r_frame_rate,avg_frame_rate,pix_fmt,profile",
        path,
    ]
    out = _run(cmd)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or "ffprobe 실패")
    data = json.loads(out.stdout)
    info = {"duration": float(data.get("format", {}).get("duration", 0) or 0),
            "width": 0, "height": 0, "fps": 30.0, "has_audio": False,
            "vcodec": "", "acodec": "", "pix_fmt": "", "profile": ""}
    for s in data.get("streams", []):
        if s.get("codec_type") == "video" and not info["width"]:
            info["width"] = int(s.get("width", 0) or 0)
            info["height"] = int(s.get("height", 0) or 0)
            info["vcodec"] = s.get("codec_name", "") or ""
            info["pix_fmt"] = s.get("pix_fmt", "") or ""
            info["profile"] = s.get("profile", "") or ""
            rate = s.get("avg_frame_rate") or s.get("r_frame_rate") or "30/1"
            try:
                n, d = rate.split("/")
                if float(d) > 0 and float(n) > 0:
                    info["fps"] = float(n) / float(d)
            except ValueError:
                pass
        elif s.get("codec_type") == "audio" and not info["has_audio"]:
            info["has_audio"] = True
            info["acodec"] = s.get("codec_name", "") or ""
    return info


def extract_thumbnails(path: str, duration: float, max_count: int = 300, height: int = 90) -> list[tuple[float, bytes]]:
    """영상 전체를 균등 분할한 썸네일(JPEG bytes) 목록. 1초 간격 이하로는 안 쪼갠다."""
    if duration <= 0:
        return []
    interval = max(duration / max_count, 1.0)
    tmp = tempfile.mkdtemp(prefix="clipslicer_thumbs_")
    pattern = os.path.join(tmp, "t_%05d.jpg")
    cmd = [find_tool("ffmpeg"), "-v", "error", "-y", "-i", path,
           "-vf", f"fps=1/{interval},scale=-2:{height}", "-q:v", "6", pattern]
    subprocess.run(cmd, capture_output=True, **_popen_kwargs())
    result = []
    for i, name in enumerate(sorted(os.listdir(tmp))):
        fp = os.path.join(tmp, name)
        with open(fp, "rb") as f:
            result.append((i * interval, f.read()))
        os.remove(fp)
    shutil.rmtree(tmp, ignore_errors=True)
    return result


def _chunk_peak(data: bytes) -> int:
    """s16le 바이트 덩어리의 절대 피크. audioop(C) 가 있으면 쓰고 없으면 순수 파이썬."""
    try:
        import audioop  # Python 3.12 까지 내장 (3.13 에서 제거)
        return audioop.max(data, 2)
    except ImportError:
        arr = array.array("h")
        arr.frombytes(data[: len(data) - len(data) % 2])
        return max((abs(x) for x in arr), default=0)


def compute_waveform(path: str, buckets: int = 4000) -> list[float] | None:
    """모노 8kHz PCM 으로 디코드한 뒤 bucket 별 피크(0~1) 목록."""
    cmd = [find_tool("ffmpeg"), "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "-"]
    proc = subprocess.run(cmd, capture_output=True, **_popen_kwargs())
    raw = proc.stdout
    n_samples = len(raw) // 2
    if proc.returncode != 0 or n_samples < 2:
        return None
    n = min(buckets, n_samples)
    per = n_samples // n
    peaks = [float(_chunk_peak(raw[i * per * 2:(i + 1) * per * 2])) for i in range(n)]
    top = max(peaks)
    return [v / top for v in peaks] if top > 0 else peaks


def keyframes(path: str) -> list[float]:
    """비디오 키프레임(I-frame) 시각 목록. 디코딩 없이 패킷만 읽어서 빠르다."""
    cmd = [find_tool("ffprobe"), "-v", "error", "-select_streams", "v:0",
           "-show_entries", "packet=pts_time,dts_time,flags", "-of", "csv=p=0", path]
    out = _run(cmd)
    if out.returncode != 0:
        return []
    kfs = []
    for line in out.stdout.splitlines():
        parts = line.strip().split(",")
        if len(parts) < 3 or "K" not in parts[2]:
            continue
        t = parts[0] if parts[0] not in ("N/A", "") else parts[1]
        try:
            kfs.append(float(t))
        except ValueError:
            pass
    kfs.sort()
    return kfs


def detect_silence(path: str, noise_db: float = -35.0, min_dur: float = 1.0) -> list[tuple[float, float]]:
    """silencedetect 필터로 (시작, 끝) 무음 구간 목록."""
    cmd = [find_tool("ffmpeg"), "-hide_banner", "-nostats", "-i", path, "-vn",
           "-af", f"silencedetect=noise={noise_db}dB:d={min_dur}", "-f", "null", "-"]
    out = _run(cmd)
    text = out.stderr
    starts = [float(m) for m in re.findall(r"silence_start:\s*([0-9.]+)", text)]
    ends = [float(m) for m in re.findall(r"silence_end:\s*([0-9.]+)", text)]
    spans = list(zip(starts, ends))
    if len(starts) > len(ends):  # 파일 끝까지 무음
        spans.append((starts[-1], float("inf")))
    return spans


# --------------------------------------------------------------------------- 인코더
_GPU_CACHE: dict[str, str | None] = {}


def detect_gpu_encoder(family: str = "h264") -> str | None:
    """사용 가능한 하드웨어 인코더 이름 (h264_nvenc / h264_qsv / h264_amf …) 또는 None."""
    if family in _GPU_CACHE:
        return _GPU_CACHE[family]
    found = None
    for enc in (f"{family}_nvenc", f"{family}_qsv", f"{family}_amf"):
        cmd = [find_tool("ffmpeg"), "-v", "error", "-f", "lavfi", "-i", "color=s=256x256:d=0.3:r=10",
               "-c:v", enc, "-f", "null", "-"]
        try:
            if _run(cmd, timeout=20).returncode == 0:
                found = enc
                break
        except subprocess.TimeoutExpired:
            pass
    _GPU_CACHE[family] = found
    return found


def video_encoder_args(family: str, gpu: str | None, crf: int = 18) -> list[str]:
    """family: h264 | hevc. gpu: detect_gpu_encoder 결과(없으면 None)."""
    if gpu:
        if gpu.endswith("nvenc"):
            return ["-c:v", gpu, "-preset", "p5", "-rc", "vbr", "-cq", str(crf + 4), "-b:v", "0"]
        if gpu.endswith("qsv"):
            return ["-c:v", gpu, "-global_quality", str(crf + 4), "-preset", "medium"]
        if gpu.endswith("amf"):
            return ["-c:v", gpu, "-quality", "balanced", "-rc", "cqp", "-qp_i", str(crf + 4), "-qp_p", str(crf + 4)]
    if family == "hevc":
        return ["-c:v", "libx265", "-preset", "fast", "-crf", str(crf + 4)]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf)]


AUDIO_ENCODERS = {
    "aac": ["-c:a", "aac", "-b:a", "192k"],
    "mp3": ["-c:a", "libmp3lame", "-b:a", "192k"],
    "opus": ["-c:a", "libopus", "-b:a", "128k"],
    "vorbis": ["-c:a", "libvorbis", "-q:a", "5"],
    "ac3": ["-c:a", "ac3", "-b:a", "384k"],
    "eac3": ["-c:a", "eac3", "-b:a", "384k"],
    "flac": ["-c:a", "flac"],
    "alac": ["-c:a", "alac"],
    "pcm_s16le": ["-c:a", "pcm_s16le"],
    "pcm_s24le": ["-c:a", "pcm_s24le"],
}


# --------------------------------------------------------------------------- 실행기
class CutProcess:
    """진행률 콜백을 주는 ffmpeg 실행기. cancel() 로 중단."""

    def __init__(self, cmd: list[str], duration: float):
        self.cmd = cmd
        self.duration = max(duration, 0.01)
        self.proc: subprocess.Popen | None = None
        self._cancelled = False

    def cancel(self):
        self._cancelled = True
        if self.proc and self.proc.poll() is None:
            self.proc.kill()

    def run(self, on_progress: ProgressCb) -> tuple[bool, str]:
        # stderr 를 stdout 으로 합쳐 파이프 하나만 읽는다.
        # (따로 두면 Windows 의 4KB 파이프 버퍼가 차서 ffmpeg 가 멈춘다)
        self.proc = subprocess.Popen(
            self.cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", **_popen_kwargs(),
        )
        assert self.proc.stdout is not None
        progress_keys = ("out_time_us=", "out_time_ms=", "frame=", "fps=", "bitrate=", "total_size=",
                         "out_time=", "dup_frames=", "drop_frames=", "speed=", "progress=", "stream_")
        other: list[str] = []
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            if line.startswith("out_time_us="):
                try:
                    on_progress(min(int(line.split("=", 1)[1]) / 1e6 / self.duration, 1.0))
                except ValueError:
                    pass
            elif not line.startswith(progress_keys):
                other.append(line)
                if len(other) > 20:
                    other.pop(0)
        self.proc.wait()
        if self._cancelled:
            return False, "취소됨"
        return self.proc.returncode == 0, "\n".join(other[-5:])


class Cancelled(Exception):
    pass


class Cutter:
    """한 구간(또는 합치기)을 여러 ffmpeg 단계로 처리. 단계마다 진행률을 합산해 보고한다."""

    def __init__(self):
        self._current: CutProcess | None = None
        self._cancelled = False

    def cancel(self):
        self._cancelled = True
        if self._current:
            self._current.cancel()

    def _step(self, cmd: list[str], duration: float, cb: ProgressCb) -> str:
        if self._cancelled:
            raise Cancelled()
        self._current = CutProcess(cmd, duration)
        ok, msg = self._current.run(cb)
        self._current = None
        if self._cancelled:
            raise Cancelled()
        if not ok:
            raise RuntimeError(msg or "ffmpeg 실패")
        return msg

    # ---- 기본 명령 ----
    @staticmethod
    def _base(src: str, start: float, dur: float) -> list[str]:
        return [find_tool("ffmpeg"), "-hide_banner", "-v", "error", "-y", "-nostats",
                "-ss", f"{start:.3f}", "-i", src, "-t", f"{dur:.3f}"]

    @staticmethod
    def _audio_args(audio: str, acodec: str) -> list[str]:
        """audio: 'copy' | 'aac' | 'mp3'"""
        if audio == "mp3":
            return ["-vn", "-c:a", "libmp3lame", "-q:a", "2"]
        if audio == "aac":
            return ["-vn"] + (["-c:a", "copy"] if acodec == "aac" else ["-c:a", "aac", "-b:a", "192k"])
        return []

    def cut_copy(self, src: str, start: float, end: float, dst: str, cb: ProgressCb, audio_only: str = ""):
        cmd = self._base(src, start, end - start)
        if audio_only:
            cmd += self._audio_args(audio_only, "")  # 코덱 모르면 재인코딩
        else:
            cmd += ["-c", "copy"]
        cmd += ["-avoid_negative_ts", "make_zero", "-progress", "pipe:1", dst]
        self._step(cmd, end - start, cb)

    def cut_audio(self, src: str, start: float, end: float, dst: str, fmt: str, acodec: str, cb: ProgressCb):
        cmd = self._base(src, start, end - start) + self._audio_args(fmt, acodec)
        cmd += ["-progress", "pipe:1", dst]
        self._step(cmd, end - start, cb)

    def cut_encode(self, src: str, start: float, end: float, dst: str, cb: ProgressCb,
                   family: str = "h264", gpu: str | None = None, extra_video: list[str] | None = None,
                   audio_args: list[str] | None = None):
        """프레임 단위 정확 재인코딩. 오디오도 같이 재인코딩해야 시작점이 정확해진다.

        (-ss 입력 탐색은 비디오 키프레임 기준이라, 오디오를 copy 하면 앞쪽에 여분이 붙는다)
        """
        cmd = self._base(src, start, end - start) + video_encoder_args(family, gpu)
        cmd += extra_video or ["-pix_fmt", "yuv420p"]
        cmd += audio_args if audio_args is not None else AUDIO_ENCODERS["aac"]
        cmd += ["-movflags", "+faststart", "-avoid_negative_ts", "make_zero", "-progress", "pipe:1", dst]
        self._step(cmd, end - start, cb)

    def cut_smart(self, src: str, start: float, end: float, dst: str, info: dict, kfs: list[float],
                  cb: ProgressCb, gpu: str | None = None) -> str:
        """시작~첫 키프레임만 재인코딩, 나머지는 복사, 둘을 이어 붙인다.

        반환: 실제로 쓴 방식 설명 ('copy' / 'smart' / 'encode').
        """
        vcodec = info.get("vcodec", "")
        fps = info.get("fps", 30.0) or 30.0
        frame = 1.0 / fps
        family = "h264" if vcodec == "h264" else "hevc" if vcodec in ("hevc", "h265") else None
        inside = [k for k in kfs if start - frame / 2 <= k <= end]
        if inside and inside[0] <= start + frame / 2:
            # 시작점이 이미 키프레임 → 그냥 복사
            self.cut_copy(src, start, end, dst, cb)
            return "copy"
        acodec = info.get("acodec", "")
        if info.get("has_audio"):
            audio_args = AUDIO_ENCODERS.get(acodec)
        else:
            audio_args = ["-an"]
        if family is None or not inside or audio_args is None:
            # 지원 안 하는 코덱이거나 구간 안에 키프레임이 없음 → 전체 재인코딩
            self.cut_encode(src, start, end, dst, cb, family or "h264", gpu)
            return "encode"
        k = inside[0]
        ext = os.path.splitext(dst)[1] or ".mp4"
        tmp = tempfile.mkdtemp(prefix="clipslicer_smart_")
        head = os.path.join(tmp, "head" + ext)
        tail = os.path.join(tmp, "tail" + ext)
        try:
            head_len, tail_len = k - start, end - k
            total = end - start
            extra = ["-pix_fmt", info.get("pix_fmt") or "yuv420p",
                     "-s", f"{info['width']}x{info['height']}", "-r", f"{fps:.6f}"]
            if family == "h264" and info.get("profile"):
                prof = info["profile"].lower().replace(" ", "")
                if prof in ("baseline", "main", "high"):
                    extra += ["-profile:v", prof]
            self.cut_encode(src, start, k, head, lambda p: cb(p * head_len / total),
                            family, gpu, extra_video=extra, audio_args=audio_args)
            self.cut_copy(src, k, end, tail, lambda p: cb((head_len + p * tail_len) / total))
            self.concat([head, tail], dst, lambda p: cb(0.98 + 0.02 * p))
            return "smart"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def concat(self, parts: list[str], dst: str, cb: ProgressCb):
        """같은 코덱의 파일들을 재인코딩 없이 이어 붙인다 (concat demuxer)."""
        lst = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8")
        try:
            for p in parts:
                lst.write("file '" + p.replace("\\", "/").replace("'", "'\\''") + "'\n")
            lst.close()
            total = 0.0
            for p in parts:
                try:
                    total += probe(p)["duration"]
                except Exception:
                    pass
            cmd = [find_tool("ffmpeg"), "-hide_banner", "-v", "error", "-y", "-nostats",
                   "-f", "concat", "-safe", "0", "-i", lst.name, "-c", "copy",
                   "-movflags", "+faststart", "-progress", "pipe:1", dst]
            self._step(cmd, max(total, 0.1), cb)
        finally:
            try:
                os.remove(lst.name)
            except OSError:
                pass
