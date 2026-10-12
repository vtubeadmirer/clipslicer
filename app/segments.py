"""자르기 마커 -> 구간 모델."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def fmt_time(t: float, ms: bool = True) -> str:
    if t < 0:
        t = 0.0
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    if ms:
        return f"{h:02d}:{m:02d}:{s:06.3f}" if h else f"{m:02d}:{s:06.3f}"
    return f"{h:d}:{m:02d}:{int(s):02d}" if h else f"{m:02d}:{int(s):02d}"


@dataclass
class Segment:
    start: float
    end: float
    enabled: bool = True
    name: str = ""  # 비어 있으면 자동 이름

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class ClipProject:
    """영상 한 개의 편집 상태."""
    path: str
    duration: float = 0.0
    fps: float = 30.0
    width: int = 0
    height: int = 0
    markers: list[float] = field(default_factory=list)
    segments: list[Segment] = field(default_factory=list)
    thumbs: list = field(default_factory=list)   # [(time, QPixmap)]
    waveform: object = None                      # np.ndarray | None
    last_position: float = 0.0

    @property
    def stem(self) -> str:
        return os.path.splitext(os.path.basename(self.path))[0]

    @property
    def ext(self) -> str:
        return os.path.splitext(self.path)[1] or ".mp4"

    # ---- 마커 ----
    def add_marker(self, t: float, min_gap: float = 0.05) -> bool:
        if t <= min_gap or t >= self.duration - min_gap:
            return False
        if any(abs(m - t) < min_gap for m in self.markers):
            return False
        self.markers.append(t)
        self.markers.sort()
        self.rebuild_segments()
        return True

    def move_marker(self, idx: int, t: float, min_gap: float = 0.05):
        lo = self.markers[idx - 1] + min_gap if idx > 0 else min_gap
        hi = self.markers[idx + 1] - min_gap if idx + 1 < len(self.markers) else self.duration - min_gap
        self.markers[idx] = min(max(t, lo), hi)
        self.rebuild_segments()

    def remove_marker(self, idx: int):
        if 0 <= idx < len(self.markers):
            self.markers.pop(idx)
            self.rebuild_segments()

    def nearest_marker(self, t: float, tol: float) -> int:
        best, best_d = -1, tol
        for i, m in enumerate(self.markers):
            d = abs(m - t)
            if d <= best_d:
                best, best_d = i, d
        return best

    def clear_markers(self):
        self.markers.clear()
        self.rebuild_segments()

    # ---- 구간 ----
    def rebuild_segments(self):
        """마커로 구간을 다시 만들되, 기존 구간의 사용/이름 설정은 시작 시각 기준으로 유지."""
        old = {round(s.start, 3): s for s in self.segments}
        bounds = [0.0] + list(self.markers) + [self.duration]
        new = []
        for a, b in zip(bounds, bounds[1:]):
            prev = old.get(round(a, 3))
            new.append(Segment(a, b, prev.enabled if prev else True, prev.name if prev else ""))
        self.segments = new

    def segment_at(self, t: float) -> int:
        for i, s in enumerate(self.segments):
            if s.start <= t < s.end:
                return i
        return len(self.segments) - 1 if self.segments else -1

    def output_name(self, idx: int, ext: str) -> str:
        seg = self.segments[idx]
        base = seg.name.strip() or f"{self.stem}_{idx + 1:02d}"
        return base + ext

    def enabled_segments(self) -> list[tuple[int, Segment]]:
        return [(i, s) for i, s in enumerate(self.segments) if s.enabled and s.duration > 0.01]
