"""ClipSlicer 실행 진입점."""
from app.i18n import tr
import os
import sys
import traceback

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPalette, QColor, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from app import __version__
from app.paths import missing_tools, base_dir
from app.style import QSS
from app.logging_setup import setup as setup_logging, install_error_dialog, LOG
from app.paths import make_settings
from app.i18n import set_language


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
    if "--selftest" in sys.argv:   # ClipSlicer.exe --selftest <결과.json> : 창 없이 핵심 기능 점검 (릴리즈 전 CI)
        i = sys.argv.index("--selftest")
        from app import selftest
        return selftest.run(sys.argv[i + 1] if i + 1 < len(sys.argv) else os.path.join(base_dir(), "selftest.json"))
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)  # 내장 브라우저(QtWebEngine)가 나중에 뜰 수 있게
    app = QApplication(sys.argv)
    app.setApplicationName("ClipSlicer")
    app.setWindowIcon(app_icon())
    apply_dark_theme(app)
    setup_logging(__version__)
    set_language(make_settings().value("lang", "auto"))

    from app import updater
    if "--updated" in sys.argv:
        updater.restore_user_data()  # 옛 버전의 교체 스크립트가 지운 유튜브 연결·로그인 등을 백업에서 되살림
    if updater.update_in_progress() and not any(f in sys.argv for f in ("--updated", "--update-failed", "--update-blocked")):
        # 교체 스크립트가 이 폴더의 파일을 바꾸는 중: 지금 뜨면 파일을 잠가 교체가 실패한다
        LOG.warning("업데이트 적용 중이라 실행하지 않음")
        QMessageBox.information(None, "ClipSlicer", tr("업데이트를 적용하는 중입니다. 끝나면 자동으로 다시 열립니다.\n잠시 뒤에 다시 실행해 주세요."))
        return 0

    missing = missing_tools()
    if missing:
        LOG.error("필수 파일 없음: %s", missing)
        QMessageBox.critical(
            None, tr("필요한 파일이 없습니다"),
            tr("다음 파일을 프로그램 폴더(또는 bin\\ 폴더)에 넣어 주세요:\n\n  • ")
            + "\n  • ".join(missing)
            + tr("\n\n프로그램 폴더: {0}\n\nffmpeg: https://www.gyan.dev/ffmpeg/builds/ (ffmpeg.exe, ffprobe.exe)\nlibmpv: python tools\\get_libmpv.py 실행 (또는 mpv-dev 7z 에서 libmpv-2.dll 복사)").format(base_dir()),
        )
        return 1

    from app.mainwindow import MainWindow  # libmpv 준비 후 import

    try:
        win = MainWindow()
    except Exception:
        LOG.exception("메인 창 생성 실패")
        QMessageBox.critical(None, tr("실행 실패"),
                             tr("창을 만들지 못했습니다. 그래픽 드라이버 문제일 수 있습니다.\nsettings.ini 에 compat_mode=1 을 추가해 호환 모드로 다시 실행해 보세요.\n\n")
                             + traceback.format_exc().strip().splitlines()[-1])
        return 1
    install_error_dialog(win)
    win.show()
    if "--site" in sys.argv:  # ClipSlicer.exe --site <방송 페이지 주소> : 사이트에서 녹화 창으로 바로
        i = sys.argv.index("--site")
        url = sys.argv[i + 1] if i + 1 < len(sys.argv) else ""
        QTimer.singleShot(300, lambda: win.open_site_recorder(url))
    files = [a for a in sys.argv[1:] if os.path.exists(a)]
    if files:
        win.add_files(files)
    for flag in ("--updated", "--update-failed", "--update-blocked"):
        if flag in sys.argv[1:]:
            win.notify_startup_flag(flag)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
