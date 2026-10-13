"""업데이트: 버전 비교, 릴리스 파싱, 체크섬, 압축 풀기, 교체 스크립트(실제 robocopy)."""
import os
import subprocess
import sys
import time
import zipfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import updater  # noqa: E402


def test_version_compare():
    assert updater.parse_version("v0.4.0") == (0, 4, 0)
    assert updater.parse_version("1.2") == (1, 2, 0)
    assert updater.is_newer("v0.5.0", "0.4.0")
    assert updater.is_newer("v1.0.0", "0.9.9")
    assert not updater.is_newer("v0.4.0", "0.4.0")
    assert not updater.is_newer("v0.3.9", "0.4.0")
    assert not updater.is_newer("garbage", "0.4.0")


def test_parse_release():
    data = {"tag_name": "v0.5.0", "body": "notes", "html_url": "u",
            "assets": [{"name": "ClipSlicer-v0.5.0-win64.zip", "browser_download_url": "z", "size": 10},
                       {"name": "ClipSlicer-v0.5.0-win64.zip.sha256", "browser_download_url": "s", "size": 1}]}
    rel = updater.parse_release(data)
    assert rel["version"] == "0.5.0" and rel["zip_url"] == "z" and rel["sha_url"] == "s" and rel["zip_size"] == 10
    assert updater.parse_release({"tag_name": "v0.5.0", "assets": []}) is None


def test_sha_and_find_app_dir(tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"hello")
    assert updater.sha256_file(str(f)) == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    root = tmp_path / "new"
    (root / "ClipSlicer" / "_internal").mkdir(parents=True)
    (root / "ClipSlicer" / "ClipSlicer.exe").write_bytes(b"x")
    assert updater.find_app_dir(str(root)) == str(root / "ClipSlicer")
    assert updater.find_app_dir(str(tmp_path / "nothing")) is None


@pytest.mark.skipif(os.name != "nt", reason="robocopy/PowerShell 필요")
def test_replacer_script_swaps_files_and_keeps_settings(tmp_path):
    app = tmp_path / "app"
    (app / "_internal").mkdir(parents=True)
    (app / "logs").mkdir()
    (app / "ClipSlicer.exe").write_bytes(b"OLD")
    (app / "_internal" / "old_only.dll").write_bytes(b"old")
    (app / "settings.ini").write_text("[x]\nkeep=1\n", encoding="utf-8")
    (app / "logs" / "clipslicer.log").write_text("log\n", encoding="utf-8")
    # 새 버전: 실행 파일 대신 같은 이름의 cmd 가 "실행됨" 표식을 남긴다
    new = tmp_path / "upd" / "new" / "ClipSlicer"
    (new / "_internal").mkdir(parents=True)
    (new / "ClipSlicer.exe").write_bytes(b"NEW")
    (new / "_internal" / "new_only.dll").write_bytes(b"new")
    (new / "started.cmd").write_text("@echo %* > \"%~dp0started.txt\"\n", encoding="ascii")

    waiter = subprocess.Popen(["cmd", "/c", "timeout /t 1 /nobreak >nul"], creationflags=0x08000000)
    script = updater.launch_replacer(str(new), str(app), "started.cmd", pid=waiter.pid)
    assert os.path.exists(script)
    for _ in range(60):
        if (app / "started.txt").exists():
            break
        time.sleep(0.5)
    assert (app / "ClipSlicer.exe").read_bytes() == b"NEW"
    assert (app / "_internal" / "new_only.dll").exists()
    assert not (app / "_internal" / "old_only.dll").exists()
    assert (app / "settings.ini").read_text(encoding="utf-8") == "[x]\nkeep=1\n"
    assert (app / "logs" / "clipslicer.log").exists()
    assert (app / "_backup" / "ClipSlicer.exe").read_bytes() == b"OLD"
    assert (app / "started.txt").read_text().strip() == "--updated"
    assert "성공" in (app / "logs" / "update.log").read_text(encoding="utf-8-sig")


def test_zip_layout_roundtrip(tmp_path):
    src = tmp_path / "ClipSlicer"
    src.mkdir()
    (src / "ClipSlicer.exe").write_bytes(b"x")
    z = tmp_path / "ClipSlicer-v9-win64.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.write(src / "ClipSlicer.exe", "ClipSlicer/ClipSlicer.exe")
    out = tmp_path / "out"
    with zipfile.ZipFile(z) as zf:
        zf.extractall(out)
    assert updater.find_app_dir(str(out)) == str(out / "ClipSlicer")
