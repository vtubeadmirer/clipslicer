"""업데이트 교체 사고 재현 테스트 (0.9.0 → 0.9.3 업데이트에서 실제로 난 문제들).

1) 같은 폴더에서 다른 ClipSlicer 창이 실행 중 → 파일이 잠겨 robocopy rc=11, 3분 재시도 끝에 실패.
   → 이제는 그 창이 닫힐 때까지 기다리고, 끝내 안 닫히면 아무것도 바꾸지 않고 중단해야 한다.
2) 내장 브라우저(QtWebEngineProcess)·ffmpeg 같은 보조 프로세스가 남아 파일을 잠금 → 정리하고 진행.
3) /MIR 이 프로그램 폴더의 사용자 데이터(유튜브 연결, 내장 브라우저 로그인, 북마크 기록)를 지움 → 보존.
4) 교체 스크립트를 'utf-8-sig' 코덱으로 쓰다 LookupError → 코덱 없이 BOM 을 직접 쓴다.
"""
import os
import shutil
import subprocess
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import updater  # noqa: E402

pytestmark = pytest.mark.skipif(os.name != "nt", reason="robocopy/PowerShell 필요")
PING = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "PING.EXE")


def _app(root, marker=b"OLD"):
    (root / "_internal").mkdir(parents=True)
    shutil.copy(PING, root / "ClipSlicer.exe")  # 실행 가능한 가짜 앱 (ping 으로 몇 초 버팀)
    (root / "_internal" / "core.dll").write_bytes(marker)
    return root


def _user_data(app):
    (app / "settings.ini").write_text("[x]\nk=1\n", encoding="utf-8")
    (app / "youtube_token.bin").write_bytes(b"TOKEN")
    (app / "youtube_client_secret.json").write_text("{}", encoding="utf-8")
    (app / "bookmarks.jsonl").write_text('{"ts": 1}\n', encoding="utf-8")
    (app / "youtube_uploads.jsonl").write_text('{"video_id": "x"}\n', encoding="utf-8")
    (app / "web_profile").mkdir()
    (app / "web_profile" / "Cookies").write_bytes(b"LOGIN")
    (app / "samples").mkdir()
    (app / "samples" / "sample.mp4").write_bytes(b"mp4")
    (app / "logs").mkdir()


def _run_replacer(tmp_path, app, new, wait_sec=30, pid=0):
    script = str(tmp_path / "replace.ps1")
    updater.write_replacer(script)
    cmd = updater.replacer_command(script, str(new), str(app), "ClipSlicer.exe", pid, lite=False) + ["-WaitSec", str(wait_sec)]
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, timeout=wait_sec + 90)
    return r.returncode, time.time() - t0, (app / "logs" / "update.log").read_text(encoding="utf-8-sig")


def _kill_relaunched(app):
    """교체 후 스크립트가 다시 띄운 가짜 앱(ping)을 정리."""
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    f"Get-Process | Where-Object {{ $_.Path -like '{app}*' }} | Stop-Process -Force"], capture_output=True)


def test_write_replacer_bom_without_codec(tmp_path):
    p = tmp_path / "r.ps1"
    updater.write_replacer(str(p))
    data = p.read_bytes()
    assert data.startswith(b"\xef\xbb\xbf") and "교체 시작".encode("utf-8") in data
    assert "-WaitSec" not in updater.replacer_command("s", "n", "a", "e", 1, False)  # 기본 대기는 스크립트 기본값


def test_update_in_progress_lock(tmp_path):
    assert not updater.update_in_progress(str(tmp_path))
    lock = tmp_path / updater.LOCK_NAME
    lock.write_text("123", encoding="ascii")
    assert updater.update_in_progress(str(tmp_path))
    old = time.time() - 3600
    os.utime(lock, (old, old))
    assert not updater.update_in_progress(str(tmp_path))  # 오래된 잠금은 무시 (스크립트가 죽은 경우)


def test_user_data_survives_full_update(tmp_path):
    app = _app(tmp_path / "app")
    _user_data(app)
    new = _app(tmp_path / "ClipSlicer-update" / "new" / "ClipSlicer", b"NEW")
    try:
        code, _, log = _run_replacer(tmp_path, app, new)
    finally:
        _kill_relaunched(app)
    assert code == 0 and "성공" in log, log
    assert (app / "_internal" / "core.dll").read_bytes() == b"NEW"
    assert (app / "youtube_token.bin").read_bytes() == b"TOKEN"
    assert (app / "youtube_client_secret.json").exists()
    assert (app / "bookmarks.jsonl").exists() and (app / "youtube_uploads.jsonl").exists()
    assert (app / "web_profile" / "Cookies").read_bytes() == b"LOGIN"
    assert (app / "samples" / "sample.mp4").exists()
    assert (app / "settings.ini").read_text(encoding="utf-8") == "[x]\nk=1\n"
    assert not (app / updater.LOCK_NAME).exists()


def test_waits_for_other_instance_then_succeeds(tmp_path):
    app = _app(tmp_path / "app")
    new = _app(tmp_path / "ClipSlicer-update" / "new" / "ClipSlicer", b"NEW")
    other = subprocess.Popen([str(app / "ClipSlicer.exe"), "-n", "5", "127.0.0.1"], stdout=subprocess.DEVNULL,
                             creationflags=0x08000000)  # 같은 폴더에서 4초쯤 더 실행되는 '다른 창'
    try:
        code, dt, log = _run_replacer(tmp_path, app, new, wait_sec=30)
    finally:
        other.kill()
        _kill_relaunched(app)
    assert code == 0 and "기다림" in log and "성공" in log, log
    assert dt >= 2.5 and dt < 40  # 기다렸다가 진행 (예전처럼 3분 재시도하지 않음)
    assert (app / "_internal" / "core.dll").read_bytes() == b"NEW"


def test_blocks_without_touching_files_when_other_instance_stays(tmp_path):
    app = _app(tmp_path / "app")
    _user_data(app)
    new = _app(tmp_path / "ClipSlicer-update" / "new" / "ClipSlicer", b"NEW")
    other = subprocess.Popen([str(app / "ClipSlicer.exe"), "-n", "60", "127.0.0.1"], stdout=subprocess.DEVNULL,
                             creationflags=0x08000000)
    try:
        code, dt, log = _run_replacer(tmp_path, app, new, wait_sec=3)
    finally:
        other.kill()
        _kill_relaunched(app)
    assert code == 2 and "중단" in log, log
    assert dt < 30
    assert (app / "_internal" / "core.dll").read_bytes() == b"OLD"  # 아무것도 안 바뀜
    assert (app / "youtube_token.bin").read_bytes() == b"TOKEN"
    assert not (app / "_backup").exists()
    assert not (app / updater.LOCK_NAME).exists()


def test_kills_leftover_helper_processes(tmp_path):
    app = _app(tmp_path / "app")
    shutil.copy(PING, app / "_internal" / "QtWebEngineProcess.exe")
    new = _app(tmp_path / "ClipSlicer-update" / "new" / "ClipSlicer", b"NEW")
    helper = subprocess.Popen([str(app / "_internal" / "QtWebEngineProcess.exe"), "-n", "60", "127.0.0.1"],
                              stdout=subprocess.DEVNULL, creationflags=0x08000000)
    try:
        code, dt, log = _run_replacer(tmp_path, app, new, wait_sec=20)
    finally:
        helper.kill()
        _kill_relaunched(app)
    assert code == 0 and "보조 프로세스 정리: QtWebEngineProcess" in log and "성공" in log, log
    assert helper.poll() is not None
    assert not (app / "_internal" / "QtWebEngineProcess.exe").exists()  # 새 버전엔 없으니 /MIR 로 정리됨


def test_cleanup_never_deletes_unexpected_parent(tmp_path):
    """새 버전 폴더의 상위가 예상한 임시 폴더(ClipSlicer-update/new)가 아니면 상위는 지우지 않는다."""
    app = _app(tmp_path / "app")
    new = _app(tmp_path / "ClipSlicer", b"NEW")  # 상위 = tmp_path (app 이 들어 있음)
    sibling = tmp_path / "keep_me.txt"
    sibling.write_text("x", encoding="utf-8")
    try:
        code, _, log = _run_replacer(tmp_path, app, new)
    finally:
        _kill_relaunched(app)
    assert code == 0 and "성공" in log
    assert app.exists() and sibling.exists()


def test_decode_output():
    assert updater.decode_output(None) == "" and updater.decode_output(b"") == ""
    assert updater.decode_output("12|C:\\문서\\a.exe".encode("utf-8")) == "12|C:\\문서\\a.exe"
    assert updater.decode_output("12|C:\\문서\\a.exe".encode("cp949")) == "12|C:\\문서\\a.exe"
    assert updater.decode_output(b"\xff\xfe\xfa") != ""


_OTHER_SCRIPT = r"""
import os, sys
sys.path.insert(0, sys.argv[1])
sys.frozen = True   # exe 로 실행 중인 것처럼
from app import updater
print("PIDS=" + ",".join(map(str, updater.other_instances(sys.argv[2], own_pid=1))))
"""


def test_other_instances_with_korean_folder(tmp_path):
    """0.9.5~0.9.7 오류 재현: 프로그램 폴더 경로에 한글(문서)이 있고 앱이 UTF-8 모드면 stdout 이 None 이 되어 업데이트가 죽었다."""
    app = _app(tmp_path / "문서 폴더" / "ClipSlicer")
    other = subprocess.Popen([str(app / "ClipSlicer.exe"), "-n", "30", "127.0.0.1"], stdout=subprocess.DEVNULL,
                             creationflags=0x08000000)
    try:
        time.sleep(1)
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        r = subprocess.run([sys.executable, "-X", "utf8", "-c", _OTHER_SCRIPT, root, str(app)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    finally:
        other.kill()
    line = next((l for l in r.stdout.splitlines() if l.startswith("PIDS=")), None)
    assert line, (r.returncode, r.stderr[-1500:])
    assert str(other.pid) in line.split("=", 1)[1].split(","), line


def test_remove_backup_only_touches_backup(tmp_path):
    """업데이트 후 남던 _backup(이전 버전 전체 사본)을 지운다. 사용자 데이터 · 프로그램 파일은 그대로."""
    app = _app(tmp_path / "app")
    _user_data(app)
    (app / "_backup" / "_internal").mkdir(parents=True)
    (app / "_backup" / "_internal" / "core.dll").write_bytes(b"x" * 5000)
    (app / "_backup" / "ClipSlicer.exe").write_bytes(b"old")
    assert updater.remove_backup(str(app)) >= 5003
    assert not (app / "_backup").exists()
    assert (app / "youtube_token.bin").exists() and (app / "web_profile" / "Cookies").exists()
    assert (app / "_internal" / "core.dll").read_bytes() == b"OLD" and (app / "settings.ini").exists()
    assert updater.remove_backup(str(app)) == 0          # 두 번째는 할 일 없음


def test_restore_user_data_from_backup(tmp_path):
    """0.9.4 이하 교체 스크립트가 지운 사용자 데이터를 0.9.5 첫 실행에서 되살린다 (기존 파일은 덮어쓰지 않음)."""
    app = tmp_path / "app"
    (app / "_backup" / "web_profile").mkdir(parents=True)
    (app / "_backup" / "youtube_token.bin").write_bytes(b"TOKEN")
    (app / "_backup" / "youtube_client_secret.json").write_text("{}", encoding="utf-8")
    (app / "_backup" / "web_profile" / "Cookies").write_bytes(b"LOGIN")
    (app / "_backup" / "bookmarks.jsonl").write_text("old\n", encoding="utf-8")
    (app / "bookmarks.jsonl").write_text("new\n", encoding="utf-8")  # 이미 있음 → 그대로
    got = updater.restore_user_data(str(app))
    assert set(got) == {"youtube_token.bin", "youtube_client_secret.json", "web_profile"}
    assert (app / "youtube_token.bin").read_bytes() == b"TOKEN"
    assert (app / "web_profile" / "Cookies").read_bytes() == b"LOGIN"
    assert (app / "bookmarks.jsonl").read_text(encoding="utf-8") == "new\n"
    assert updater.restore_user_data(str(app)) == []  # 두 번째는 할 일 없음
    assert updater.restore_user_data(str(tmp_path / "nothing")) == []
