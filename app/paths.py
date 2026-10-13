"""외부 도구(ffmpeg, ffprobe, libmpv) 위치 탐색."""
from .i18n import tr
import os
import shutil
import sys


def base_dir() -> str:
    """exe(패키징) 또는 프로젝트 루트 디렉터리."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _candidate_dirs():
    b = base_dir()
    dirs = [os.path.join(b, "bin", "ffmpeg"), b, os.path.join(b, "bin")]
    meipass = getattr(sys, "_MEIPASS", None)  # PyInstaller 가 번들 파일을 푸는 곳 (onedir 은 _internal)
    if meipass and meipass not in dirs:
        dirs += [os.path.join(meipass, "ffmpeg"), meipass]
    return dirs


def find_tool(name: str) -> str | None:
    """ffmpeg / ffprobe 실행 파일 경로. 앱 폴더 -> bin/ -> PATH 순."""
    for d in _candidate_dirs():
        p = os.path.join(d, name + ".exe")
        if os.path.isfile(p):
            return p
    return shutil.which(name)


def prepare_libmpv() -> str | None:
    """libmpv-2.dll 이 있는 폴더를 DLL 검색 경로에 추가하고 그 폴더를 돌려준다."""
    for d in _candidate_dirs():
        for dll in ("libmpv-2.dll", "mpv-2.dll"):
            if os.path.isfile(os.path.join(d, dll)):
                if hasattr(os, "add_dll_directory"):
                    os.add_dll_directory(d)
                os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
                return d
    return None


def missing_tools() -> list[str]:
    missing = []
    if not find_tool("ffmpeg"):
        missing.append("ffmpeg.exe")
    if not find_tool("ffprobe"):
        missing.append("ffprobe.exe")
    if prepare_libmpv() is None:
        missing.append("libmpv-2.dll")
    return missing


def settings_file() -> str | None:
    """포터블 설정 파일 경로 (exe 옆 settings.ini). 그 폴더에 쓸 수 없으면 None → 레지스트리 사용."""
    path = os.path.join(base_dir(), "settings.ini")
    try:
        with open(path, "a", encoding="utf-8"):
            pass
        return path
    except OSError:
        return None


def make_settings():
    """QSettings 생성: 쓸 수 있으면 exe 옆 settings.ini (포터블), 아니면 레지스트리."""
    from PySide6.QtCore import QSettings
    path = settings_file()
    if path:
        return QSettings(path, QSettings.IniFormat)
    return QSettings("ClipSlicer", "ClipSlicer")
