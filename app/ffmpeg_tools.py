"""ffmpeg / ffprobe 호출 유틸리티 (프로브, 썸네일, 파형, 자르기)."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from typing import Callable

import numpy as np

from .paths import find_tool

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def _popen_kwargs():
    return dict(creationflags=CREATE_NO_WINDOW, stdin=subprocess.DEVNULL)


def probe(path: str) -> dict:
    """duration(초), width, height, fps, has_audio 반환."""
    ffprobe = find_tool("ffprobe")
    cmd = [
        ffprobe, "-v", "error", "-print_format", "json",
        "-show_entries", "format=duration:stream=codec_type,width,height,r_frame_rate,avg_frame_rate",
        path,
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", **_popen_kwargs())
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or "ffprobe 실패")
    data = json.loads(out.stdout)
    info = {"duration": float(data.get("format", {}).get("duration", 0) or 0),
            "width": 0, "height": 0, "fps": 30.0, "has_audio": False}
    for s in data.get("streams", []):
        if s.get("codec_type") == "video" and not info["width"]:
            info["width"] = int(s.get("width", 0) or 0)
            info["height"] = int(s.get("height", 0) or 0)
            rate = s.get("avg_frame_rate") or s.get("r_frame_rate") or "30/1"
            try:
                n, d = rate.split("/")
                if float(d) > 0 and float(n) > 0:
                    info["fps"] = float(n) / float(d)
            except ValueError:
                pass
        elif s.get("codec_type") == "audio":
            info["has_audio"] = True
    return info


def extract_thumbnails(path: str, duration: float, count: int = 80, height: int = 54) -> list[tuple[float, bytes]]:
    """영상 전체를 count 장으로 균등 분할한 썸네일(JPEG bytes) 목록."""
    if duration <= 0:
        return []
    interval = max(duration / count, 0.5)
    tmp = tempfile.mkdtemp(prefix="clipslicer_thumbs_")
    pattern = os.path.join(tmp, "t_%05d.jpg")
    cmd = [
        find_tool("ffmpeg"), "-v", "error", "-y", "-i", path,
        "-vf", f"fps=1/{interval},scale=-2:{height}",
        "-q:v", "5", pattern,
    ]
    subprocess.run(cmd, capture_output=True, **_popen_kwargs())
    result = []
    for i, name in enumerate(sorted(os.listdir(tmp))):
        fp = os.path.join(tmp, name)
        with open(fp, "rb") as f:
            result.append((i * interval, f.read()))
        os.remove(fp)
    try:
        os.rmdir(tmp)
    except OSError:
        pass
    return result


def compute_waveform(path: str, buckets: int = 2000) -> np.ndarray | None:
    """모노 8kHz PCM 으로 디코드한 뒤 bucket 별 피크(0~1) 배열."""
    cmd = [
        find_tool("ffmpeg"), "-v", "error", "-i", path,
        "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, **_popen_kwargs())
    if proc.returncode != 0 or len(proc.stdout) < 4:
        return None
    samples = np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32)
    if samples.size == 0:
        return None
    n = min(buckets, samples.size)
    trimmed = samples[: samples.size - samples.size % n]
    peaks = np.abs(trimmed.reshape(n, -1)).max(axis=1)
    peak = peaks.max()
    if peak > 0:
        peaks = peaks / peak
    return peaks


def build_cut_cmd(src: str, start: float, end: float, dst: str, precise: bool) -> list[str]:
    """구간 자르기 명령. precise=False 는 무손실(stream copy)."""
    dur = max(end - start, 0.01)
    cmd = [find_tool("ffmpeg"), "-hide_banner", "-v", "error", "-y", "-nostats",
           "-ss", f"{start:.3f}", "-i", src, "-t", f"{dur:.3f}"]
    if precise:
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k"]
    else:
        cmd += ["-c", "copy", "-avoid_negative_ts", "make_zero"]
    cmd += ["-progress", "pipe:1", dst]
    return cmd


class CutProcess:
    """진행률 콜백을 주는 ffmpeg 자르기 실행기. cancel() 로 중단."""

    def __init__(self, cmd: list[str], duration: float):
        self.cmd = cmd
        self.duration = max(duration, 0.01)
        self.proc: subprocess.Popen | None = None
        self._cancelled = False

    def cancel(self):
        self._cancelled = True
        if self.proc and self.proc.poll() is None:
            self.proc.kill()

    def run(self, on_progress: Callable[[float], None]) -> tuple[bool, str]:
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
        ok = self.proc.returncode == 0
        return ok, "\n".join(other[-5:])
