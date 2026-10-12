"""자르기 마커 -> 구간 모델, 실행 취소 스냅샷, 작업 파일 저장/복원."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

PROJECT_SUFFIX = ".clipslicer.json"
DEFAULT_PATTERN = "{name}_{n}"


def fmt_time(t: float, ms: bool = True) -> str:
    if t < 0:
        t = 0.0
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    if ms:
        return f"{h:02d}:{m:02d}:{s:06.3f}" if h else f"{m:02d}:{s:06.3f}"
    return f"{h:d}:{m:02d}:{int(s):02d}" if h else f"{m:02d}:{int(s):02d}"


def fmt_time_file(t: float) -> str:
    """파일명에 쓸 수 있는 시각 표기 (01h02m03s)."""
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    return f"{h:02d}h{m:02d}m{s:02d}s" if h else f"{m:02d}m{s:02d}s"


def parse_time(text: str) -> float | None:
    """'1:23.5', '01:02:03', '83.5', '1h2m3s' 를 초로."""
    text = text.strip()
    if not text:
        return None
    m = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+(?:\.\d+)?)s?)?", text)
    if m and any(m.groups()):
        h, mi, s = m.groups()
        return int(h or 0) * 3600 + int(mi or 0) * 60 + float(s or 0)
    parts = text.split(":")
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        return None
    total = 0.0
    for n in nums:
        total = total * 60 + n
    return total


def safe_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", name).strip() or "clip"


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
    info: dict = field(default_factory=dict)
    markers: list[float] = field(default_factory=list)
    segments: list[Segment] = field(default_factory=list)
    thumbs: list = field(default_factory=list)   # [(time, QPixmap)]
    waveform: object = None                      # list[float] | None
    keyframes: list[float] = field(default_factory=list)
    last_position: float = 0.0
    undo_stack: list = field(default_factory=list)
    redo_stack: list = field(default_factory=list)
    dirty: bool = False

    @property
    def stem(self) -> str:
        return os.path.splitext(os.path.basename(self.path))[0]

    @property
    def ext(self) -> str:
        return os.path.splitext(self.path)[1] or ".mp4"

    @property
    def project_file(self) -> str:
        return self.path + PROJECT_SUFFIX

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

    def add_markers(self, times: list[float]) -> int:
        n = 0
        for t in times:
            if self.add_marker(t):
                n += 1
        return n

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

    def nearest_keyframe(self, t: float, tol: float) -> float | None:
        if not self.keyframes:
            return None
        best = min(self.keyframes, key=lambda k: abs(k - t))
        return best if abs(best - t) <= tol else None

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

    def auto_name(self, idx: int, pattern: str = DEFAULT_PATTERN) -> str:
        seg = self.segments[idx]
        values = {
            "name": self.stem, "n": f"{idx + 1:02d}",
            "start": fmt_time_file(seg.start), "end": fmt_time_file(seg.end),
            "dur": fmt_time_file(seg.duration),
        }
        try:
            out = pattern.format(**values)
        except (KeyError, IndexError, ValueError):
            out = DEFAULT_PATTERN.format(**values)
        return safe_filename(out)

    def output_name(self, idx: int, ext: str, pattern: str = DEFAULT_PATTERN) -> str:
        seg = self.segments[idx]
        base = safe_filename(seg.name.strip()) if seg.name.strip() else self.auto_name(idx, pattern)
        return base + ext

    def enabled_segments(self) -> list[tuple[int, Segment]]:
        return [(i, s) for i, s in enumerate(self.segments) if s.enabled and s.duration > 0.01]

    # ---- 실행 취소 ----
    def snapshot(self) -> tuple:
        return (tuple(self.markers), tuple((s.start, s.enabled, s.name) for s in self.segments))

    def restore(self, snap: tuple):
        markers, segs = snap
        self.markers = list(markers)
        self.segments = []
        self.rebuild_segments()
        by_start = {round(st, 3): (en, nm) for st, en, nm in segs}
        for s in self.segments:
            en_nm = by_start.get(round(s.start, 3))
            if en_nm:
                s.enabled, s.name = en_nm

    def push_undo(self):
        self.undo_stack.append(self.snapshot())
        if len(self.undo_stack) > 200:
            self.undo_stack.pop(0)
        self.redo_stack.clear()
        self.dirty = True

    def undo(self) -> bool:
        if not self.undo_stack:
            return False
        self.redo_stack.append(self.snapshot())
        self.restore(self.undo_stack.pop())
        self.dirty = True
        return True

    def redo(self) -> bool:
        if not self.redo_stack:
            return False
        self.undo_stack.append(self.snapshot())
        self.restore(self.redo_stack.pop())
        self.dirty = True
        return True

    # ---- 저장 / 복원 ----
    def to_json(self) -> dict:
        return {
            "version": 1,
            "video": os.path.basename(self.path),
            "duration": self.duration,
            "markers": self.markers,
            "segments": [{"start": s.start, "enabled": s.enabled, "name": s.name} for s in self.segments],
            "last_position": self.last_position,
        }

    def save(self) -> bool:
        try:
            with open(self.project_file, "w", encoding="utf-8") as f:
                json.dump(self.to_json(), f, ensure_ascii=False, indent=1)
            self.dirty = False
            return True
        except OSError:
            return False

    def load(self) -> bool:
        try:
            with open(self.project_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return False
        self.markers = [float(m) for m in data.get("markers", []) if 0 < float(m) < self.duration]
        self.markers.sort()
        self.segments = []
        self.rebuild_segments()
        by_start = {round(float(s["start"]), 3): s for s in data.get("segments", [])}
        for s in self.segments:
            d = by_start.get(round(s.start, 3))
            if d:
                s.enabled = bool(d.get("enabled", True))
                s.name = str(d.get("name", ""))
        self.last_position = float(data.get("last_position", 0.0))
        self.dirty = False
        return True

    def has_project_file(self) -> bool:
        return os.path.isfile(self.project_file)
