"""libmpv 를 Qt 위젯에 임베드한 플레이어."""
from __future__ import annotations

import locale

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPalette, QColor
from PySide6.QtWidgets import QWidget

from .paths import prepare_libmpv

prepare_libmpv()
locale.setlocale(locale.LC_NUMERIC, "C")  # libmpv 요구 사항

import mpv  # noqa: E402  (DLL 경로 준비 후 import)


class MpvWidget(QWidget):
    positionChanged = Signal(float)
    durationChanged = Signal(float)
    pauseChanged = Signal(bool)
    fileLoaded = Signal()
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_DontCreateNativeAncestors)
        self.setAttribute(Qt.WA_NativeWindow)
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(QPalette.Window, QColor(0, 0, 0))
        self.setPalette(pal)
        self.setMinimumSize(320, 180)
        self.setFocusPolicy(Qt.NoFocus)

        self.mpv = mpv.MPV(
            wid=str(int(self.winId())),
            vo="gpu",
            hwdec="auto-safe",
            keep_open="yes",
            osc="no",
            input_default_bindings="no",
            input_vo_keyboard="no",
            input_cursor="no",
            hr_seek="yes",
            hr_seek_framedrop="no",
            pause="yes",
            volume=100,
        )
        try:
            self.mpv["drag-and-drop"] = "no"
        except Exception:
            pass
        self.duration = 0.0
        self.position = 0.0
        self.loaded = False

        @self.mpv.property_observer("time-pos")
        def _on_pos(_name, value):
            if value is not None:
                self.position = float(value)
                self.positionChanged.emit(self.position)

        @self.mpv.property_observer("duration")
        def _on_dur(_name, value):
            if value is not None:
                self.duration = float(value)
                self.durationChanged.emit(self.duration)

        @self.mpv.property_observer("pause")
        def _on_pause(_name, value):
            if value is not None:
                self.pauseChanged.emit(bool(value))

        @self.mpv.event_callback("file-loaded")
        def _on_loaded(_event):
            self.loaded = True
            self.fileLoaded.emit()

    # ---- 제어 ----
    def load(self, path: str):
        self.loaded = False
        self.mpv.pause = True
        self.mpv.play(path)

    def unload(self):
        try:
            self.mpv.command("stop")
        except Exception:
            pass
        self.loaded = False

    @property
    def paused(self) -> bool:
        return bool(self.mpv.pause)

    def toggle_pause(self):
        if not self.loaded:
            return
        # 영상 끝에서 재생 누르면 처음부터
        if self.mpv.pause and self.duration and self.position >= self.duration - 0.05:
            self.seek(0)
        self.mpv.pause = not self.mpv.pause

    def pause(self):
        self.mpv.pause = True

    def seek(self, t: float, exact: bool = True):
        if not self.loaded:
            return
        t = max(0.0, min(t, self.duration))
        try:
            self.mpv.seek(t, "absolute", "exact" if exact else "keyframes")
        except Exception:
            pass

    def seek_relative(self, dt: float):
        self.seek(self.position + dt)

    def frame_step(self, forward: bool = True):
        if not self.loaded:
            return
        try:
            if forward:
                self.mpv.frame_step()
            else:
                self.mpv.frame_back_step()
        except Exception:
            pass

    def set_loop(self, a: float | None, b: float | None):
        self.mpv["ab-loop-a"] = "no" if a is None else a
        self.mpv["ab-loop-b"] = "no" if b is None else b

    def set_speed(self, speed: float):
        self.mpv.speed = speed

    def set_volume(self, vol: int):
        self.mpv.volume = vol

    # ---- 이벤트 ----
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def shutdown(self):
        try:
            self.mpv.terminate()
        except Exception:
            pass
