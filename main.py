"""ClipSlicer 실행 진입점."""
import os
import sys
import traceback

from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette, QColor, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from app import __version__
from app.paths import missing_tools, base_dir
from app.style import QSS
from app.logging_setup import setup as setup_logging, install_error_dialog, LOG


def apply_dark_theme(app: QApplication):
    app.setStyle("Fusion")
    p = QPalette()
    bg, base, text = QColor(37, 37, 42), QColor(28, 28, 32), QColor(228, 228, 232)
    p.setColor(QPalette.Window, bg)
    p.setColor(QPalette.WindowText, text)
    p.setColor(QPalette.Base, base)
    p.setColor(QPalette.AlternateBase, bg)
    p.setColor(QPalette.ToolTipBase, base)
    p.setColor(QPalette.ToolTipText, text)
    p.setColor(QPalette.Text, text)
    p.setColor(QPalette.Button, QColor(50, 50, 56))
    p.setColor(QPalette.ButtonText, text)
    p.setColor(QPalette.Highlight, QColor(66, 165, 245))
    p.setColor(QPalette.HighlightedText, QColor(10, 10, 10))
    p.setColor(QPalette.Disabled, QPalette.Text, QColor(120, 120, 128))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(120, 120, 128))
    app.setPalette(p)
    app.setStyleSheet(QSS)


def app_icon() -> QIcon:
    for name in ("icon.ico", "icon.png"):
        for d in (os.path.join(base_dir(), "assets"), base_dir(), getattr(sys, "_MEIPASS", "")):
            if d and os.path.isfile(os.path.join(d, name)):
                return QIcon(os.path.join(d, name))
    return QIcon()


def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName("ClipSlicer")
    app.setWindowIcon(app_icon())
    apply_dark_theme(app)
    setup_logging(__version__)

    missing = missing_tools()
    if missing:
        LOG.error("필수 파일 없음: %s", missing)
        QMessageBox.critical(
            None, "필요한 파일이 없습니다",
            "다음 파일을 프로그램 폴더(또는 bin\\ 폴더)에 넣어 주세요:\n\n  • "
            + "\n  • ".join(missing)
            + f"\n\n프로그램 폴더: {base_dir()}\n\n"
            "ffmpeg: https://www.gyan.dev/ffmpeg/builds/ (ffmpeg.exe, ffprobe.exe)\n"
            "libmpv: python tools\\get_libmpv.py 실행 (또는 mpv-dev 7z 에서 libmpv-2.dll 복사)",
        )
        return 1

    from app.mainwindow import MainWindow  # libmpv 준비 후 import

    try:
        win = MainWindow()
    except Exception:
        LOG.exception("메인 창 생성 실패")
        QMessageBox.critical(None, "실행 실패",
                             "창을 만들지 못했습니다. 그래픽 드라이버 문제일 수 있습니다.\n"
                             "settings.ini 에 compat_mode=1 을 추가해 호환 모드로 다시 실행해 보세요.\n\n"
                             + traceback.format_exc().strip().splitlines()[-1])
        return 1
    install_error_dialog(win)
    win.show()
    files = [a for a in sys.argv[1:] if os.path.exists(a)]
    if files:
        win.add_files(files)
    for flag in ("--updated", "--update-failed"):
        if flag in sys.argv[1:]:
            win.notify_startup_flag(flag)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
