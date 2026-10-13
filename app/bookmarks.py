"""방송 중 북마크: 전역 단축키(Windows RegisterHotKey)로 어느 프로그램에서든 '지금' 시각을 기록해 두고,
녹화가 끝난 뒤 그 파일을 열면 파일 수정 시각(= 녹화 끝)을 기준으로 영상 시각으로 바꿔 마커로 가져온다.

기록 파일: <설정 폴더>/bookmarks.jsonl — 한 줄에 {"ts": epoch 초, "note": 메모} 하나.
"""
from __future__ import annotations

from .i18n import tr
import ctypes
import json
import logging
import os
import sys
import time
from datetime import datetime
from typing import Callable

from PySide6.QtCore import Qt, QAbstractNativeEventFilter, QCoreApplication, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton, QListWidget, QApplication,
)

LOG = logging.getLogger("clipslicer")

WM_HOTKEY = 0x0312
HOTKEY_ID = 0xC1B5                      # 이 앱이 쓰는 단축키 id (임의 값)
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_NOREPEAT = 0x0001, 0x0002, 0x0004, 0x4000
ERROR_HOTKEY_ALREADY_REGISTERED = 1409
VK_F9, VK_F10 = 0x78, 0x79

# (표시 이름, modifiers, 가상 키 코드)
HOTKEYS: list[tuple[str, int, int]] = [
    ("Ctrl+Alt+B", MOD_CONTROL | MOD_ALT, ord("B")),
    ("Ctrl+Alt+M", MOD_CONTROL | MOD_ALT, ord("M")),
    ("Ctrl+Shift+B", MOD_CONTROL | MOD_SHIFT, ord("B")),
    ("F9", 0, VK_F9),
    ("F10", 0, VK_F10),
]
DEFAULT_HOTKEY = "Ctrl+Alt+B"
HOTKEY_NAMES = [h[0] for h in HOTKEYS]
SETTINGS_KEY = "bookmark_hotkey"        # QSettings 에 저장하는 단축키 이름
MAX_LIST = 200                          # 창에 보여 주는 최근 북마크 수


# --------------------------------------------------------------------------- 저장소
def store_path() -> str:
    """bookmarks.jsonl 경로. 테스트에서는 이 함수를 monkeypatch 한다."""
    from .youtube import config_dir
    return os.path.join(config_dir(), "bookmarks.jsonl")


def add_bookmark(note: str = "", ts: float | None = None) -> float:
    """북마크 한 줄 추가. 기록한 epoch 초를 돌려준다."""
    ts = time.time() if ts is None else float(ts)
    path = store_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": ts, "note": note or ""}, ensure_ascii=False) + "\n")
    LOG.info("북마크 기록: %s %s", datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S"), note or "")
    return ts


def load_bookmarks() -> list[dict]:
    """[{"ts": float, "note": str}, ...] 시각 순. 깨진 줄은 건너뛴다."""
    try:
        with open(store_path(), "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return []
    out: list[dict] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
            out.append({"ts": float(d["ts"]), "note": str(d.get("note", "") or "")})
        except (ValueError, KeyError, TypeError):
            continue
    out.sort(key=lambda d: d["ts"])
    return out


def clear_bookmarks():
    try:
        os.remove(store_path())
    except OSError:
        pass


def bookmarks_for_file(path: str, duration: float) -> list[tuple[float, str]]:
    """녹화 파일에 해당하는 북마크를 (영상 시각, 메모) 목록으로.

    파일 수정 시각(mtime)을 녹화 '끝'으로 보고 start = mtime - duration 으로 계산한다.
    """
    try:
        end = os.path.getmtime(path)
    except OSError:
        return []
    if duration <= 0:
        return []
    start = end - duration
    out = []
    for b in load_bookmarks():
        t = b["ts"] - start
        if 0.0 <= t <= duration:
            out.append((round(t, 3), b["note"]))
    return out


def apply_to_project(proj, min_gap: float = 0.05) -> int:
    """현재 영상에 해당하는 북마크를 마커로 넣는다 (실행 취소 1단계). 추가한 마커 수를 돌려준다."""
    hits = bookmarks_for_file(proj.path, proj.duration)
    times = [t for t, _ in hits
             if min_gap < t < proj.duration - min_gap and not any(abs(m - t) < min_gap for m in proj.markers)]
    if not times:
        return 0
    proj.push_undo()
    return proj.add_markers(times)


def fmt_bookmark_time(ts: float) -> str:
    """오늘이면 'HH:MM:SS', 아니면 'MM-DD HH:MM:SS'."""
    dt = datetime.fromtimestamp(ts)
    if dt.date() == datetime.now().date():
        return dt.strftime("%H:%M:%S")
    return dt.strftime("%m-%d %H:%M:%S")


# --------------------------------------------------------------------------- 전역 단축키
class _HotkeyFilter(QAbstractNativeEventFilter):
    """WM_HOTKEY 를 잡아 콜백을 부른다 (GUI 스레드)."""

    def __init__(self, callback: Callable[[], None]):
        super().__init__()
        self.callback = callback

    def nativeEventFilter(self, event_type, message):
        try:
            et = bytes(event_type)
        except TypeError:
            et = b""
        if et in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            import ctypes.wintypes
            msg = ctypes.wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and int(msg.wParam) == HOTKEY_ID:
                try:
                    self.callback()
                except Exception:
                    LOG.exception("북마크 단축키 처리 실패")
                return True, 0
        return False, 0


class GlobalHotkey:
    """Windows 전역 단축키 하나를 등록/해제. 다른 프로그램이 앞에 있어도 눌리면 callback 이 불린다."""

    def __init__(self, callback: Callable[[], None]):
        self.callback = callback
        self.name = ""
        self._filter: _HotkeyFilter | None = None
        self._registered = False

    @staticmethod
    def available() -> bool:
        return sys.platform == "win32"

    @property
    def registered(self) -> bool:
        return self._registered

    def register(self, name: str) -> tuple[bool, str]:
        """(성공 여부, 실패 이유). 이미 등록돼 있으면 먼저 푼다."""
        self.unregister()
        if not self.available():
            return False, tr("전역 단축키는 Windows 에서만 동작합니다")
        spec = next((h for h in HOTKEYS if h[0] == name), None)
        if spec is None:
            return False, tr("알 수 없는 단축키: {0}").format(name)
        _, mods, vk = spec
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.RegisterHotKey.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_uint, ctypes.c_uint]
        user32.RegisterHotKey.restype = ctypes.c_int
        if not user32.RegisterHotKey(None, HOTKEY_ID, mods | MOD_NOREPEAT, vk):
            err = ctypes.get_last_error()
            LOG.warning("RegisterHotKey 실패 %s (오류 %d)", name, err)
            if err == ERROR_HOTKEY_ALREADY_REGISTERED:
                return False, tr("{0} 은(는) 다른 프로그램이 이미 쓰고 있습니다. 다른 단축키를 고르세요.").format(name)
            return False, tr("단축키 등록 실패 ({0}, 오류 {1})").format(name, err)
        app = QCoreApplication.instance()
        if app is not None:
            self._filter = _HotkeyFilter(self.callback)
            app.installNativeEventFilter(self._filter)
        self.name = name
        self._registered = True
        LOG.info("전역 단축키 등록: %s", name)
        return True, ""

    def unregister(self):
        if not self._registered:
            return
        try:
            ctypes.WinDLL("user32").UnregisterHotKey(None, HOTKEY_ID)
        except (OSError, AttributeError):
            pass
        app = QCoreApplication.instance()
        if app is not None and self._filter is not None:
            app.removeNativeEventFilter(self._filter)
        self._filter = None
        self._registered = False
        LOG.info("전역 단축키 해제: %s", self.name)


# --------------------------------------------------------------------------- 창
class BookmarkWindow(QDialog):
    """항상 위에 떠 있는 작은 창: 단축키 선택 · 지금 북마크 · 최근 기록 목록.

    show() 로 띄우면 단축키를 등록하고, 닫으면 푼다 (모달 아님 — 메인 창은 그대로 쓸 수 있다).
    """
    bookmarked = Signal(float)   # 기록한 epoch 초

    def __init__(self, parent=None, settings=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle(tr("방송 북마크 모드"))
        self.setWindowFlags(Qt.Tool | Qt.WindowStaysOnTopHint | Qt.CustomizeWindowHint
                            | Qt.WindowTitleHint | Qt.WindowCloseButtonHint)
        self.setMinimumWidth(360)
        self.hotkey = GlobalHotkey(self.bookmark_now)

        lay = QVBoxLayout(self)
        intro = QLabel(tr("방송·녹화 중에 남기고 싶은 순간이 나오면 단축키를 누르세요. 다른 프로그램이 앞에 있어도 됩니다.\n"
                          "녹화가 끝나면 그 파일을 열고 편집 ▸ 북마크 가져오기 로 마커를 넣습니다."))
        intro.setWordWrap(True)
        intro.setObjectName("hint")
        lay.addWidget(intro)

        row = QHBoxLayout()
        row.addWidget(QLabel(tr("단축키")))
        self.cb_hotkey = QComboBox()
        self.cb_hotkey.addItems(HOTKEY_NAMES)
        cur = str(settings.value(SETTINGS_KEY, DEFAULT_HOTKEY)) if settings is not None else DEFAULT_HOTKEY
        self.cb_hotkey.setCurrentIndex(max(0, HOTKEY_NAMES.index(cur) if cur in HOTKEY_NAMES else 0))
        self.cb_hotkey.currentTextChanged.connect(self._on_hotkey_changed)
        row.addWidget(self.cb_hotkey, 1)
        self.b_now = QPushButton(tr("● 지금 북마크"))
        self.b_now.setObjectName("cutBtn")
        self.b_now.setToolTip(tr("현재 시각을 북마크로 기록 (단축키와 같음)"))
        self.b_now.clicked.connect(self.bookmark_now)
        row.addWidget(self.b_now)
        lay.addLayout(row)

        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        lay.addWidget(self.lbl_status)

        self.list = QListWidget()
        self.list.setToolTip(tr("최근 북마크 (기록 시각 · 메모)"))
        lay.addWidget(self.list, 1)

        btns = QHBoxLayout()
        self.b_clear = QPushButton(tr("기록 지우기"))
        self.b_clear.setToolTip(tr("북마크 기록 파일을 비웁니다"))
        self.b_clear.clicked.connect(self._clear)
        btns.addWidget(self.b_clear)
        btns.addStretch(1)
        b_close = QPushButton(tr("닫기"))
        b_close.clicked.connect(self.close)
        btns.addWidget(b_close)
        lay.addLayout(btns)
        self.refresh()

    # ---- 단축키 ----
    @property
    def hotkey_name(self) -> str:
        return self.cb_hotkey.currentText()

    def _register(self):
        ok, why = self.hotkey.register(self.hotkey_name)
        if ok:
            self._set_status(tr("단축키 {0} 사용 중 — 어느 프로그램에서든 누르면 기록됩니다").format(self.hotkey_name), "#81c784")
        elif not GlobalHotkey.available():
            self._set_status(why + " " + tr("(이 창의 '지금 북마크' 버튼은 쓸 수 있습니다)"), "#ffb74d")
        else:
            self._set_status(why, "#ef5350")

    def _on_hotkey_changed(self, name: str):
        if self.settings is not None:
            self.settings.setValue(SETTINGS_KEY, name)
        if self.isVisible():
            self._register()

    def _set_status(self, text: str, color: str = "#9aa0a6"):
        self.lbl_status.setText(text)
        self.lbl_status.setStyleSheet(f"color: {color};")

    def showEvent(self, e):
        super().showEvent(e)
        if not e.spontaneous() and not self.hotkey.registered:
            self._register()

    def closeEvent(self, e):
        self.hotkey.unregister()
        super().closeEvent(e)

    def reject(self):
        self.hotkey.unregister()
        super().reject()

    # ---- 북마크 ----
    def bookmark_now(self, note: str = "") -> float:
        ts = add_bookmark(note if isinstance(note, str) else "")
        QApplication.beep()
        self.refresh()
        self._set_status(tr("북마크 저장: {0}  (총 {1}개)").format(fmt_bookmark_time(ts), self.list.count()), "#7cc4ff")
        self.bookmarked.emit(ts)
        return ts

    def refresh(self):
        items = load_bookmarks()[-MAX_LIST:]
        self.list.clear()
        for b in reversed(items):
            text = fmt_bookmark_time(b["ts"])
            if b["note"]:
                text += "  " + b["note"]
            self.list.addItem(text)
        self.b_clear.setEnabled(bool(items))

    def _clear(self):
        clear_bookmarks()
        self.refresh()
        self._set_status(tr("북마크 기록을 지웠습니다"))
