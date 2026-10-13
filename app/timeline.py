"""타임라인 위젯: 썸네일 띠 + 파형 + 채팅 반응 그래프 + 구간 블록 + 키프레임 + 자르기 마커 + 플레이헤드.

확대/축소(Ctrl+휠), 가로 스크롤(휠), 호버 썸네일 미리보기 지원.
project.chat (app.chat.ChatData) 이 있으면 띠 아래쪽 절반에 주황색 반응 그래프를 겹쳐 그린다.
"""
from __future__ import annotations

from .i18n import tr
import math

from PySide6.QtCore import Qt, Signal, QRectF, QPointF, QPoint, QSize
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QPolygonF, QFont, QPixmap, QLinearGradient
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout, QScrollBar, QSizePolicy

from .segments import ClipProject, fmt_time

THUMB_H = 64
RULER_H = 18
MARKER_TOL_PX = 7

SEG_COLORS = [QColor(66, 165, 245), QColor(102, 187, 106), QColor(255, 167, 38),
              QColor(171, 71, 188), QColor(38, 198, 218), QColor(239, 83, 80),
              QColor(255, 213, 79), QColor(129, 199, 132)]


def seg_color(i: int) -> QColor:
    return QColor(SEG_COLORS[i % len(SEG_COLORS)])


class PreviewPopup(QLabel):
    """타임라인 위에 뜨는 썸네일 + 시각 팝업."""

    def __init__(self):
        super().__init__(None, Qt.ToolTip | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setStyleSheet("background: #111; color: #eee; border: 1px solid #555; padding: 3px; font-size: 11px;")
        self.setAlignment(Qt.AlignCenter)
        self._thumb = QLabel(self)
        self._time = QLabel(self)
        self._time.setAlignment(Qt.AlignCenter)
        self._time.setStyleSheet("border: none; padding: 0; font-family: Consolas, monospace;")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        lay.addWidget(self._thumb)
        lay.addWidget(self._time)

    def show_at(self, global_pos: QPoint, pix: QPixmap | None, text: str):
        if pix is not None:
            self._thumb.setPixmap(pix.scaledToHeight(120, Qt.SmoothTransformation))
            self._thumb.show()
        else:
            self._thumb.hide()
        self._time.setText(text)
        self.adjustSize()
        self.move(global_pos.x() - self.width() // 2, global_pos.y() - self.height() - 8)
        self.show()


class TimelineCanvas(QWidget):
    seekRequested = Signal(float, bool)      # (time, final)
    markerDragStarted = Signal()
    markerMoved = Signal(int, float, bool)   # (idx, time, final)
    markerDeleted = Signal(int)
    segmentToggled = Signal(int)
    segmentLoopRequested = Signal(int)
    addMarkerRequested = Signal(float)
    viewChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project: ClipProject | None = None
        self.position = 0.0
        self.hover_x = -1
        self.drag_marker = -1
        self.scrubbing = False
        self.loop_segment = -1
        self.show_keyframes = True
        self.follow = True
        # 보기 영역 (초)
        self.view_start = 0.0
        self.view_len = 0.0
        self.popup = PreviewPopup()
        self.setFixedHeight(THUMB_H + RULER_H + 8)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    # ---- 좌표 변환 ----
    @property
    def duration(self) -> float:
        return self.project.duration if self.project else 0.0

    def x_to_t(self, x: float) -> float:
        if self.view_len <= 0 or self.width() <= 0:
            return 0.0
        t = self.view_start + x / self.width() * self.view_len
        return max(0.0, min(self.duration, t))

    def t_to_x(self, t: float) -> float:
        if self.view_len <= 0:
            return 0.0
        return (t - self.view_start) / self.view_len * self.width()

    def px_tol_sec(self, px: float) -> float:
        return px / max(self.width(), 1) * self.view_len

    # ---- 외부 API ----
    def set_project(self, project: ClipProject | None):
        self.project = project
        self.position = project.last_position if project else 0.0
        self.loop_segment = -1
        self.view_start = 0.0
        self.view_len = self.duration
        self.viewChanged.emit()
        self.update()

    def set_position(self, t: float):
        self.position = t
        if self.follow and self.duration > 0 and self.view_len < self.duration and not self.scrubbing:
            if t < self.view_start or t > self.view_start + self.view_len:
                self._set_view(t - self.view_len * 0.1, self.view_len)
        self.update()

    def set_loop_segment(self, idx: int):
        self.loop_segment = idx
        self.update()

    def zoom_factor(self) -> float:
        return self.duration / self.view_len if self.view_len > 0 else 1.0

    def _set_view(self, start: float, length: float):
        length = max(min(length, self.duration), min(2.0, self.duration))
        start = max(0.0, min(start, self.duration - length))
        if abs(start - self.view_start) > 1e-9 or abs(length - self.view_len) > 1e-9:
            self.view_start, self.view_len = start, length
            self.viewChanged.emit()
            self.update()

    def zoom(self, factor: float, anchor_t: float | None = None):
        if self.duration <= 0:
            return
        if anchor_t is None:
            anchor_t = self.position
        new_len = self.view_len / factor
        frac = (anchor_t - self.view_start) / self.view_len if self.view_len > 0 else 0.5
        self._set_view(anchor_t - frac * new_len, new_len)

    def zoom_reset(self):
        self._set_view(0.0, self.duration)

    def scroll_to(self, start: float):
        self._set_view(start, self.view_len)

    # ---- 그리기 ----
    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor(24, 24, 28))

        if not self.project or self.duration <= 0:
            p.setPen(QColor(110, 110, 120))
            p.drawText(self.rect(), Qt.AlignCenter, tr("영상을 열거나 여기에 끌어다 놓으세요"))
            return

        band = QRectF(0, 0, w, THUMB_H)
        self._draw_thumbs(p, band)
        self._draw_chat(p, band)
        self._draw_waveform(p, band)
        self._draw_segments(p, band)
        self._draw_ruler(p, QRectF(0, THUMB_H, w, RULER_H))
        if self.show_keyframes:
            self._draw_keyframes(p, h)
        self._draw_markers(p, h)
        self._draw_pending_in(p, h)
        self._draw_playhead(p, h)
        if self.hover_x >= 0 and not self.scrubbing and self.drag_marker < 0:
            p.setPen(QPen(QColor(255, 255, 255, 90), 1))
            p.drawLine(self.hover_x, 0, self.hover_x, h)

    def _thumb_for(self, t: float):
        thumbs = self.project.thumbs
        if not thumbs:
            return None
        # 이진 탐색으로 가장 가까운 썸네일
        lo, hi = 0, len(thumbs) - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if thumbs[mid][0] < t:
                lo = mid + 1
            else:
                hi = mid
        cands = [thumbs[lo]]
        if lo > 0:
            cands.append(thumbs[lo - 1])
        return min(cands, key=lambda th: abs(th[0] - t))[1]

    def _draw_thumbs(self, p: QPainter, band: QRectF):
        if not self.project.thumbs:
            p.fillRect(band, QColor(40, 40, 46))
            p.setPen(QColor(90, 90, 100))
            p.drawText(band, Qt.AlignCenter, tr("썸네일 생성 중…"))
            return
        tile_w = int(THUMB_H * 16 / 9)
        n_tiles = max(1, int(band.width() // tile_w) + 1)
        for i in range(n_tiles):
            x = i * tile_w
            pix = self._thumb_for(self.x_to_t(x + tile_w / 2))
            if pix is None:
                continue
            p.drawPixmap(QRectF(x, 0, tile_w, THUMB_H).toRect(), pix)

    def _draw_waveform(self, p: QPainter, band: QRectF):
        wave = self.project.waveform
        if wave is None or len(wave) == 0:
            return
        w = int(band.width())
        n = len(wave)
        bottom = band.bottom()
        poly = QPolygonF()
        poly.append(QPointF(0, bottom))
        dur = self.duration
        for x in range(w):
            t0 = self.x_to_t(x)
            t1 = self.x_to_t(x + 1)
            i0 = min(n - 1, int(t0 / dur * n))
            i1 = min(n, max(i0 + 1, int(t1 / dur * n)))
            amp = max(wave[i0:i1]) * THUMB_H * 0.85
            poly.append(QPointF(x, bottom - amp))
        poly.append(QPointF(w, bottom))
        p.setPen(Qt.NoPen)
        grad = QLinearGradient(0, band.top(), 0, bottom)
        grad.setColorAt(0, QColor(0, 230, 200, 150))
        grad.setColorAt(1, QColor(0, 160, 140, 90))
        p.setBrush(QBrush(grad))
        p.drawPolygon(poly)

    def _chat_buckets(self) -> tuple[list, float]:
        """project.chat (app.chat.ChatData) 의 (buckets, bucket_sec). 없으면 ([], 0)."""
        chat = getattr(self.project, "chat", None)
        buckets = getattr(chat, "buckets", None) or []
        try:
            bsec = float(getattr(chat, "bucket_sec", 0) or 0)
        except (TypeError, ValueError):
            bsec = 0.0
        return (list(buckets), bsec) if buckets and bsec > 0 else ([], 0.0)

    def _draw_chat(self, p: QPainter, band: QRectF):
        """채팅 반응 그래프: 썸네일 띠 아래쪽 절반에 주황색 계단형 면 그래프 (가장 바쁜 버킷 = 최대 높이)."""
        buckets, bsec = self._chat_buckets()
        if not buckets:
            return
        top = max(buckets)
        if top <= 0:
            return
        w = int(band.width())
        n = len(buckets)
        bottom = band.bottom()
        max_h = THUMB_H * 0.5
        poly = QPolygonF()
        poly.append(QPointF(0, bottom))
        edge: list[QPointF] = []
        for x in range(w):
            t0 = self.x_to_t(x)
            t1 = self.x_to_t(x + 1)
            i0 = min(n - 1, max(0, int(t0 // bsec)))
            i1 = min(n, max(i0 + 1, int(math.ceil(t1 / bsec))))
            amp = max(buckets[i0:i1]) / top * max_h
            pt = QPointF(x, bottom - amp)
            poly.append(pt)
            edge.append(pt)
        poly.append(QPointF(w, bottom))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 167, 38, 130))
        p.drawPolygon(poly)
        p.setPen(QPen(QColor(255, 167, 38, 220), 1))
        p.setBrush(Qt.NoBrush)
        p.drawPolyline(QPolygonF(edge))
        # 범례
        font = QFont()
        font.setPointSize(7)
        font.setBold(True)
        p.setFont(font)
        r = QRectF(4, bottom - max_h - 13, 40, 12)
        p.setPen(QColor(0, 0, 0, 170))
        p.drawText(r.translated(1, 1), Qt.AlignLeft | Qt.AlignVCenter, tr("채팅"))
        p.setPen(QColor(255, 190, 90, 235))
        p.drawText(r, Qt.AlignLeft | Qt.AlignVCenter, tr("채팅"))
        p.setPen(Qt.NoPen)

    def _draw_segments(self, p: QPainter, band: QRectF):
        segs = self.project.segments
        p.setPen(Qt.NoPen)
        font = QFont()
        font.setPointSize(8)
        font.setBold(True)
        p.setFont(font)
        for i, s in enumerate(segs):
            x0, x1 = self.t_to_x(s.start), self.t_to_x(s.end)
            if x1 < 0 or x0 > band.width():
                continue
            r = QRectF(x0, 0, max(x1 - x0, 1), THUMB_H)
            if s.enabled:
                c = seg_color(i)
                c.setAlpha(50)
            else:
                c = QColor(0, 0, 0, 160)
            p.fillRect(r, c)
            # 아래쪽 색 띠
            bar = seg_color(i) if s.enabled else QColor(90, 90, 96)
            p.fillRect(QRectF(r.left(), THUMB_H - 4, r.width(), 4), bar)
            if i == self.loop_segment:
                p.setPen(QPen(QColor(255, 235, 59), 2))
                p.setBrush(Qt.NoBrush)
                p.drawRect(r.adjusted(1, 1, -1, -1))
                p.setPen(Qt.NoPen)
            if r.width() > 26:
                label = f"{i + 1}" if s.enabled else f"{i + 1} ✕"
                lx = max(r.left(), 0) + 4
                p.setPen(QColor(0, 0, 0, 160))
                p.drawText(QRectF(lx + 1, 3, 60, 14), Qt.AlignLeft | Qt.AlignTop, label)
                p.setPen(QColor(255, 255, 255, 235 if s.enabled else 130))
                p.drawText(QRectF(lx, 2, 60, 14), Qt.AlignLeft | Qt.AlignTop, label)
                p.setPen(Qt.NoPen)

    def _draw_ruler(self, p: QPainter, r: QRectF):
        p.fillRect(r, QColor(32, 32, 38))
        w = r.width()
        px_per_sec = w / max(self.view_len, 1e-6)
        step = 3600
        for cand in (0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600):
            if cand * px_per_sec >= 70:
                step = cand
                break
        font = QFont()
        font.setPointSize(7)
        p.setFont(font)
        p.setPen(QColor(150, 150, 160))
        t = (self.view_start // step) * step
        end = self.view_start + self.view_len
        ms = step < 1
        while t <= end:
            x = self.t_to_x(t)
            if x >= 0:
                p.drawLine(int(x), int(r.top()), int(x), int(r.top() + 5))
                p.drawText(int(x) + 3, int(r.top() + 14), fmt_time(t, ms=True)[:-2] if ms else fmt_time(t, ms=False))
            t += step

    def _draw_keyframes(self, p: QPainter, h: int):
        kfs = self.project.keyframes
        if not kfs:
            return
        # 너무 촘촘하면 생략
        if len(kfs) / max(self.duration, 1) * self.view_len > self.width() / 3:
            return
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 140))
        y = THUMB_H + RULER_H + 2
        for k in kfs:
            if k < self.view_start or k > self.view_start + self.view_len:
                continue
            x = int(self.t_to_x(k))
            p.drawRect(x - 1, y, 2, 4)

    def _draw_markers(self, p: QPainter, h: int):
        for i, m in enumerate(self.project.markers):
            if m < self.view_start or m > self.view_start + self.view_len:
                continue
            x = int(self.t_to_x(m))
            col = QColor(255, 82, 82) if i != self.drag_marker else QColor(255, 200, 80)
            p.setPen(QPen(col, 2))
            p.drawLine(x, 0, x, h)
            tri = QPolygonF([QPointF(x - 6, 0), QPointF(x + 6, 0), QPointF(x, 8)])
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(col))
            p.drawPolygon(tri)

    def _draw_pending_in(self, p: QPainter, h: int):
        t = self.project.pending_in
        if t is None or t < self.view_start or t > self.view_start + self.view_len:
            return
        x = int(self.t_to_x(t))
        pen = QPen(QColor(102, 187, 106), 2, Qt.DashLine)
        p.setPen(pen)
        p.drawLine(x, 0, x, h)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(102, 187, 106))
        p.drawRect(x, 0, 14, 14)
        p.setPen(QColor(0, 0, 0))
        font = QFont()
        font.setPointSize(8)
        font.setBold(True)
        p.setFont(font)
        p.drawText(QRectF(x, 0, 14, 14), Qt.AlignCenter, "I")

    def _draw_playhead(self, p: QPainter, h: int):
        x = int(self.t_to_x(self.position))
        if x < -2 or x > self.width() + 2:
            return
        p.setPen(QPen(QColor(255, 255, 255), 2))
        p.drawLine(x, 0, x, h)
        tri = QPolygonF([QPointF(x - 6, h), QPointF(x + 6, h), QPointF(x, h - 8)])
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(255, 255, 255)))
        p.drawPolygon(tri)

    # ---- 마우스 ----
    def _marker_near(self, x: float) -> int:
        if not self.project:
            return -1
        return self.project.nearest_marker(self.x_to_t(x), self.px_tol_sec(MARKER_TOL_PX))

    def _show_popup(self, x: float):
        t = self.x_to_t(x)
        pix = self._thumb_for(t) if self.project else None
        gp = self.mapToGlobal(QPoint(int(x), 0))
        text = fmt_time(t)
        buckets, bsec = self._chat_buckets()
        if buckets:
            i = int(t // bsec)
            if 0 <= i < len(buckets):
                text += tr("  💬 {0}").format(buckets[i])
        self.popup.show_at(gp, pix, text)

    def mousePressEvent(self, e):
        if not self.project or self.duration <= 0:
            return
        x = e.position().x()
        if e.button() == Qt.LeftButton:
            if e.modifiers() & Qt.ControlModifier:
                idx = self.project.segment_at(self.x_to_t(x))
                if idx >= 0:
                    self.segmentToggled.emit(idx)
                return
            mi = self._marker_near(x)
            if mi >= 0:
                self.drag_marker = mi
                self.markerDragStarted.emit()
                self.setCursor(Qt.SizeHorCursor)
            else:
                self.scrubbing = True
                self.seekRequested.emit(self.x_to_t(x), False)
            self._show_popup(x)
            self.update()
        elif e.button() == Qt.RightButton:
            mi = self._marker_near(x)
            if mi >= 0:
                self.markerDeleted.emit(mi)
            else:
                self.addMarkerRequested.emit(self.x_to_t(x))

    def mouseMoveEvent(self, e):
        x = e.position().x()
        self.hover_x = int(x)
        if self.drag_marker >= 0:
            self.markerMoved.emit(self.drag_marker, self.x_to_t(x), False)
            self.seekRequested.emit(self.project.markers[self.drag_marker], False)
            self._show_popup(self.t_to_x(self.project.markers[self.drag_marker]))
        elif self.scrubbing:
            self.seekRequested.emit(self.x_to_t(x), False)
            self._show_popup(x)
        elif self.project and self.duration > 0:
            near = self._marker_near(x) >= 0
            self.setCursor(Qt.SizeHorCursor if near else Qt.PointingHandCursor)
            self._show_popup(x)
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        x = e.position().x()
        if self.drag_marker >= 0:
            self.markerMoved.emit(self.drag_marker, self.x_to_t(x), True)
            self.seekRequested.emit(self.project.markers[self.drag_marker], True)
            self.drag_marker = -1
            self.setCursor(Qt.PointingHandCursor)
        elif self.scrubbing:
            self.scrubbing = False
            self.seekRequested.emit(self.x_to_t(x), True)
        self.update()

    def mouseDoubleClickEvent(self, e):
        if not self.project or e.button() != Qt.LeftButton:
            return
        idx = self.project.segment_at(self.x_to_t(e.position().x()))
        if idx >= 0:
            self.segmentLoopRequested.emit(idx)

    def wheelEvent(self, e):
        if not self.project or self.duration <= 0:
            return
        dy = e.angleDelta().y()
        if e.modifiers() & Qt.ControlModifier:
            self.zoom(1.25 if dy > 0 else 1 / 1.25, self.x_to_t(e.position().x()))
        else:
            self.scroll_to(self.view_start - (dy / 120.0) * self.view_len * 0.15)
        e.accept()

    def leaveEvent(self, _e):
        self.hover_x = -1
        self.popup.hide()
        self.update()

    def hideEvent(self, e):
        self.popup.hide()
        super().hideEvent(e)


class TimelineWidget(QWidget):
    """캔버스 + 가로 스크롤바. 바깥에서는 canvas 의 신호를 그대로 쓴다."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.canvas = TimelineCanvas(self)
        self.scroll = QScrollBar(Qt.Horizontal, self)
        self.scroll.setRange(0, 0)
        self.scroll.setFixedHeight(12)
        self.scroll.hide()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.canvas)
        lay.addWidget(self.scroll)
        self._syncing = False
        self.canvas.viewChanged.connect(self._sync_scroll)
        self.scroll.valueChanged.connect(self._on_scroll)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    # 편의 위임
    def __getattr__(self, name):
        return getattr(self.canvas, name)

    def _sync_scroll(self):
        c = self.canvas
        if self._syncing:
            return
        self._syncing = True
        try:
            if c.duration <= 0 or c.view_len >= c.duration - 1e-6:
                self.scroll.hide()
                self.scroll.setRange(0, 0)
            else:
                self.scroll.show()
                total = int(c.duration * 1000)
                page = int(c.view_len * 1000)
                self.scroll.setRange(0, max(0, total - page))
                self.scroll.setPageStep(page)
                self.scroll.setSingleStep(max(1, page // 10))
                self.scroll.setValue(int(c.view_start * 1000))
        finally:
            self._syncing = False

    def _on_scroll(self, v: int):
        if self._syncing:
            return
        self._syncing = True
        try:
            self.canvas.scroll_to(v / 1000.0)
        finally:
            self._syncing = False
