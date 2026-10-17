"""녹화 · 다운로드 목록 창: 여러 개를 동시에 받는다 (줄마다 DownloadWorker 하나).

브라우저 확장에서 온 요청과 'URL 에서 열기' 의 받기가 모두 여기에 한 줄씩 추가된다.
라이브는 줄마다 '■ 녹화 중지 (저장)' 으로 따로 멈출 수 있고, 끝난 파일은 fileReady 로 편집기에 넘긴다.
"""
from __future__ import annotations

import logging
import os
import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from .i18n import tr

LOG = logging.getLogger("clipslicer")

RUNNING, LIVE, STOPPING, DONE, FAILED, CANCELLED = "running", "live", "stopping", "done", "failed", "cancelled"
ACTIVE = (RUNNING, LIVE, STOPPING)


def _strip(url: str) -> str:
    return url.split("#", 1)[0].split("?", 1)[0].rstrip("/").lower()


def task_key(url: str, page: str = "") -> str:
    """같은 방송인지 비교할 열쇠: 방송 페이지 주소 + 스트림 경로 (쿼리의 토큰은 무시).

    rplay 처럼 모든 방송이 같은 경로(.../track.m3u8)를 쓰고 토큰으로만 구분하는 곳이 있어 경로만으로는
    다른 방송까지 중복으로 막힌다 (0.9.9). 확장이 넘기는 페이지 주소는 방송마다 다르므로 함께 쓴다.
    """
    return _strip(page or url) + "|" + _strip(url)


class DownloadRow(QFrame):
    """한 줄 = 받기 하나. params: url, out_dir, quality, section, cookies, referer, headers, title, page, cookie_file."""
    finished = Signal(object)   # self
    openRequested = Signal(str, str)  # 파일 경로, 원래 페이지 주소

    def __init__(self, params: dict, worker_factory, parent=None):
        super().__init__(parent)
        self.params = params
        self.state = RUNNING
        self.path = ""
        self.error = ""
        self.started = time.time()
        self.setFrameShape(QFrame.StyledPanel)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        top = QHBoxLayout()
        self.lbl_title = QLabel(params.get("title") or params["url"])
        self.lbl_title.setStyleSheet("font-weight:600;")
        self.lbl_title.setToolTip(params["url"])
        self.lbl_title.setMinimumWidth(80)
        top.addWidget(self.lbl_title, 1)
        self.b_stop = QPushButton(tr("■ 녹화 중지 (저장)"))
        self.b_stop.setVisible(False)
        self.b_stop.clicked.connect(self.stop_recording)
        self.b_cancel = QPushButton(tr("취소"))
        self.b_cancel.clicked.connect(self.cancel)
        self.b_open = QPushButton(tr("편집기에서 열기"))
        self.b_open.setVisible(False)
        self.b_open.clicked.connect(lambda: self.openRequested.emit(self.path, self.params.get("page") or self.params["url"]))
        self.b_folder = QPushButton(tr("폴더"))
        self.b_folder.setVisible(False)
        self.b_folder.clicked.connect(self._open_folder)
        for b in (self.b_stop, self.b_cancel, self.b_open, self.b_folder):
            b.setFocusPolicy(Qt.NoFocus)
            top.addWidget(b)
        lay.addLayout(top)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(8)
        lay.addWidget(self.progress)
        self.lbl_status = QLabel(tr("준비 중…"))
        self.lbl_status.setStyleSheet("color:#9aa0a6;")
        self.lbl_status.setWordWrap(True)
        lay.addWidget(self.lbl_status)

        self.worker = worker_factory(params)
        self.worker.progress.connect(self._on_progress)
        self.worker.done.connect(self._on_done)
        self.worker.liveStarted.connect(self._on_live)
        self.worker.start()

    # ---- 상태 ----
    @property
    def active(self) -> bool:
        return self.state in ACTIVE

    @property
    def key(self) -> str:
        return task_key(self.params["url"], self.params.get("page") or "")

    def _on_progress(self, frac: float, text: str):
        if self.state == LIVE:
            self.lbl_status.setText(text)
            return
        if self.state == RUNNING:
            self.progress.setValue(int(frac * 1000))
            self.lbl_status.setText(f"{frac * 100:.0f}%  {text}")

    def _on_live(self):
        self.state = LIVE
        self.progress.setRange(0, 0)   # 길이를 모르므로 움직이는 막대
        self.b_stop.setVisible(True)
        self.b_cancel.setText(tr("취소 (버리기)"))

    def stop_recording(self):
        """라이브: 그때까지 받은 분량을 저장하고 끝낸다."""
        if self.state == LIVE:
            self.state = STOPPING
            self.b_stop.setEnabled(False)
            self.lbl_status.setText(tr("녹화를 멈추고 저장하는 중…"))
            self.worker.stop_recording()

    def cancel(self):
        if self.active:
            self.state = STOPPING
            self.b_stop.setEnabled(False)
            self.b_cancel.setEnabled(False)
            self.lbl_status.setText(tr("취소 중…"))
            self.worker.cancel()

    def _on_done(self, path: str, error: str):
        self.progress.setRange(0, 1000)
        self._cleanup_cookie_file()
        self.b_stop.setVisible(False)
        self.b_cancel.setVisible(False)
        if path:
            self.state, self.path = DONE, path
            self.progress.setValue(1000)
            self.lbl_status.setText(tr("완료: {0}").format(os.path.basename(path)))
            self.b_open.setVisible(True)
            self.b_folder.setVisible(True)
        elif error == tr("취소됨"):
            self.state = CANCELLED
            self.progress.setValue(0)
            self.lbl_status.setText(tr("취소됨"))
        else:
            self.state, self.error = FAILED, error
            self.progress.setValue(0)
            self.lbl_status.setText(tr("실패: ") + error)
            self.lbl_status.setStyleSheet("color:#ef9a9a;")
        LOG.info("받기 끝 [%s] %s → %s %s", self.state, self.params["url"][:100], path, error[:200])
        self.finished.emit(self)

    def _cleanup_cookie_file(self):
        p = self.params.get("cookie_file")
        if p:
            try:
                os.remove(p)   # 로그인 쿠키가 든 임시 파일은 끝나면 바로 지운다
            except OSError:
                pass
            self.params["cookie_file"] = ""

    def _open_folder(self):
        if self.path:
            import subprocess
            subprocess.Popen(["explorer", "/select,", os.path.normpath(self.path)])


class DownloadsWindow(QWidget):
    """동시 녹화 · 다운로드 목록. fileReady(경로, 페이지) 는 끝난 파일마다 한 번."""
    fileReady = Signal(str, str)
    openRequested = Signal(str, str)
    countChanged = Signal(int)   # 진행 중인 개수

    def __init__(self, parent=None, worker_factory=None):
        super().__init__(parent, Qt.Window)
        self.setWindowTitle(tr("녹화 · 다운로드"))
        self.resize(640, 420)
        self.worker_factory = worker_factory or _default_worker
        self.rows: list[DownloadRow] = []
        lay = QVBoxLayout(self)
        self.lbl_summary = QLabel()
        lay.addWidget(self.lbl_summary)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.NoFrame)
        host = QWidget()
        self.list_lay = QVBoxLayout(host)
        self.list_lay.setContentsMargins(0, 0, 0, 0)
        self.list_lay.addStretch(1)
        sa.setWidget(host)
        lay.addWidget(sa, 1)
        bottom = QHBoxLayout()
        hint = QLabel(tr("여러 방송을 동시에 녹화할 수 있습니다. 브라우저 확장에서 보낼 때마다 한 줄씩 추가됩니다."))
        hint.setStyleSheet("color:#9aa0a6; font-size:11px;")
        hint.setWordWrap(True)
        bottom.addWidget(hint, 1)
        b_clear = QPushButton(tr("끝난 항목 지우기"))
        b_clear.clicked.connect(self.clear_finished)
        bottom.addWidget(b_clear)
        lay.addLayout(bottom)
        self._update_summary()

    # ---- 추가 ----
    def find_active(self, url: str, page: str = "") -> DownloadRow | None:
        k = task_key(url, page)
        return next((r for r in self.rows if r.active and r.key == k), None)

    def add(self, params: dict) -> DownloadRow | None:
        """새 받기를 시작. 같은 방송(페이지 + 스트림 경로)이 이미 진행 중이면 None (중복 녹화 방지)."""
        if self.find_active(params["url"], params.get("page") or ""):
            LOG.info("받기 중복이라 건너뜀 (같은 방송이 이미 진행 중): %s | %s", (params.get("page") or "")[:100], params["url"][:100])
            return None
        os.makedirs(params["out_dir"], exist_ok=True)
        row = DownloadRow(params, self.worker_factory, self)
        row.finished.connect(self._on_row_finished)
        row.openRequested.connect(self.openRequested)
        self.rows.append(row)
        self.list_lay.insertWidget(self.list_lay.count() - 1, row)
        LOG.info("받기 추가 (%d개 진행 중): %s", self.active_count(), params["url"][:120])
        self._update_summary()
        return row

    def _on_row_finished(self, row: DownloadRow):
        self._update_summary()
        if row.state == DONE:
            self.fileReady.emit(row.path, row.params.get("page") or row.params["url"])

    def clear_finished(self):
        for r in [r for r in self.rows if not r.active]:
            self.rows.remove(r)
            r.setParent(None)
            r.deleteLater()
        self._update_summary()

    # ---- 상태 ----
    def active_count(self) -> int:
        return sum(1 for r in self.rows if r.active)

    def live_count(self) -> int:
        return sum(1 for r in self.rows if r.state in (LIVE, STOPPING))

    def _update_summary(self):
        n = self.active_count()
        done = sum(1 for r in self.rows if r.state == DONE)
        self.lbl_summary.setText(tr("진행 중 {0}개 · 완료 {1}개").format(n, done) if self.rows
                                 else tr("아직 받는 항목이 없습니다."))
        self.countChanged.emit(n)

    def stop_all_and_wait(self, timeout: float = 60.0) -> bool:
        """종료 · 업데이트 전: 라이브는 저장하고 멈추고, 일반 다운로드는 취소. 모두 끝나면 True."""
        for r in self.rows:
            if r.state == LIVE:
                r.stop_recording()
            elif r.state == RUNNING:
                r.cancel()
        t0 = time.time()
        while time.time() - t0 < timeout:
            QApplication.processEvents()
            if all(not r.worker.isRunning() for r in self.rows):
                QApplication.processEvents()   # 남은 done 신호 처리
                return True
            time.sleep(0.05)
        return False


def _default_worker(params: dict):
    from .workers import DownloadWorker
    return DownloadWorker(params["url"], params["out_dir"], params.get("quality") or "best", params.get("section"),
                          None, params.get("cookies") or "", params.get("referer") or "",
                          headers=params.get("headers") or {}, title=params.get("title") or "")
