"""타임라인 위젯: 썸네일 띠 + 파형 + 구간 블록 + 자르기 마커 + 플레이헤드."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QRectF, QPointF
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QPolygonF, QFont, QCursor
from PySide6.QtWidgets import QWidget, QToolTip

from .segments import ClipProject, fmt_time

THUMB_H = 54
RULER_H = 18
MARKER_TOL_PX = 6

SEG_COLORS = [QColor(66, 165, 245), QColor(102, 187, 106), QColor(255, 167, 38),
              QColor(171, 71, 188), QColor(38, 198, 218), QColor(239, 83, 80)]


class TimelineWidget(QWidget):
    seekRequested = Signal(float, bool)      # (time, final)
    markerMoved = Signal(int, float)
    markerDeleted = Signal(int)
    segmentToggled = Signal(int)
    segmentLoopRequested = Signal(int)
    addMarkerRequested = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project: ClipProject | None = None
        self.position = 0.0
        self.hover_x = -1
        self.drag_marker = -1
        self.scrubbing = False
        self.loop_segment = -1
        self.setMinimumHeight(THUMB_H + RULER_H + 8)
        self.setMaximumHeight(THUMB_H + RULER_H + 8)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)

    # ---- 좌표 변환 ----
    @property
    def duration(self) -> float:
        return self.project.duration if self.project else 0.0

    def x_to_t(self, x: float) -> float:
        if self.duration <= 0 or self.width() <= 0:
            return 0.0
        return max(0.0, min(self.duration, x / self.width() * self.duration))

    def t_to_x(self, t: float) -> float:
        if self.duration <= 0:
            return 0.0
        return t / self.duration * self.width()

    # ---- 외부 API ----
    def set_project(self, project: ClipProject | None):
        self.project = project
        self.position = project.last_position if project else 0.0
        self.loop_segment = -1
        self.update()

    def set_position(self, t: float):
        self.position = t
        self.update()

    def set_loop_segment(self, idx: int):
        self.loop_segment = idx
        self.update()

    # ---- 그리기 ----
    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor(24, 24, 28))

        if not self.project or self.duration <= 0:
            p.setPen(QColor(110, 110, 120))
            p.drawText(self.rect(), Qt.AlignCenter, "영상을 열거나 여기에 끌어다 놓으세요")
            return

        band = QRectF(0, 0, w, THUMB_H)
        self._draw_thumbs(p, band)
        self._draw_waveform(p, band)
        self._draw_segments(p, band)
        self._draw_ruler(p, QRectF(0, THUMB_H, w, RULER_H))
        self._draw_markers(p, h)
        self._draw_playhead(p, h)
        if self.hover_x >= 0 and not self.scrubbing:
            p.setPen(QPen(QColor(255, 255, 255, 90), 1))
            p.drawLine(self.hover_x, 0, self.hover_x, h)

    def _draw_thumbs(self, p: QPainter, band: QRectF):
        thumbs = self.project.thumbs
        if not thumbs:
            p.fillRect(band, QColor(40, 40, 46))
            return
        tile_w = int(THUMB_H * 16 / 9)
        n_tiles = max(1, int(band.width() // tile_w) + 1)
        for i in range(n_tiles):
            x = i * tile_w
            t_center = self.x_to_t(x + tile_w / 2)
            # 가장 가까운 썸네일
            best = min(thumbs, key=lambda th: abs(th[0] - t_center))
            pix = best[1]
            target = QRectF(x, 0, tile_w, THUMB_H)
            p.drawPixmap(target.toRect(), pix)

    def _draw_waveform(self, p: QPainter, band: QRectF):
        wave = self.project.waveform
        if wave is None or len(wave) == 0:
            return
        w = int(band.width())
        n = len(wave)
        poly = QPolygonF()
        bottom = band.bottom()
        poly.append(QPointF(0, bottom))
        for x in range(w):
            i = min(n - 1, int(x / max(w, 1) * n))
            amp = float(wave[i]) * THUMB_H * 0.9
            poly.append(QPointF(x, bottom - amp))
        poly.append(QPointF(w, bottom))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 230, 200, 110))
        p.drawPolygon(poly)

    def _draw_segments(self, p: QPainter, band: QRectF):
        segs = self.project.segments
        p.setPen(Qt.NoPen)
        font = QFont()
        font.setPointSize(8)
        font.setBold(True)
        p.setFont(font)
        for i, s in enumerate(segs):
            x0, x1 = self.t_to_x(s.start), self.t_to_x(s.end)
            r = QRectF(x0, 0, max(x1 - x0, 1), THUMB_H)
            if s.enabled:
                c = QColor(SEG_COLORS[i % len(SEG_COLORS)])
                c.setAlpha(55)
            else:
                c = QColor(0, 0, 0, 150)
            p.fillRect(r, c)
            if i == self.loop_segment:
                p.setPen(QPen(QColor(255, 235, 59), 2))
                p.setBrush(Qt.NoBrush)
                p.drawRect(r.adjusted(1, 1, -1, -1))
                p.setPen(Qt.NoPen)
            if r.width() > 24:
                label = f"{i + 1}" if s.enabled else f"{i + 1} ✕"
                p.setPen(QColor(255, 255, 255, 230 if s.enabled else 120))
                p.drawText(r.adjusted(4, 2, -2, -2), Qt.AlignLeft | Qt.AlignTop, label)
                p.setPen(Qt.NoPen)

    def _draw_ruler(self, p: QPainter, r: QRectF):
        p.fillRect(r, QColor(32, 32, 38))
        dur = self.duration
        w = r.width()
        px_per_sec = w / dur
        step = 1
        for cand in (0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600):
            if cand * px_per_sec >= 70:
                step = cand
                break
        else:
            step = 3600
        font = QFont()
        font.setPointSize(7)
        p.setFont(font)
        p.setPen(QColor(150, 150, 160))
        t = 0.0
        while t <= dur:
            x = self.t_to_x(t)
            p.drawLine(int(x), int(r.top()), int(x), int(r.top() + 5))
            p.drawText(int(x) + 3, int(r.top() + 14), fmt_time(t, ms=False))
            t += step

    def _draw_markers(self, p: QPainter, h: int):
        for i, m in enumerate(self.project.markers):
            x = int(self.t_to_x(m))
            col = QColor(255, 82, 82) if i != self.drag_marker else QColor(255, 200, 80)
            p.setPen(QPen(col, 2))
            p.drawLine(x, 0, x, h)
            tri = QPolygonF([QPointF(x - 5, 0), QPointF(x + 5, 0), QPointF(x, 7)])
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(col))
            p.drawPolygon(tri)

    def _draw_playhead(self, p: QPainter, h: int):
        x = int(self.t_to_x(self.position))
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
        tol = self.x_to_t(MARKER_TOL_PX) - self.x_to_t(0)
        return self.project.nearest_marker(self.x_to_t(x), tol)

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
                self.setCursor(Qt.SizeHorCursor)
            else:
                self.scrubbing = True
                self.seekRequested.emit(self.x_to_t(x), False)
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
            self.markerMoved.emit(self.drag_marker, self.x_to_t(x))
            self.seekRequested.emit(self.project.markers[self.drag_marker], False)
        elif self.scrubbing:
            self.seekRequested.emit(self.x_to_t(x), False)
        else:
            if self.project and self.duration > 0:
                near = self._marker_near(x) >= 0
                self.setCursor(Qt.SizeHorCursor if near else Qt.PointingHandCursor)
                QToolTip.showText(QCursor.pos(), fmt_time(self.x_to_t(x)), self)
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        x = e.position().x()
        if self.drag_marker >= 0:
            self.markerMoved.emit(self.drag_marker, self.x_to_t(x))
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

    def leaveEvent(self, _e):
        self.hover_x = -1
        self.update()
