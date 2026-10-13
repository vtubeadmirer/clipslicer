"""자르기 마커 -> 구간 모델, 실행 취소 스냅샷, 작업 파일 저장/복원."""
from __future__ import annotations

from .i18n import tr
import json
import os
import re
import shutil
import statistics
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


_TS_RE = re.compile(r"(?<![\d:])(?:(\d{1,2}):)?(\d{1,3}):(\d{2})(?:[.,](\d{1,3}))?(?![\d:])")


def parse_timestamps(text: str) -> list[float]:
    """텍스트 안의 h:mm:ss / mm:ss(.ms) 시각을 모두 찾아 초 단위 정렬 목록으로 (중복 제거)."""
    found = set()
    for m in _TS_RE.finditer(text or ""):
        h, mi, s, frac = m.groups()
        t = int(h or 0) * 3600 + int(mi) * 60 + int(s)
        if frac:
            t += int(frac.ljust(3, "0")[:3]) / 1000
        found.add(round(t, 3))
    return sorted(found)


def safe_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", name).strip() or "clip"


@dataclass
class Segment:
    start: float
    end: float
    enabled: bool = True
    name: str = ""  # 비어 있으면 자동 이름
    note: str = ""  # 메모 (파일명·내보내기에는 영향 없음)

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
    clips: list[tuple[float, float]] = field(default_factory=list)   # I/O 로 지정한 클립 구간
    pending_in: float | None = None                                  # I 만 찍고 O 를 기다리는 중
    crop_x: float = 0.5                                              # 세로 크롭 위치 (0~1)
    merge_order: list[float] = field(default_factory=list)           # 합치기 순서 (구간 시작 시각). 비어 있으면 시간순
    source_url: str = ""                                             # 다운로드한 원본 URL (있을 때만)
    chat: object = None                                              # app/chat.py 채팅 데이터 (저장 안 함)
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
        self.clips.clear()
        self.pending_in = None
        self.rebuild_segments()

    # ---- 클립 모드 (I/O) ----
    def apply_clip(self, a: float, b: float) -> bool:
        """[a, b] 를 클립으로 등록: 양 끝에 마커를 찍고, 클립에 속한 구간만 켠다."""
        if b - a < 0.1:
            return False
        a = max(0.0, a)
        b = min(self.duration, b)
        for t in (a, b):
            if 0 < t < self.duration:
                self.add_marker(t)
        self.clips.append((a, b))
        self.clips.sort()
        self._apply_clip_enables()
        return True

    def _apply_clip_enables(self):
        for s in self.segments:
            s.enabled = any(s.start >= ca - 0.02 and s.end <= cb + 0.02 for ca, cb in self.clips)

    def chapter_text(self) -> str:
        """유튜브 설명란용 '00:00 이름' 목록 (켜진 구간)."""
        lines = []
        for i, s in enumerate(self.segments):
            if s.enabled:
                name = s.name.strip() or tr("구간 {0}").format(i + 1)
                lines.append(f"{fmt_time(s.start, ms=False).rjust(5, '0') if s.start < 3600 else fmt_time(s.start, ms=False)} {name}")
        return "\n".join(lines)

    # ---- 구간 ----
    def rebuild_segments(self):
        """마커로 구간을 다시 만들되, 기존 구간의 사용/이름/메모 설정은 시작 시각 기준으로 유지."""
        old = {round(s.start, 3): s for s in self.segments}
        bounds = [0.0] + list(self.markers) + [self.duration]
        new = []
        for a, b in zip(bounds, bounds[1:]):
            prev = old.get(round(a, 3))
            new.append(Segment(a, b, prev.enabled if prev else True, prev.name if prev else "", prev.note if prev else ""))
        self.segments = new
        self._prune_merge_order()

    def _prune_merge_order(self):
        """merge_order 에서 더 이상 존재하지 않는 시작 시각(과 중복)을 제거."""
        starts = {round(s.start, 3): s.start for s in self.segments}
        seen: set[float] = set()
        kept: list[float] = []
        for t in self.merge_order:
            k = round(float(t), 3)
            if k in starts and k not in seen:
                seen.add(k)
                kept.append(starts[k])
        self.merge_order = kept

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

    # ---- 합치기 순서 ----
    def ordered_enabled(self) -> list[tuple[int, Segment]]:
        """켜진 구간을 merge_order 순서로. merge_order 에 없는 구간은 그 뒤에 시간순."""
        segs = self.enabled_segments()
        if not self.merge_order:
            return segs
        rank = {round(t, 3): n for n, t in enumerate(self.merge_order)}
        tail = len(rank)
        return sorted(segs, key=lambda it: (rank.get(round(it[1].start, 3), tail), it[0]))

    def merge_position(self, idx: int) -> int:
        """구간 idx 가 합치기 순서에서 몇 번째인지 (0부터). 켜져 있지 않으면 -1."""
        for n, (i, _s) in enumerate(self.ordered_enabled()):
            if i == idx:
                return n
        return -1

    def _full_order(self) -> list[float]:
        """merge_order 를 전체 구간으로 펼친다: 켜진 구간은 ordered_enabled 순, 꺼진 구간은 그 뒤 시간순."""
        order = [s.start for _, s in self.ordered_enabled()]
        seen = {round(t, 3) for t in order}
        order += [s.start for s in self.segments if round(s.start, 3) not in seen]
        return order

    def move_in_order(self, idx: int, delta: int) -> bool:
        """구간 idx 를 합치기 순서에서 delta 칸 옮긴다 (음수 = 앞으로). 전체 순서를 merge_order 에 확정한다."""
        if not (0 <= idx < len(self.segments)) or delta == 0:
            return False
        order = self._full_order()
        key = round(self.segments[idx].start, 3)
        pos = next((i for i, t in enumerate(order) if round(t, 3) == key), -1)
        if pos < 0:
            return False
        new_pos = min(max(pos + delta, 0), len(order) - 1)
        if new_pos == pos:
            return False
        order.insert(new_pos, order.pop(pos))
        self.merge_order = order
        return True

    # ---- 실행 취소 ----
    def snapshot(self) -> tuple:
        return (tuple(self.markers), tuple((s.start, s.enabled, s.name, s.note) for s in self.segments),
                tuple(self.clips), tuple(self.merge_order))

    def restore(self, snap: tuple):
        markers, segs = snap[0], snap[1]
        self.clips = [tuple(c) for c in snap[2]] if len(snap) > 2 else []
        self.merge_order = list(snap[3]) if len(snap) > 3 else []
        self.pending_in = None
        self.markers = list(markers)
        self.segments = []
        self.rebuild_segments()
        by_start = {round(row[0], 3): row[1:] for row in segs}
        for s in self.segments:
            row = by_start.get(round(s.start, 3))
            if row:
                s.enabled, s.name = row[0], row[1]
                s.note = row[2] if len(row) > 2 else ""

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
            "segments": [{"start": s.start, "enabled": s.enabled, "name": s.name, "note": s.note} for s in self.segments],
            "clips": [list(c) for c in self.clips],
            "crop_x": self.crop_x,
            "merge_order": list(self.merge_order),
            "source_url": self.source_url,
            "last_position": self.last_position,
        }

    def save(self) -> bool:
        if os.path.isfile(self.project_file):
            try:  # 덮어쓰기 전 백업 (실패해도 저장은 계속)
                shutil.copyfile(self.project_file, self.project_file + ".bak")
            except OSError:
                pass
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
                s.note = str(d.get("note", ""))
        self.clips = [(float(a), float(b)) for a, b in data.get("clips", [])]
        self.crop_x = float(data.get("crop_x", 0.5))
        self.merge_order = [float(t) for t in data.get("merge_order", [])]
        self._prune_merge_order()
        self.source_url = str(data.get("source_url", "") or "")
        self.last_position = float(data.get("last_position", 0.0))
        self.dirty = False
        return True

    def has_project_file(self) -> bool:
        return os.path.isfile(self.project_file)


# --------------------------------------------------------------------------- 찾기 도우미
def loud_peaks(wave: list[float], duration: float, factor: float = 3.0, min_gap: float = 10.0,
               lead: float = 2.0, max_count: int = 50) -> list[float]:
    """파형(compute_waveform 의 0~1 bucket 피크 목록)에서 유난히 큰 소리(웃음·고함·환호)가 난 시각 목록.

    기준 = min(0.98, max(0 이 아닌 값들의 중앙값 * factor, 0.05)). 기준을 넘는 연속 bucket 을 한 덩어리로 묶고
    덩어리마다 가장 큰 bucket 을 대표로 삼은 뒤, 큰 순서대로 고르되 이미 고른 시각과 min_gap 초 이상 떨어진 것만
    max_count 개까지 고른다. 돌려주는 값은 각 시각에서 lead 초 앞당긴(0 미만은 0) 오름차순 목록 —
    클립이 반응 조금 전부터 시작하도록.
    """
    if not wave or duration <= 0:
        return []
    nonzero = [v for v in wave if v > 0]
    if not nonzero:
        return []
    median = statistics.median(nonzero)
    threshold = min(0.98, max(median * factor, 0.05))
    if threshold <= median:  # 평평한 파형: 두드러진 곳이 없다
        return []
    per = duration / len(wave)
    groups: list[tuple[float, int]] = []   # (대표 피크, bucket 번호)
    best: tuple[float, int] | None = None
    for i, v in enumerate(wave):
        if v > threshold:
            if best is None or v > best[0]:
                best = (v, i)
        elif best is not None:
            groups.append(best)
            best = None
    if best is not None:
        groups.append(best)
    chosen: list[float] = []
    for _v, i in sorted(groups, key=lambda g: (-g[0], g[1])):
        if len(chosen) >= max_count:
            break
        t = i * per
        if all(abs(t - c) >= min_gap for c in chosen):
            chosen.append(t)
    return sorted(round(max(0.0, t - lead), 3) for t in chosen)


def bookmarks_to_markers(bookmarks: list[float], file_end_epoch: float, duration: float) -> list[float]:
    """벽시계 북마크(epoch 초)를 영상 시각으로 바꾼다. 파일 수정 시각(mtime)이 녹화가 끝난 시각이라고 가정.

    0 < t < duration 인 것만 남기고, 중복 제거 후 소수 3자리 오름차순.
    """
    if duration <= 0:
        return []
    start_epoch = float(file_end_epoch) - float(duration)
    out: set[float] = set()
    for b in bookmarks:
        t = round(float(b) - start_epoch, 3)
        if 0 < t < duration:
            out.add(t)
    return sorted(out)
