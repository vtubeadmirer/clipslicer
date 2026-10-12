"""오류 로그 파일 + 처리되지 않은 예외 대화상자.

로그 위치: 프로그램 폴더\\logs\\clipslicer.log (쓸 수 없으면 %LOCALAPPDATA%\\ClipSlicer\\logs).
"""
from __future__ import annotations

import logging
import os
import platform
import sys
import threading
import traceback
from logging.handlers import RotatingFileHandler

from .paths import base_dir

LOG = logging.getLogger("clipslicer")
_LOG_DIR: str | None = None
_SEEN: set[str] = set()


def log_dir() -> str:
    global _LOG_DIR
    if _LOG_DIR:
        return _LOG_DIR
    candidates = [os.path.join(base_dir(), "logs"),
                  os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "ClipSlicer", "logs")]
    for d in candidates:
        try:
            os.makedirs(d, exist_ok=True)
            probe = os.path.join(d, ".write_test")
            with open(probe, "w"):
                pass
            os.remove(probe)
            _LOG_DIR = d
            return d
        except OSError:
            continue
    _LOG_DIR = os.getcwd()
    return _LOG_DIR


def log_file() -> str:
    return os.path.join(log_dir(), "clipslicer.log")


def setup(version: str) -> str:
    """파일 로그 핸들러와 예외 훅 설치. 로그 파일 경로를 돌려준다."""
    LOG.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(threadName)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    try:
        fh = RotatingFileHandler(log_file(), maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        fh.setFormatter(fmt)
        LOG.addHandler(fh)
    except OSError:
        pass
    if sys.stderr is not None:  # 콘솔이 있을 때만 (windowed exe 는 None)
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(fmt)
        sh.setLevel(logging.INFO)
        LOG.addHandler(sh)
    LOG.info("=== ClipSlicer %s 시작 | Python %s | %s %s | 폴더 %s",
             version, platform.python_version(), platform.system(), platform.release(), base_dir())

    def _hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            return
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        LOG.error("처리되지 않은 예외:\n%s", text)
        _report(text)

    def _thread_hook(args):
        _hook(args.exc_type, args.exc_value, args.exc_traceback)

    sys.excepthook = _hook
    threading.excepthook = _thread_hook
    return log_file()


# ---- 오류 대화상자 (메인 스레드에서만, 같은 오류는 한 번만) ----
_reporter = None


def _report(text: str):
    key = text.strip().splitlines()[-1] if text.strip() else text
    if key in _SEEN:
        return
    _SEEN.add(key)
    if _reporter is not None:
        _reporter.report.emit(text)


def install_error_dialog(parent):
    """QApplication 이 뜬 뒤에 호출. 백그라운드 스레드의 예외도 메인 스레드에서 대화상자로 보여 준다."""
    global _reporter
    from PySide6.QtCore import QObject, Signal, Qt
    from PySide6.QtWidgets import QMessageBox, QPushButton

    class Reporter(QObject):
        report = Signal(str)

    _reporter = Reporter()

    def show(text: str):
        box = QMessageBox(parent)
        box.setIcon(QMessageBox.Critical)
        box.setWindowTitle("문제가 생겼습니다")
        last = text.strip().splitlines()[-1] if text.strip() else "알 수 없는 오류"
        box.setText(f"{last}\n\n프로그램은 계속 쓸 수 있지만, 방금 동작은 완료되지 않았을 수 있습니다.")
        box.setDetailedText(text)
        b_log = QPushButton("로그 폴더 열기")
        box.addButton(b_log, QMessageBox.ActionRole)
        box.addButton("닫기", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is b_log:
            try:
                os.startfile(log_dir())
            except OSError:
                pass

    _reporter.report.connect(show, Qt.QueuedConnection)
