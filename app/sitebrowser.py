"""사이트에서 녹화: ClipSlicer 안의 작은 브라우저로 방송 페이지를 열고, 재생이 시작되면 m3u8 주소와
로그인 쿠키를 자동으로 잡아 버튼 한 번으로 녹화한다.

- 로그인은 이 창 안에서 한 번만 하면 된다 (프로필은 설정 폴더 web_profile 에 저장).
- 쿠키는 외부 브라우저에서 읽지 않으므로 크롬 쿠키 암호화 문제가 없다.
- 녹화 자체는 workers.DownloadWorker 의 m3u8 경로(live_record)를 그대로 쓴다.
- DRM 스트림은 live_record 가 거부한다.
"""
from __future__ import annotations

import logging
import os
import time
import urllib.parse

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QToolButton, QVBoxLayout)
from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage, QWebEngineUrlRequestInterceptor
from PySide6.QtWebEngineWidgets import QWebEngineView

from .i18n import tr

LOG = logging.getLogger("clipslicer")


def profile_dir() -> str:
    from .youtube import config_dir
    d = os.path.join(config_dir(), "web_profile")
    os.makedirs(d, exist_ok=True)
    return d


_PROFILE = None


def shared_profile() -> QWebEngineProfile:
    """앱 전체에서 하나만 쓰는 영구 프로필 (창보다 오래 살아야 페이지 정리 경고가 안 난다)."""
    global _PROFILE
    if _PROFILE is None:
        from PySide6.QtWidgets import QApplication
        _PROFILE = QWebEngineProfile("ClipSlicer", QApplication.instance())
        _PROFILE.setPersistentStoragePath(profile_dir())
        _PROFILE.setCachePath(os.path.join(profile_dir(), "cache"))
        _PROFILE.setPersistentCookiesPolicy(QWebEngineProfile.ForcePersistentCookies)
        # 구글 등은 'QtWebEngine' 이 들어간 내장 브라우저의 로그인을 막는다 → 일반 크롬과 같은 식별 문자열
        _PROFILE.setHttpUserAgent(clean_user_agent(_PROFILE.httpUserAgent()))
    return _PROFILE


def clean_user_agent(ua: str) -> str:
    """'... QtWebEngine/6.x Chrome/140 ...' → '... Chrome/140 ...'"""
    import re
    return re.sub(r"\s*QtWebEngine/[\d.]+", "", ua or "").strip()


class PopupPage(QWebEnginePage):
    """window.open() 으로 열리는 로그인 팝업(구글·애플·트위터 등)을 별도 창으로 띄운다.
    같은 프로필을 쓰므로 팝업에서 로그인하면 쿠키가 원래 창에도 그대로 적용된다."""

    def __init__(self, profile, parent_widget):
        super().__init__(profile, parent_widget)
        self._owner = parent_widget
        self.popups = []

    def createWindow(self, _type):
        dlg = QDialog(self._owner.window())
        dlg.setWindowTitle(tr("로그인"))
        dlg.resize(520, 680)
        dlg.setAttribute(Qt.WA_DeleteOnClose)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(0, 0, 0, 0)
        view = QWebEngineView(dlg)
        page = PopupPage(self.profile(), view)
        view.setPage(page)
        page.windowCloseRequested.connect(dlg.close)   # 로그인 끝나고 팝업이 스스로 닫힐 때
        view.titleChanged.connect(lambda t: dlg.setWindowTitle(t or tr("로그인")))
        lay.addWidget(view)
        dlg.finished.connect(lambda *_: self.popups.remove(dlg) if dlg in self.popups else None)
        self.popups.append(dlg)
        dlg.show()
        return page


def write_cookies_txt(cookies: list[dict], path: str) -> str:
    """[{domain, path, secure, expiry, name, value}] → Netscape cookies.txt (yt-dlp/live_record 용)."""
    lines = ["# Netscape HTTP Cookie File", "# ClipSlicer 내장 브라우저에서 저장 (로그인 정보가 들어 있으니 공유 금지)"]
    for c in cookies:
        dom = c["domain"]
        lines.append("\t".join([dom, "TRUE" if dom.startswith(".") else "FALSE", c.get("path") or "/",
                                "TRUE" if c.get("secure") else "FALSE", str(int(c.get("expiry") or 0)),
                                c["name"], c["value"]]))
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    return path


def pick_stream(urls: list[str]) -> str:
    """잡힌 m3u8 중 녹화할 것: master/playlist 이름을 우선, 없으면 처음 잡힌 것."""
    for u in urls:
        name = urllib.parse.urlparse(u).path.rsplit("/", 1)[-1].lower()
        if any(k in name for k in ("master", "playlist", "index", "manifest")):
            return u
    return urls[0] if urls else ""


class _Bus(QObject):
    """인터셉터(네트워크 스레드) → 창(GUI 스레드) 신호 전달."""
    found = Signal(str, str)  # m3u8 url, 페이지 url


class _Sniffer(QWebEngineUrlRequestInterceptor):
    def __init__(self, bus: _Bus):
        super().__init__()
        self.bus = bus

    def interceptRequest(self, info):
        url = info.requestUrl().toString()
        if ".m3u8" in url.lower().split("#")[0]:
            self.bus.found.emit(url, info.firstPartyUrl().toString())


class SiteRecordWindow(QDialog):
    """방송 페이지 열기 → 스트림 자동 감지 → 녹화 시작/중지."""
    fileReady = Signal(str, str)  # 저장된 파일, 페이지 주소

    def __init__(self, parent, settings, start_url: str = ""):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle(tr("사이트에서 녹화"))
        self.resize(1100, 760)
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self.streams: list[str] = []
        self.page_url = ""
        self.cookies: dict[tuple, dict] = {}
        self.worker = None
        self.t0 = 0.0

        # 프로필: 이름 있는 프로필은 쿠키·로그인을 디스크에 유지한다
        self.profile = shared_profile()
        self.bus = _Bus(self)
        self.bus.found.connect(self._on_found)
        self.sniffer = _Sniffer(self.bus)
        self.profile.setUrlRequestInterceptor(self.sniffer)
        store = self.profile.cookieStore()
        store.cookieAdded.connect(self._on_cookie_added)
        store.cookieRemoved.connect(self._on_cookie_removed)
        store.loadAllCookies()

        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.b_back = QToolButton()
        self.b_back.setText("◀")
        self.b_reload = QToolButton()
        self.b_reload.setText("⟳")
        self.ed_url = QLineEdit(start_url or settings.value("site_last_url", "https://rplay.live/") or "https://rplay.live/")
        self.ed_url.returnPressed.connect(self._go)
        b_go = QPushButton(tr("열기"))
        b_go.clicked.connect(self._go)
        top.addWidget(self.b_back)
        top.addWidget(self.b_reload)
        top.addWidget(self.ed_url, 1)
        top.addWidget(b_go)
        lay.addLayout(top)

        self.view = QWebEngineView(self)
        self.view.setPage(PopupPage(self.profile, self.view))
        self.b_back.clicked.connect(self.view.back)
        self.b_reload.clicked.connect(self.view.reload)
        self.view.urlChanged.connect(lambda u: self.ed_url.setText(u.toString()))
        lay.addWidget(self.view, 1)

        hint = QLabel(tr("① 처음이면 이 창에서 로그인하세요 (한 번만 하면 기억됩니다)  ② 방송을 재생하면 아래에 스트림이 잡힙니다  ③ ● 녹화 시작"))
        hint.setStyleSheet("color:#9aa0a6; font-size:11px;")
        lay.addWidget(hint)

        bot = QHBoxLayout()
        self.lbl = QLabel(tr("스트림을 찾는 중… 방송 화면을 재생하세요."))
        bot.addWidget(self.lbl, 1)
        self.cb_stream = QComboBox()
        self.cb_stream.setMinimumWidth(220)
        self.cb_stream.setVisible(False)
        bot.addWidget(self.cb_stream)
        self.cb_mute = QCheckBox(tr("녹화 중 페이지 소리 끄기"))
        self.cb_mute.setChecked(True)
        bot.addWidget(self.cb_mute)
        self.b_rec = QPushButton(tr("● 녹화 시작"))
        self.b_rec.setObjectName("cutBtn")
        self.b_rec.setEnabled(False)
        self.b_rec.clicked.connect(self._toggle)
        bot.addWidget(self.b_rec)
        lay.addLayout(bot)

        self._go()

    # ---- 탐색 ----
    def _go(self):
        u = self.ed_url.text().strip()
        if u and "://" not in u:
            u = "https://" + u
        self.settings.setValue("site_last_url", u)
        if self.worker is None:
            self.streams.clear()
            self.cb_stream.clear()
            self.cb_stream.setVisible(False)
            self.b_rec.setEnabled(False)
            self.lbl.setText(tr("스트림을 찾는 중… 방송 화면을 재생하세요."))
        self.view.load(QUrl(u))

    # ---- 감지 ----
    def _on_found(self, url: str, page: str):
        if url in self.streams:
            return
        LOG.info("스트림 감지: %s (페이지 %s)", url[:120], page[:80])
        self.streams.append(url)
        if page.startswith("http"):
            self.page_url = page
        self.cb_stream.clear()
        for u in self.streams:
            self.cb_stream.addItem(urllib.parse.urlparse(u).path.rsplit("/", 1)[-1][:40] or u[:40], u)
        best = pick_stream(self.streams)
        self.cb_stream.setCurrentIndex(max(0, self.cb_stream.findData(best)))
        self.cb_stream.setVisible(len(self.streams) > 1)
        if self.worker is None:
            self.lbl.setText(tr("스트림을 찾았습니다. ● 녹화 시작을 누르세요."))
            self.b_rec.setEnabled(True)

    def _on_cookie_added(self, c):
        d = {"domain": c.domain(), "path": c.path(), "secure": c.isSecure(), "name": bytes(c.name()).decode("latin-1"),
             "value": bytes(c.value()).decode("latin-1"),
             "expiry": c.expirationDate().toSecsSinceEpoch() if not c.isSessionCookie() else 0}
        self.cookies[(d["domain"], d["path"], d["name"])] = d

    def _on_cookie_removed(self, c):
        self.cookies.pop((c.domain(), c.path(), bytes(c.name()).decode("latin-1")), None)

    # ---- 녹화 ----
    def _toggle(self):
        if self.worker is None:
            self._start()
        else:
            self.worker.stop_recording()
            self.b_rec.setEnabled(False)
            self.lbl.setText(tr("녹화를 멈추고 저장하는 중…"))

    def _start(self):
        from .workers import DownloadWorker
        url = self.cb_stream.currentData() or pick_stream(self.streams)
        if not url:
            return
        out_dir = self.settings.value("dl_dir", "") or os.path.join(
            os.environ.get("USERPROFILE", os.path.expanduser("~")), "Videos", "ClipSlicer")
        os.makedirs(out_dir, exist_ok=True)
        cookie_file = write_cookies_txt(list(self.cookies.values()), os.path.join(profile_dir(), "cookies.txt"))
        p = urllib.parse.urlparse(self.page_url or self.ed_url.text())
        referer = f"{p.scheme}://{p.netloc}/" if p.netloc else ""
        self.worker = DownloadWorker(url, out_dir, "best", None, self, cookie_file, referer)
        self.worker.progress.connect(lambda f, t: self.lbl.setText(t))
        self.worker.liveStarted.connect(self._on_live)
        self.worker.done.connect(self._on_done)
        self.b_rec.setEnabled(False)
        self.lbl.setText(tr("재생 목록 확인 중…"))
        self.worker.start()

    def _on_live(self):
        self.t0 = time.time()
        if self.cb_mute.isChecked():
            self.view.page().setAudioMuted(True)
        self.b_rec.setText(tr("■ 녹화 중지 (저장)"))
        self.b_rec.setEnabled(True)

    def _on_done(self, path: str, err: str):
        self.worker = None
        self.view.page().setAudioMuted(False)
        self.b_rec.setText(tr("● 녹화 시작"))
        self.b_rec.setEnabled(bool(self.streams))
        if path:
            self.lbl.setText(tr("저장했습니다: {0}").format(os.path.basename(path)))
            self.fileReady.emit(path, self.page_url or self.ed_url.text())
        else:
            self.lbl.setText(tr("실패: ") + err)
            if err and err != tr("취소됨"):
                QMessageBox.warning(self, tr("사이트에서 녹화"), err)

    def closeEvent(self, e):
        if self.worker is not None:
            if QMessageBox.question(self, tr("사이트에서 녹화"),
                                    tr("녹화 중입니다. 지금까지 받은 분량을 저장하고 닫을까요?")) != QMessageBox.Yes:
                e.ignore()
                return
            self.worker.stop_recording()
            self.worker.wait(20000)
        self.profile.setUrlRequestInterceptor(None)
        try:
            self.profile.cookieStore().cookieAdded.disconnect(self._on_cookie_added)
            self.profile.cookieStore().cookieRemoved.disconnect(self._on_cookie_removed)
        except (RuntimeError, TypeError):
            pass
        self.view.page().deleteLater()
        super().closeEvent(e)
