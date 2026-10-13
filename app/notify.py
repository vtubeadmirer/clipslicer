"""트레이 아이콘 + 풍선 알림. 메인 창이 뒤에 있을 때 내보내기 · 업로드 · 다운로드 완료를 알려 준다."""
from __future__ import annotations

from .i18n import tr
import logging

from PySide6.QtCore import QObject
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QSystemTrayIcon, QMenu, QStyle, QApplication

LOG = logging.getLogger("clipslicer")


class Notifier(QObject):
    """QSystemTrayIcon 래퍼. 트레이를 못 쓰는 환경이면 조용히 아무것도 안 한다."""

    def __init__(self, window, icon: QIcon | None = None):
        super().__init__(window)
        self.window = window
        self.tray: QSystemTrayIcon | None = None
        self._menu: QMenu | None = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            LOG.info("시스템 트레이 없음 — 알림 끔")
            return
        if icon is None or icon.isNull():
            icon = window.style().standardIcon(QStyle.SP_MediaPlay)
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip("ClipSlicer")
        self._menu = QMenu(window)
        a = self._menu.addAction(tr("창 보이기"))
        a.triggered.connect(self.show_window)
        self._menu.addSeparator()
        a = self._menu.addAction(tr("종료"))
        a.triggered.connect(self.quit)
        self.tray.setContextMenu(self._menu)
        self.tray.activated.connect(self._on_activated)
        self.tray.messageClicked.connect(self.show_window)
        self.tray.show()

    @property
    def available(self) -> bool:
        return self.tray is not None

    def notify(self, title: str, text: str, force: bool = False, msecs: int = 6000) -> bool:
        """사용자가 이 앱을 보고 있지 않을 때만 풍선을 띄운다 (force=True 면 항상). 띄웠으면 True.

        메인 창뿐 아니라 모달 대화상자(업로드 · 다운로드)가 활성이어도 '보고 있는 중'으로 본다.
        """
        if self.tray is None or not self.tray.isVisible():
            return False
        if not force and not self.window.isMinimized() and QApplication.activeWindow() is not None:
            return False
        self.tray.showMessage(title, text, QSystemTrayIcon.Information, msecs)
        return True

    def show_window(self):
        w = self.window
        if w.isMinimized() or not w.isVisible():
            w.showNormal()
        else:
            w.show()
        w.raise_()
        w.activateWindow()

    def quit(self):
        self.window.close()

    def hide(self):
        if self.tray is not None:
            self.tray.hide()

    def _on_activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.show_window()
