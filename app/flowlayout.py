"""폭이 모자라면 다음 줄로 넘기는 레이아웃 (버튼 · 체크박스 줄이 창을 줄였을 때 잘리지 않게).

Qt 예제의 FlowLayout 을 옮긴 것. heightForWidth 를 지원해 스크롤 영역 안에서도 높이가 맞게 늘어난다.
"""
from __future__ import annotations

from PySide6.QtCore import QMargins, QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QSizePolicy


class FlowLayout(QLayout):
    def __init__(self, parent=None, hspacing: int = 6, vspacing: int = 4):
        super().__init__(parent)
        self._items = []
        self._h, self._v = hspacing, vspacing
        self.setContentsMargins(QMargins(0, 0, 0, 0))

    def __del__(self):
        while self.count():
            self.takeAt(0)

    def addItem(self, item):
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect):
        super().setGeometry(rect)
        self._do_layout(rect, apply=True)

    def sizeHint(self) -> QSize:
        # 한 줄로 늘어놓았을 때 크기 (넓으면 한 줄, 좁으면 heightForWidth 로 줄바꿈)
        w = h = 0
        for it in self._items:
            if it.widget() is not None and not it.widget().isVisible():
                continue
            s = it.sizeHint()
            w += s.width() + (self._h if w else 0)
            h = max(h, s.height())
        m = self.contentsMargins()
        return QSize(w + m.left() + m.right(), h + m.top() + m.bottom())

    def minimumSize(self) -> QSize:
        size = QSize()
        for it in self._items:
            size = size.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do_layout(self, rect: QRect, apply: bool) -> int:
        m = self.contentsMargins()
        r = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line_h = r.x(), r.y(), 0
        for it in self._items:
            wdg = it.widget()
            if wdg is not None and not wdg.isVisibleTo(wdg.parentWidget() or wdg):
                continue
            hint = it.sizeHint()
            if wdg is not None and wdg.sizePolicy().horizontalPolicy() == QSizePolicy.Ignored:
                hint = it.minimumSize()
            w = min(hint.width(), r.width())   # 한 줄보다 넓은 것은 줄 폭에 맞춘다
            if x > r.x() and x + w > r.right() + 1:
                x, y, line_h = r.x(), y + line_h + self._v, 0
            if apply:
                it.setGeometry(QRect(QPoint(x, y), QSize(w, hint.height())))
            x += w + self._h
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y() + m.bottom()
