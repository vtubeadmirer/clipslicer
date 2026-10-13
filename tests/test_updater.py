"""업데이트: 버전 비교, 릴리스 파싱(전체 + 경량 zip), deps.txt 비교, 체크섬, 압축 풀기, 교체 스크립트(실제 robocopy)."""
import os
import shutil
import subprocess
import sys
import time
import zipfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import updater  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEPS_TEXT = "ffmpeg=autobuild-2026-10-12-13-12\nlibmpv=20261013\n"


def _asset(name, url, size=1):
    return {"name": name, "browser_download_url": url, "size": size}


def _release(with_update=True, with_deps=True, tag="v0.5.0"):
    assets = [_asset(f"ClipSlicer-{tag}-win64.zip", "z", 169_000_000),
              _asset(f"ClipSlicer-{tag}-win64.zip.sha256", "s")]
    if with_update:
        assets += [_asset(f"ClipSlicer-{tag}-win64-update.zip", "uz", 20_000_000),
                   _asset(f"ClipSlicer-{tag}-win64-update.zip.sha256", "us")]
    if with_deps:
        assets.append(_asset("deps.txt", "d"))
    return {"tag_name": tag, "body": "notes", "html_url": "u", "assets": assets}


def _make_app(root, deps=DEPS_TEXT, ffmpeg=True, libmpv=True):
    """ClipSlicer.exe + _internal (ffmpeg\\ffmpeg.exe, libmpv-2.dll, deps.txt) 를 가진 설치 폴더 흉내."""
    internal = root / "_internal"
    internal.mkdir(parents=True, exist_ok=True)
    (root / "ClipSlicer.exe").write_bytes(b"exe")
    if ffmpeg:
        (internal / "ffmpeg").mkdir(exist_ok=True)
        (internal / "ffmpeg" / "ffmpeg.exe").write_bytes(b"ff")
    if libmpv:
        (internal / "libmpv-2.dll").write_bytes(b"mpv")
    if deps is not None:
        (internal / "deps.txt").write_text(deps, encoding="utf-8")
    return root


# --------------------------------------------------------------------------- 버전 · 파싱
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
    assert rel["update_zip_url"] == "" and rel["update_sha_url"] == "" and rel["update_zip_size"] == 0 and rel["deps_url"] == ""
    assert updater.parse_release({"tag_name": "v0.5.0", "assets": []}) is None


def test_parse_release_both_assets():
    rel = updater.parse_release(_release())
    assert rel["zip_url"] == "z" and rel["zip_name"] == "ClipSlicer-v0.5.0-win64.zip" and rel["zip_size"] == 169_000_000
    assert rel["sha_url"] == "s"
    assert rel["update_zip_url"] == "uz" and rel["update_zip_name"] == "ClipSlicer-v0.5.0-win64-update.zip"
    assert rel["update_zip_size"] == 20_000_000 and rel["update_sha_url"] == "us"
    assert rel["deps_url"] == "d"
    # 자산 순서가 바뀌어도 전체/경량이 섞이지 않는다
    data = _release()
    data["assets"].reverse()
    rel2 = updater.parse_release(data)
    assert rel2["zip_url"] == "z" and rel2["sha_url"] == "s" and rel2["update_zip_url"] == "uz" and rel2["update_sha_url"] == "us"
    # 경량 zip 만 있고 전체가 없으면 릴리스로 안 친다
    only_upd = {"tag_name": "v0.5.0", "assets": [_asset("ClipSlicer-v0.5.0-win64-update.zip", "uz")]}
    assert updater.parse_release(only_upd) is None
    # 옛 릴리스: 이름이 안 맞는 .sha256 하나뿐이면 전체 zip 의 것
    old = {"tag_name": "v0.5.0", "assets": [_asset("ClipSlicer-v0.5.0-win64.zip", "z"), _asset("checksum.sha256", "s")]}
    assert updater.parse_release(old)["sha_url"] == "s"


def test_release_yml_asset_order_keeps_old_updater_working():
    """0.7.0 이하 업데이터는 '마지막 .sha256' 을 전체 zip 의 체크섬으로 본다.

    release.yml 이 업로드 순서로 전체 zip 의 sha 를 마지막에 두는지, 그리고 그 순서(또는 이름순)로 받은
    자산 목록에 옛 루프를 돌려도 전체 zip 의 sha 가 선택되는지 확인한다.
    """
    yml = open(os.path.join(ROOT, ".github", "workflows", "release.yml"), encoding="utf-8").read()
    files = yml.split("files: |", 1)[1].split("generate_release_notes")[0]
    order = [ln.strip() for ln in files.splitlines() if "env." in ln]
    assert order.index("${{ env.SHA }}") > order.index("${{ env.UPD_SHA }}")
    assert order.index("${{ env.SHA }}") > order.index("${{ env.ZIP }}")

    tag = "v0.8.0"
    names = {"ZIP": f"ClipSlicer-{tag}-win64.zip", "SHA": f"ClipSlicer-{tag}-win64.zip.sha256",
             "UPD": f"ClipSlicer-{tag}-win64-update.zip", "UPD_SHA": f"ClipSlicer-{tag}-win64-update.zip.sha256"}
    upload_order = [names[o.split("env.")[1].split(" ")[0]] for o in order] + ["deps.txt"]
    for assets in (upload_order, sorted(upload_order)):
        zip_asset = sha_asset = None
        for n in assets:  # HEAD(0.7.0) app/updater.py 의 루프와 같은 규칙
            if n.lower().endswith("win64.zip"):
                zip_asset = n
            elif n.lower().endswith(".sha256"):
                sha_asset = n
        assert zip_asset == names["ZIP"] and sha_asset == names["SHA"]


# --------------------------------------------------------------------------- deps.txt
def test_parse_and_local_deps(tmp_path):
    assert updater.parse_deps("ffmpeg=a\r\n# 주석\n\nlibmpv = b \nbroken\n=novalue\n") == {"ffmpeg": "a", "libmpv": "b"}
    assert updater.parse_deps("") == {}
    assert updater.local_deps(str(tmp_path)) == {}  # _internal 없음
    _make_app(tmp_path)
    assert updater.local_deps(str(tmp_path)) == {"ffmpeg": "autobuild-2026-10-12-13-12", "libmpv": "20261013"}
    assert updater.internal_dir(str(tmp_path)) == str(tmp_path / "_internal")


def test_has_bundled_deps_and_is_lite_dir(tmp_path):
    full = _make_app(tmp_path / "full")
    assert updater.has_bundled_deps(str(full)) and not updater.is_lite_dir(str(full))
    lite = _make_app(tmp_path / "lite", ffmpeg=False, libmpv=False)
    assert not updater.has_bundled_deps(str(lite)) and updater.is_lite_dir(str(lite))
    half = _make_app(tmp_path / "half", ffmpeg=True, libmpv=False)
    assert not updater.has_bundled_deps(str(half)) and updater.is_lite_dir(str(half))


def test_choose_asset_matrix(tmp_path):
    app = str(_make_app(tmp_path / "app"))
    local = updater.local_deps(app)
    same = {"ffmpeg": "autobuild-2026-10-12-13-12", "libmpv": "20261013"}

    rel = updater.parse_release(_release())
    rel["remote_deps"] = dict(same)
    assert updater.choose_asset(rel, local, app) == "update"  # 일치 → 경량

    rel["remote_deps"] = {"ffmpeg": "autobuild-2099-01-01-00-00", "libmpv": "20261013"}
    assert updater.choose_asset(rel, local, app) == "full"  # ffmpeg 버전 다름
    rel["remote_deps"] = {"ffmpeg": "autobuild-2026-10-12-13-12", "libmpv": "20991231"}
    assert updater.choose_asset(rel, local, app) == "full"  # libmpv 버전 다름
    rel["remote_deps"] = {}
    assert updater.choose_asset(rel, local, app) == "full"  # 릴리스 deps 비어 있음

    rel = updater.parse_release(_release(with_deps=False))
    assert rel["deps_url"] == ""
    assert updater.choose_asset(rel, local, app) == "full"  # 릴리스에 deps.txt 없음 (remote_deps 미리 안 채움 → fetch_deps("") = {})

    rel = updater.parse_release(_release())
    rel["remote_deps"] = dict(same)
    assert updater.choose_asset(rel, {}, app) == "full"  # 로컬 deps.txt 없음 (구버전 빌드)
    assert updater.choose_asset(rel, local, str(_make_app(tmp_path / "noff", ffmpeg=False))) == "full"  # 로컬 ffmpeg 없음
    assert updater.choose_asset(rel, local, str(_make_app(tmp_path / "nompv", libmpv=False))) == "full"  # 로컬 libmpv 없음

    rel = updater.parse_release(_release(with_update=False))
    rel["remote_deps"] = dict(same)
    assert updater.choose_asset(rel, local, app) == "full"  # 릴리스에 경량 zip 없음

    # 표시 크기는 선택된 zip 의 것
    rel = updater.parse_release(_release())
    rel["kind"] = "update"
    assert updater.chosen_size(rel) == 20_000_000
    rel["kind"] = "full"
    assert updater.chosen_size(rel) == 169_000_000
    assert updater.chosen_size({"zip_size": 5}) == 5


def test_fetch_deps_bad_url_is_empty():
    assert updater.fetch_deps("") == {}
    assert updater.fetch_deps("http://127.0.0.1:9/deps.txt", timeout=0.5) == {}


# --------------------------------------------------------------------------- 체크섬 · 폴더 찾기
def test_sha_and_find_app_dir(tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"hello")
    assert updater.sha256_file(str(f)) == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    root = tmp_path / "new"
    (root / "ClipSlicer" / "_internal").mkdir(parents=True)
    (root / "ClipSlicer" / "ClipSlicer.exe").write_bytes(b"x")
    assert updater.find_app_dir(str(root)) == str(root / "ClipSlicer")
    assert updater.find_app_dir(str(tmp_path / "nothing")) is None


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


# --------------------------------------------------------------------------- 다운로드 워커 (네트워크 대신 로컬 파일)
def _zip_dir(src_dir, zip_path, top="ClipSlicer"):
    with zipfile.ZipFile(zip_path, "w") as zf:
        for dirpath, _dirs, files in os.walk(src_dir):
            for name in files:
                full = os.path.join(dirpath, name)
                zf.write(full, top + "/" + os.path.relpath(full, src_dir).replace(os.sep, "/"))


def test_download_worker_picks_update_zip(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QCoreApplication
    app = QCoreApplication.instance() or QCoreApplication([])
    assert app is not None
    monkeypatch.setattr(updater.tempfile, "gettempdir", lambda: str(tmp_path / "tmp"))

    full_src = _make_app(tmp_path / "src_full")
    lite_src = _make_app(tmp_path / "src_lite", ffmpeg=False, libmpv=False)
    files = {}
    for key, src in (("z", full_src), ("uz", lite_src)):
        zp = tmp_path / f"{key}.zip"
        _zip_dir(str(src), str(zp))
        files[key] = str(zp)
        files[key + "s"] = str(tmp_path / f"{key}.sha256")
        (tmp_path / f"{key}.sha256").write_text(updater.sha256_file(str(zp)) + " *x.zip\n", encoding="ascii")
    files["s"] = files["zs"]
    files["us"] = files["uzs"]

    def fake_fetch(self, url, dst, size_hint):
        shutil.copyfile(files[url], dst)
    monkeypatch.setattr(updater.UpdateDownloadWorker, "_fetch", fake_fetch)

    results = []
    rel = updater.parse_release(_release())
    rel["remote_deps"] = {"ffmpeg": "autobuild-2026-10-12-13-12", "libmpv": "20261013"}
    local_app = str(_make_app(tmp_path / "installed"))
    real_local_deps = updater.local_deps
    monkeypatch.setattr(updater, "local_deps", lambda app_dir=None: real_local_deps(local_app))
    monkeypatch.setattr(updater, "has_bundled_deps", lambda app_dir=None: True)

    w = updater.UpdateDownloadWorker(rel)
    w.done.connect(lambda d, e: results.append((d, e)))
    w.run()  # 스레드 없이 동기 실행
    assert results and results[-1][1] == "", results
    new_dir = results[-1][0]
    assert w.kind == "update" and updater.is_lite_dir(new_dir)
    assert os.path.isfile(os.path.join(new_dir, "ClipSlicer.exe"))

    # 로컬 deps 가 없으면 전체 zip
    monkeypatch.setattr(updater, "local_deps", lambda app_dir=None: {})
    w2 = updater.UpdateDownloadWorker(rel)
    w2.done.connect(lambda d, e: results.append((d, e)))
    w2.run()
    assert results[-1][1] == "" and w2.kind == "full" and not updater.is_lite_dir(results[-1][0])

    # kind 를 명시하면 그대로 (rel['kind'] 보다 우선)
    rel["kind"] = "update"
    w3 = updater.UpdateDownloadWorker(rel, kind="full")
    w3.done.connect(lambda d, e: results.append((d, e)))
    w3.run()
    assert w3.kind == "full" and not updater.is_lite_dir(results[-1][0])

    # 체크섬 불일치는 실패
    (tmp_path / "uz.sha256").write_text("0" * 64 + " *x.zip\n", encoding="ascii")
    monkeypatch.setattr(updater, "local_deps", lambda app_dir=None: real_local_deps(local_app))
    rel.pop("kind")
    w4 = updater.UpdateDownloadWorker(rel)
    w4.done.connect(lambda d, e: results.append((d, e)))
    w4.run()
    assert results[-1][0] == "" and "체크섬" in results[-1][1]


# --------------------------------------------------------------------------- 교체 스크립트
def test_launch_replacer_command_and_keep_switch(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(updater.subprocess, "Popen", lambda cmd, **kw: calls.append(cmd))
    monkeypatch.setattr(updater.tempfile, "gettempdir", lambda: str(tmp_path / "tmp"))
    full = str(_make_app(tmp_path / "full"))
    lite = str(_make_app(tmp_path / "lite", ffmpeg=False, libmpv=False))
    app = str(tmp_path / "app")

    script = updater.launch_replacer(full, app, "x.exe", pid=123)
    assert os.path.exists(script) and calls[-1][-8:] == ["-ProcId", "123", "-App", app, "-New", full, "-Exe", "x.exe"]
    assert "-Keep" not in calls[-1]
    updater.launch_replacer(lite, app, "x.exe", pid=123, lite=True)
    assert calls[-1][-1] == "-Keep"
    # 안전장치: 새 폴더에 ffmpeg/libmpv 가 없는데 lite=False 로 불러도 -Keep (전체 교체면 /MIR 이 지워 버린다)
    updater.launch_replacer(lite, app, "x.exe", pid=123)
    assert calls[-1][-1] == "-Keep"
    # 전체 폴더 + lite=True 도 그대로 -Keep (ffmpeg 가 같은 버전이면 복사 안 해도 된다)
    updater.launch_replacer(full, app, "x.exe", pid=123, lite=True)
    assert calls[-1][-1] == "-Keep"
    text = open(script, encoding="utf-8-sig").read()
    assert "[switch]$Keep" in text and "/XD $keepDirs /XF $keepFiles" in text and "libmpv-2.dll" in text


def _run_replacer(app, new, lite):
    """교체 스크립트를 실제로 돌리고 started.txt 가 생길 때까지 기다린다 (최대 30초)."""
    (new / "started.cmd").write_text("@echo %* > \"%~dp0started.txt\"\n", encoding="ascii")
    waiter = subprocess.Popen(["cmd", "/c", "timeout /t 1 /nobreak >nul"], creationflags=0x08000000)
    script = updater.launch_replacer(str(new), str(app), "started.cmd", pid=waiter.pid, lite=lite)
    assert os.path.exists(script)
    for _ in range(60):
        if (app / "started.txt").exists():
            break
        time.sleep(0.5)
    return script


@pytest.mark.skipif(os.name != "nt", reason="robocopy/PowerShell 필요")
def test_replacer_script_swaps_files_and_keeps_settings(tmp_path):
    app = tmp_path / "app"
    (app / "_internal" / "ffmpeg").mkdir(parents=True)
    (app / "logs").mkdir()
    (app / "ClipSlicer.exe").write_bytes(b"OLD")
    (app / "_internal" / "old_only.dll").write_bytes(b"old")
    (app / "_internal" / "ffmpeg" / "ffmpeg.exe").write_bytes(b"ff-old")
    (app / "_internal" / "libmpv-2.dll").write_bytes(b"mpv-old")
    (app / "settings.ini").write_text("[x]\nkeep=1\n", encoding="utf-8")
    (app / "logs" / "clipslicer.log").write_text("log\n", encoding="utf-8")
    # 새 버전(전체): ffmpeg/libmpv 도 같이 바뀐다. 실행 파일 대신 같은 이름의 cmd 가 "실행됨" 표식을 남긴다
    new = tmp_path / "upd" / "new" / "ClipSlicer"
    (new / "_internal" / "ffmpeg").mkdir(parents=True)
    (new / "ClipSlicer.exe").write_bytes(b"NEW")
    (new / "_internal" / "new_only.dll").write_bytes(b"new")
    (new / "_internal" / "ffmpeg" / "ffmpeg.exe").write_bytes(b"ff-new")
    (new / "_internal" / "libmpv-2.dll").write_bytes(b"mpv-new")

    _run_replacer(app, new, lite=False)
    assert (app / "ClipSlicer.exe").read_bytes() == b"NEW"
    assert (app / "_internal" / "new_only.dll").exists()
    assert not (app / "_internal" / "old_only.dll").exists()
    assert (app / "_internal" / "ffmpeg" / "ffmpeg.exe").read_bytes() == b"ff-new"
    assert (app / "_internal" / "libmpv-2.dll").read_bytes() == b"mpv-new"
    assert (app / "settings.ini").read_text(encoding="utf-8") == "[x]\nkeep=1\n"
    assert (app / "logs" / "clipslicer.log").exists()
    assert (app / "_backup" / "ClipSlicer.exe").read_bytes() == b"OLD"
    assert (app / "_backup" / "_internal" / "libmpv-2.dll").read_bytes() == b"mpv-old"
    assert (app / "started.txt").read_text().strip() == "--updated"
    assert "성공" in (app / "logs" / "update.log").read_text(encoding="utf-8-sig")


@pytest.mark.skipif(os.name != "nt", reason="robocopy/PowerShell 필요")
def test_replacer_script_lite_keeps_ffmpeg_and_libmpv(tmp_path):
    app = tmp_path / "app"
    (app / "_internal" / "ffmpeg").mkdir(parents=True)
    (app / "logs").mkdir()
    (app / "ClipSlicer.exe").write_bytes(b"OLD")
    (app / "_internal" / "old_only.dll").write_bytes(b"old")
    (app / "_internal" / "ffmpeg" / "x.dll").write_bytes(b"ffdll")
    (app / "_internal" / "libmpv-2.dll").write_bytes(b"mpv")
    (app / "_internal" / "deps.txt").write_text("ffmpeg=a\nlibmpv=b\n", encoding="utf-8")
    (app / "settings.ini").write_text("[x]\nkeep=1\n", encoding="utf-8")
    # 새 버전(경량): ffmpeg\ 와 libmpv-2.dll 이 없다
    new = tmp_path / "upd" / "new" / "ClipSlicer"
    (new / "_internal").mkdir(parents=True)
    (new / "ClipSlicer.exe").write_bytes(b"NEW")
    (new / "_internal" / "new_only.dll").write_bytes(b"new")
    (new / "_internal" / "deps.txt").write_text("ffmpeg=a\nlibmpv=b\n", encoding="utf-8")
    assert updater.is_lite_dir(str(new))

    _run_replacer(app, new, lite=True)
    assert (app / "ClipSlicer.exe").read_bytes() == b"NEW"
    assert (app / "_internal" / "new_only.dll").exists()
    assert not (app / "_internal" / "old_only.dll").exists()
    assert (app / "_internal" / "ffmpeg" / "x.dll").read_bytes() == b"ffdll"  # 유지
    assert (app / "_internal" / "libmpv-2.dll").read_bytes() == b"mpv"       # 유지
    assert (app / "_internal" / "deps.txt").read_text(encoding="utf-8") == "ffmpeg=a\nlibmpv=b\n"
    assert (app / "settings.ini").read_text(encoding="utf-8") == "[x]\nkeep=1\n"
    assert (app / "_backup" / "ClipSlicer.exe").read_bytes() == b"OLD"
    assert (app / "started.txt").read_text().strip() == "--updated"
    log = (app / "logs" / "update.log").read_text(encoding="utf-8-sig")
    assert "성공" in log and "경량" in log


# --------------------------------------------------------------------------- 빌드 스크립트 · 워크플로
def test_release_yml_has_update_zip_step():
    with open(os.path.join(ROOT, ".github", "workflows", "release.yml"), encoding="utf-8") as f:
        text = f.read()
    assert "ClipSlicer-$ver-win64.zip" in text            # 전체 zip 이름은 그대로
    assert "ClipSlicer-$ver-win64-update.zip" in text     # 경량 zip
    assert "Remove-Item lite\\ClipSlicer\\_internal\\ffmpeg" in text
    assert "Remove-Item lite\\ClipSlicer\\_internal\\libmpv-2.dll" in text
    assert "get_ffmpeg.TAG" in text and "get_libmpv.TAG" in text and "deps.txt" in text
    assert "Copy-Item deps.txt dist\\ClipSlicer\\_internal\\deps.txt" in text
    assert "${{ env.UPD }}" in text and "${{ env.UPD_SHA }}" in text
    assert text.count("${{ env.UPD_SHA }}") == 2 and text.count("deps.txt\n") >= 2  # artifact + release 둘 다
    assert "Get-FileHash $f -Algorithm SHA256" in text and '"$f.sha256"' in text


def test_build_ps1_writes_deps_txt():
    with open(os.path.join(ROOT, "build.ps1"), encoding="utf-8") as f:
        text = f.read()
    assert 'Join-Path $internal "deps.txt"' in text
    assert "get_ffmpeg.TAG" in text and "get_libmpv.TAG" in text
    # PATH 를 비우는 검증 단계보다 앞에서 python 을 불러야 한다
    assert text.index("deps.txt") < text.index('$env:PATH = "$env:SystemRoot\\System32"')
