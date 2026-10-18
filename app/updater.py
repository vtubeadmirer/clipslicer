"""업데이트 확인 · 다운로드 · 교체.

흐름: GitHub Releases 최신 태그 조회 → 새 버전이면 알림 → zip 다운로드(+SHA-256 검증) → 임시 폴더에 풀기
      → 프로그램 종료 → PowerShell 교체 스크립트가 백업 후 파일 교체 → 재실행.
settings.ini, logs\\, 작업 파일은 건드리지 않는다.

경량 업데이트: 릴리스에는 전체 zip(약 170MB) 과 함께 ffmpeg\\ · libmpv-2.dll 을 뺀 -update.zip(약 20MB) 이 올라간다.
릴리스의 deps.txt(번들 ffmpeg/libmpv 버전) 가 로컬 _internal\\deps.txt 와 같고 그 파일들이 이미 있으면
경량 zip 만 받고, 교체 스크립트는 -Keep 스위치로 ffmpeg\\ 와 libmpv-2.dll 을 남긴다.
"""
from __future__ import annotations

from .i18n import tr
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile

from PySide6.QtCore import QThread, Signal

from .paths import base_dir

LOG = logging.getLogger("clipslicer")
REPO = "vtubeadmirer/clipslicer"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{REPO}/releases"
USER_AGENT = "ClipSlicer-updater"
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

DEPS_FILE = "deps.txt"             # _internal\deps.txt — "ffmpeg=<tag>\nlibmpv=<tag>" (build.ps1 / release.yml 이 생성)
UPDATE_ZIP_SUFFIX = "-update.zip"  # 경량 zip 이름 끝 (ffmpeg\ 와 libmpv-2.dll 이 빠진 사본)


# --------------------------------------------------------------------------- 버전
def parse_version(text: str) -> tuple[int, ...]:
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text or "")
    if not m:
        return (0,)
    return tuple(int(x or 0) for x in m.groups())


def is_newer(remote: str, local: str) -> bool:
    return parse_version(remote) > parse_version(local)


def parse_release(data: dict) -> dict | None:
    """GitHub release JSON → 릴리스 정보 dict (전체 zip 없으면 None).

    키: version, tag, notes, url,
        zip_url / zip_name / zip_size / sha_url                          (전체 zip)
        update_zip_url / update_zip_name / update_zip_size / update_sha_url  (경량 zip, 없으면 "" / 0)
        deps_url                                                        (릴리스 deps.txt, 없으면 "")
    """
    tag = data.get("tag_name") or ""
    assets = {a.get("name", ""): a for a in data.get("assets", []) if a.get("name")}
    zip_asset = upd_asset = None
    deps_asset = assets.get(DEPS_FILE)
    for name, a in assets.items():
        low = name.lower()
        if low.endswith(UPDATE_ZIP_SUFFIX):
            upd_asset = a
        elif low.endswith("win64.zip"):
            zip_asset = a
    if not zip_asset:
        return None

    def sha_for(asset: dict | None) -> str:
        if not asset:
            return ""
        sha = assets.get(asset["name"] + ".sha256")
        return sha["browser_download_url"] if sha else ""

    sha_url = sha_for(zip_asset)
    if not sha_url:  # 이름이 안 맞는 옛 릴리스: .sha256 하나뿐이면 전체 zip 의 것으로 본다
        loose = [a for n, a in assets.items() if n.lower().endswith(".sha256")
                 and not n.lower().endswith(UPDATE_ZIP_SUFFIX + ".sha256")]
        sha_url = loose[0]["browser_download_url"] if len(loose) == 1 else ""
    return {
        "version": ".".join(str(x) for x in parse_version(tag)),
        "tag": tag,
        "notes": data.get("body") or "",
        "url": data.get("html_url") or RELEASES_URL,
        "zip_url": zip_asset["browser_download_url"],
        "zip_name": zip_asset["name"],
        "zip_size": int(zip_asset.get("size") or 0),
        "sha_url": sha_url,
        "update_zip_url": upd_asset["browser_download_url"] if upd_asset else "",
        "update_zip_name": upd_asset["name"] if upd_asset else "",
        "update_zip_size": int(upd_asset.get("size") or 0) if upd_asset else 0,
        "update_sha_url": sha_for(upd_asset),
        "deps_url": deps_asset["browser_download_url"] if deps_asset else "",
    }


def can_self_update() -> tuple[bool, str]:
    """(가능 여부, 안 되는 이유). exe 로 실행 중이고 프로그램 폴더에 쓸 수 있어야 한다."""
    if not getattr(sys, "frozen", False):
        return False, tr("소스로 실행 중입니다 (git pull 로 갱신)")
    d = base_dir()
    try:
        probe = os.path.join(d, ".update_write_test")
        with open(probe, "w"):
            pass
        os.remove(probe)
    except OSError:
        return False, tr("프로그램 폴더에 쓸 수 없습니다 (읽기 전용 위치)")
    return True, ""


# --------------------------------------------------------------------------- 번들 의존성 (deps.txt)
def internal_dir(app_dir: str | None = None) -> str:
    """PyInstaller onedir 의 _internal 폴더. app_dir 을 주면 그 아래 _internal."""
    if app_dir:
        return os.path.join(app_dir, "_internal")
    meipass = getattr(sys, "_MEIPASS", None)
    return meipass or os.path.join(base_dir(), "_internal")


def parse_deps(text: str) -> dict[str, str]:
    """'key=value' 줄 → dict. 빈 줄 · # 주석 무시."""
    out: dict[str, str] = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k.strip():
            out[k.strip()] = v.strip()
    return out


def local_deps(app_dir: str | None = None) -> dict[str, str]:
    """로컬 _internal\\deps.txt 내용. 없으면 {} (구버전 빌드 → 전체 zip 으로 간다)."""
    path = os.path.join(internal_dir(app_dir), DEPS_FILE)
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return parse_deps(f.read())
    except OSError:
        return {}


def fetch_deps(url: str, timeout: float = 8) -> dict[str, str]:
    """릴리스의 deps.txt 를 받아 파싱. url 이 없거나 실패하면 {}."""
    if not url:
        return {}
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return parse_deps(r.read().decode("utf-8", errors="replace"))
    except Exception as ex:
        LOG.info("릴리스 deps.txt 받기 실패 (전체 zip 으로): %s", ex)
        return {}


def has_bundled_deps(app_dir: str | None = None) -> bool:
    """로컬 _internal 에 ffmpeg\\ffmpeg.exe 와 libmpv-2.dll 이 있는지 (경량 교체의 전제)."""
    d = internal_dir(app_dir)
    return os.path.isfile(os.path.join(d, "ffmpeg", "ffmpeg.exe")) and os.path.isfile(os.path.join(d, "libmpv-2.dll"))


def is_lite_dir(new_dir: str) -> bool:
    """풀린 새 버전 폴더에 ffmpeg\\ 나 libmpv-2.dll 이 없으면 경량(코드만) 업데이트."""
    d = os.path.join(new_dir, "_internal")
    return not (os.path.isdir(os.path.join(d, "ffmpeg")) and os.path.isfile(os.path.join(d, "libmpv-2.dll")))


def choose_asset(rel: dict, local: dict[str, str], app_dir: str | None = None) -> str:
    """받을 zip 선택: 'update'(경량) 또는 'full'.

    경량은 ① 릴리스에 -update.zip 이 있고 ② 로컬 deps.txt 가 있고 ③ 릴리스 deps.txt(rel['remote_deps'] 가 있으면 그것,
    없으면 deps_url 에서 받음) 의 항목이 로컬과 모두 같고 ④ 로컬에 ffmpeg/libmpv 가 실제로 있을 때만.
    """
    if not rel.get("update_zip_url"):
        return "full"
    if not local:
        return "full"
    remote = rel.get("remote_deps")
    if remote is None:
        remote = fetch_deps(rel.get("deps_url", ""))
    if not remote or any(local.get(k) != v for k, v in remote.items()):
        LOG.info("deps 불일치 → 전체 zip (로컬 %s / 릴리스 %s)", local, remote)
        return "full"
    if not has_bundled_deps(app_dir):
        return "full"
    return "update"


def chosen_size(rel: dict) -> int:
    """UI 표시용: rel['kind'] 에 맞는 zip 크기 (바이트)."""
    if rel.get("kind") == "update" and rel.get("update_zip_size"):
        return int(rel["update_zip_size"])
    return int(rel.get("zip_size") or 0)


# --------------------------------------------------------------------------- 확인
class UpdateCheckWorker(QThread):
    result = Signal(object)  # dict | None (None = 새 버전 없음 또는 확인 실패)

    def __init__(self, current_version: str, parent=None):
        super().__init__(parent)
        self.current_version = current_version

    def run(self):
        try:
            req = urllib.request.Request(API_LATEST, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
            with urllib.request.urlopen(req, timeout=8) as r:
                data = json.load(r)
            rel = parse_release(data)
            if rel and is_newer(rel["tag"], self.current_version):
                # 경량/전체 결정은 여기서 미리 (deps.txt 는 수십 바이트) → 대화상자가 받을 크기를 바로 보여 줄 수 있다
                rel["remote_deps"] = fetch_deps(rel["deps_url"]) if rel.get("update_zip_url") else {}
                rel["kind"] = choose_asset(rel, local_deps())
                rel["download_size"] = chosen_size(rel)  # UpdateDialog 가 보여 줄 실제 다운로드 크기
                LOG.info("새 버전 있음: %s (현재 %s, %s zip %.0f MB)", rel["tag"], self.current_version,
                         rel["kind"], rel["download_size"] / 1e6)
                self.result.emit(rel)
                return
            LOG.info("업데이트 확인: 최신 (%s)", self.current_version)
        except Exception as ex:  # 네트워크 없음, 404(릴리스 없음) 등은 조용히 넘어간다
            LOG.info("업데이트 확인 실패 (무시): %s", ex)
        self.result.emit(None)


# --------------------------------------------------------------------------- 다운로드 + 검증 + 풀기
class UpdateDownloadWorker(QThread):
    progress = Signal(float, str)
    done = Signal(str, str)  # (풀린 새 프로그램 폴더, 오류)

    def __init__(self, rel: dict, parent=None, kind: str | None = None):
        """kind: 'update' | 'full' | None(= rel['kind'] 또는 choose_asset 으로 결정). 실행 후 self.kind 에 남는다."""
        super().__init__(parent)
        self.rel = rel
        self.kind = kind
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def _fetch(self, url: str, dst: str, size_hint: int):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as r, open(dst, "wb") as f:
            total = int(r.headers.get("Content-Length") or size_hint or 0)
            got = 0
            while True:
                if self._cancel:
                    raise RuntimeError(tr("취소됨"))
                chunk = r.read(1 << 18)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                if total:
                    self.progress.emit(min(got / total, 0.99) * 0.85, tr("받는 중 {0:.0f} / {1:.0f} MB").format(got / 1e6, total / 1e6))

    def _pick(self) -> tuple[str, str, int, str]:
        """(zip_url, zip_name, zip_size, sha_url) — 경량이면 -update.zip."""
        if self.kind is None:
            self.kind = self.rel.get("kind") or choose_asset(self.rel, local_deps())
        if self.kind == "update" and self.rel.get("update_zip_url"):
            r = self.rel
            return r["update_zip_url"], r["update_zip_name"], int(r.get("update_zip_size") or 0), r.get("update_sha_url", "")
        self.kind = "full"
        r = self.rel
        return r["zip_url"], r["zip_name"], int(r.get("zip_size") or 0), r.get("sha_url", "")

    def run(self):
        work = os.path.join(tempfile.gettempdir(), "ClipSlicer-update")
        try:
            shutil.rmtree(work, ignore_errors=True)
            os.makedirs(work, exist_ok=True)
            zip_url, zip_name, zip_size, sha_url = self._pick()
            LOG.info("업데이트 다운로드 (%s): %s", self.kind, zip_name)
            self.progress.emit(0.0, tr("경량 업데이트 (ffmpeg/libmpv 는 그대로)") if self.kind == "update" else tr("전체 업데이트"))
            zip_path = os.path.join(work, zip_name)
            self._fetch(zip_url, zip_path, zip_size)

            if sha_url:
                self.progress.emit(0.86, tr("체크섬 확인 중…"))
                sha_path = os.path.join(work, "expected.sha256")
                self._fetch(sha_url, sha_path, 0)
                expected = open(sha_path, encoding="utf-8", errors="replace").read().split()[0].lower()
                actual = sha256_file(zip_path)
                if expected != actual:
                    raise RuntimeError(tr("받은 파일이 손상되었습니다 (체크섬 불일치). 다시 시도해 주세요."))
            else:
                LOG.warning("체크섬 파일이 없어 검증을 건너뜀")

            self.progress.emit(0.9, tr("압축 푸는 중…"))
            new_root = os.path.join(work, "new")
            with zipfile.ZipFile(zip_path) as z:
                z.extractall(new_root)
            new_dir = find_app_dir(new_root)
            if not new_dir:
                raise RuntimeError(tr("압축 안에 ClipSlicer.exe 가 없습니다"))
            os.remove(zip_path)
            self.progress.emit(1.0, tr("준비 완료"))
            self.done.emit(new_dir, "")
        except Exception as ex:
            LOG.exception("업데이트 다운로드 실패")
            shutil.rmtree(work, ignore_errors=True)
            self.done.emit("", str(ex))


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def find_app_dir(root: str) -> str | None:
    for dirpath, _dirs, files in os.walk(root):
        if "ClipSlicer.exe" in files:
            return dirpath
    return None


# --------------------------------------------------------------------------- 교체 스크립트
# -Keep: 경량 업데이트 — robocopy /MIR 에서 ffmpeg\ 와 libmpv-2.dll 을 제외해 새 폴더에 없어도 지우지 않는다.
REPLACER = '\n# ClipSlicer 업데이트 교체 스크립트 (자동 생성)\nparam([int]$ProcId, [string]$App, [string]$New, [string]$Exe, [switch]$Keep, [int]$WaitSec = 120)\n$ErrorActionPreference = "Continue"\n$log = Join-Path $App "logs\\update.log"\n$lock = Join-Path $App "_updating.lock"\nNew-Item -ItemType Directory -Force (Split-Path $log) | Out-Null\nfunction Log($m) { "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $m | Out-File -FilePath $log -Append -Encoding utf8 }\nfunction Under-App { Get-Process | Where-Object { $_.Path -and $_.Path.StartsWith($App, [System.StringComparison]::OrdinalIgnoreCase) } }\nLog "교체 시작 pid=$ProcId app=$App new=$New keep=$Keep"\n"$PID" | Out-File -FilePath $lock -Encoding ascii\ntry { Wait-Process -Id $ProcId -Timeout 60 -ErrorAction Stop } catch { }\n# 이 폴더에서 실행 중인 프로세스가 남아 있으면 파일이 잠겨 교체가 실패한다 (rc=11).\n# 내장 브라우저·ffmpeg 같은 보조 프로세스는 정리하고, 다른 ClipSlicer 창은 닫힐 때까지 기다린다.\n$deadline = (Get-Date).AddSeconds($WaitSec)\n$warned = $false\nwhile ($true) {\n  $procs = @(Under-App)\n  $helpers = @($procs | Where-Object { $_.ProcessName -ne [System.IO.Path]::GetFileNameWithoutExtension($Exe) })\n  foreach ($h in $helpers) { Log ("보조 프로세스 정리: {0} ({1})" -f $h.ProcessName, $h.Id); Stop-Process -Id $h.Id -Force -ErrorAction SilentlyContinue }\n  $apps = @($procs | Where-Object { $_.ProcessName -eq [System.IO.Path]::GetFileNameWithoutExtension($Exe) })\n  if ($apps.Count -eq 0) { break }\n  if (-not $warned) { Log ("다른 ClipSlicer 창이 열려 있어 닫힐 때까지 기다림: " + (($apps | ForEach-Object { $_.Id }) -join ", ")); $warned = $true }\n  if ((Get-Date) -gt $deadline) {\n    Log "중단: 다른 ClipSlicer 창이 계속 열려 있어 아무 파일도 바꾸지 않음"\n    Remove-Item -LiteralPath $lock -Force -ErrorAction SilentlyContinue\n    Start-Process -FilePath (Join-Path $App $Exe) -ArgumentList "--update-blocked" -WorkingDirectory $App\n    exit 2\n  }\n  Start-Sleep -Milliseconds 700\n}\nStart-Sleep -Milliseconds 500\n# 프로그램 폴더에 있는 사용자 데이터는 /MIR 이 지우지 않게 반드시 제외한다\n# (설정, 로그, 내장 브라우저 로그인, 유튜브 연결, 북마크·업로드 기록, 샘플)\n$keepDirs = @("_backup", "logs", "web_profile", "samples")\n$keepFiles = @("settings.ini", "_updating.lock", "youtube_token.bin", "youtube_client_secret.json", "*.jsonl")\nif ($Keep) { $keepDirs += @("ffmpeg"); $keepFiles += @("libmpv-2.dll"); Log "경량 교체: ffmpeg\\, libmpv-2.dll 유지" }\n$backup = Join-Path $App "_backup"\nLog "백업"\n& robocopy $App $backup /MIR /XD $keepDirs /XF $keepFiles /NFL /NDL /NJH /NJS /R:2 /W:1 | Out-Null\nLog "교체"\n& robocopy $New $App /MIR /XD $keepDirs /XF $keepFiles /NFL /NDL /NJH /NJS /R:2 /W:1 | Out-Null\n$rc = $LASTEXITCODE\nif ($rc -ge 8) {\n  Log "실패 rc=$rc → 백업에서 복구"\n  & robocopy $backup $App /MIR /XD $keepDirs /XF $keepFiles /NFL /NDL /NJH /NJS /R:2 /W:1 | Out-Null\n  Remove-Item -LiteralPath $lock -Force -ErrorAction SilentlyContinue\n  Start-Process -FilePath (Join-Path $App $Exe) -ArgumentList "--update-failed" -WorkingDirectory $App\n  exit 1\n}\nLog "성공 rc=$rc"\nRemove-Item -LiteralPath $New -Recurse -Force -ErrorAction SilentlyContinue\n# 압축을 풀었던 임시 폴더(ClipSlicer-update 아래 new)만 지운다. 이름이 다르면 손대지 않는다.\n$parent = Split-Path $New\nif ((Split-Path $parent -Leaf) -eq "new" -and (Split-Path (Split-Path $parent) -Leaf) -eq "ClipSlicer-update") {\n  Remove-Item -LiteralPath $parent -Recurse -Force -ErrorAction SilentlyContinue\n}\nRemove-Item -LiteralPath $lock -Force -ErrorAction SilentlyContinue\nStart-Process -FilePath (Join-Path $App $Exe) -ArgumentList "--updated" -WorkingDirectory $App\nexit 0\n'


def write_replacer(path: str):
    # BOM 을 직접 붙인다. 업데이트 도중 다른 창이 실행되면서 'utf-8-sig' 코덱 로드가 실패한 적이 있다
    # (LookupError: unknown encoding: utf-8-sig). 'utf-8' 은 인터프리터가 항상 들고 있어 안전하다.
    with open(path, "wb") as f:
        f.write(b"\xef\xbb\xbf" + (REPLACER.strip() + "\n").encode("utf-8"))


LOCK_NAME = "_updating.lock"
USER_FILES = ("youtube_token.bin", "youtube_client_secret.json", "bookmarks.jsonl", "youtube_uploads.jsonl")
USER_DIRS = ("web_profile", "samples")


def restore_user_data(app_dir: str | None = None) -> list[str]:
    """0.9.4 이하의 교체 스크립트는 /MIR 로 프로그램 폴더의 사용자 데이터를 지웠다.
    지워졌고 _backup 에는 남아 있으면 되살린다 (덮어쓰지 않음). 되살린 이름 목록을 돌려준다."""
    app_dir = app_dir or base_dir()
    backup = os.path.join(app_dir, "_backup")
    if not os.path.isdir(backup):
        return []
    restored = []
    for name in USER_FILES:
        src, dst = os.path.join(backup, name), os.path.join(app_dir, name)
        if os.path.isfile(src) and not os.path.exists(dst):
            try:
                shutil.copy2(src, dst)
                restored.append(name)
            except OSError:
                LOG.warning("사용자 데이터 복구 실패: %s", name, exc_info=True)
    for name in USER_DIRS:
        src, dst = os.path.join(backup, name), os.path.join(app_dir, name)
        if os.path.isdir(src) and not os.path.exists(dst):
            try:
                shutil.copytree(src, dst)
                restored.append(name)
            except OSError:
                LOG.warning("사용자 데이터 복구 실패: %s", name, exc_info=True)
    if restored:
        LOG.info("업데이트로 지워진 사용자 데이터를 _backup 에서 복구: %s", ", ".join(restored))
    return restored


def remove_backup(app_dir: str | None = None) -> int:
    """업데이트 후 새 버전이 정상으로 켜지면 _backup(이전 버전 전체 사본, 약 650 MB)을 지운다.

    _backup 은 교체가 실패했을 때 되돌리기 위한 것이라, 새 버전이 실행된 뒤에는 필요 없다.
    (0.9.13 까지는 지우지 않아 프로그램 폴더가 두 배로 커졌다.) restore_user_data 다음에 부를 것. 지운 바이트 수.
    """
    backup = os.path.join(app_dir or base_dir(), "_backup")
    if not os.path.isdir(backup):
        return 0
    size = 0
    for dirpath, _dirs, files in os.walk(backup):
        for f in files:
            try:
                size += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                pass
    shutil.rmtree(backup, ignore_errors=True)
    if os.path.isdir(backup):
        LOG.warning("이전 버전 백업을 다 지우지 못함: %s", backup)
    else:
        LOG.info("이전 버전 백업 삭제: %.0f MB", size / 1e6)
    return size


def update_in_progress(app_dir: str | None = None, max_age: float = 600.0) -> bool:
    """교체 스크립트가 지금 이 폴더를 바꾸는 중인가 (잠금 파일이 있고 10분이 안 지남)."""
    p = os.path.join(app_dir or base_dir(), LOCK_NAME)
    try:
        return time.time() - os.path.getmtime(p) < max_age
    except OSError:
        return False


def decode_output(data: bytes | None) -> str:
    """콘솔 프로그램 출력 bytes → str. UTF-8 우선, 아니면 한국어 윈도우 코드페이지(cp949), 그래도 안 되면 대체 문자."""
    if not data:
        return ""
    for enc in ("utf-8", "cp949"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            pass
    return data.decode("utf-8", errors="replace")


def other_instances(app_dir: str | None = None, own_pid: int | None = None) -> list[int]:
    """같은 폴더에서 실행 중인 다른 ClipSlicer.exe 의 PID 목록 (exe 로 실행 중일 때만, 실패하면 [])."""
    if os.name != "nt" or not getattr(sys, "frozen", False):
        return []
    app_dir = os.path.normcase(os.path.abspath(app_dir or base_dir()))
    own = own_pid or os.getpid()
    # 출력은 UTF-8 로 받는다: 경로에 한글(예: 문서)이 있으면 PowerShell 기본 코드페이지(cp949)와
    # 앱의 UTF-8 이 어긋나 text=True 디코딩이 읽기 스레드에서 실패하고 stdout 이 None 이 된다 (0.9.5~0.9.7 업데이트 오류)
    ps = ("[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
          "Get-CimInstance Win32_Process -Filter \"Name='ClipSlicer.exe'\" | "
          "ForEach-Object { \"$($_.ProcessId)|$($_.ExecutablePath)\" }")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True,
                           timeout=15, creationflags=CREATE_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return []
    text = decode_output(r.stdout)
    out = []
    for line in text.splitlines():
        pid, _, path = line.strip().partition("|")
        if pid.isdigit() and int(pid) != own and path and os.path.normcase(os.path.dirname(path)) == app_dir:
            out.append(int(pid))
    return out


def replacer_command(script: str, new_dir: str, app_dir: str, exe_name: str, pid: int, lite: bool) -> list[str]:
    """교체 스크립트 실행 명령줄. lite 면 -Keep (ffmpeg\\ · libmpv-2.dll 보존)."""
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", script,
           "-ProcId", str(pid), "-App", app_dir, "-New", new_dir, "-Exe", exe_name]
    if lite:
        cmd.append("-Keep")
    return cmd


def launch_replacer(new_dir: str, app_dir: str | None = None, exe_name: str = "ClipSlicer.exe", pid: int | None = None,
                    lite: bool = False) -> str:
    """교체 스크립트를 별도 PowerShell 프로세스로 띄운다. 호출한 쪽은 곧바로 종료해야 한다. 스크립트 경로를 돌려준다.

    lite=True 면 경량 교체(-Keep: ffmpeg\\ · libmpv-2.dll 유지). new_dir 에 그 파일들이 없는데 lite=False 로 부르면
    /MIR 이 지워 버려 프로그램이 망가지므로 안전장치로 경량 교체로 바꾼다.
    """
    app_dir = app_dir or base_dir()
    if not lite and is_lite_dir(new_dir):
        LOG.warning("새 폴더에 ffmpeg/libmpv 가 없어 경량 교체로 전환: %s", new_dir)
        lite = True
    script = os.path.join(tempfile.gettempdir(), "ClipSlicer-update", "replace.ps1")
    os.makedirs(os.path.dirname(script), exist_ok=True)
    write_replacer(script)
    cmd = replacer_command(script, new_dir, app_dir, exe_name, pid or os.getpid(), lite)
    LOG.info("교체 스크립트 실행: %s", " ".join(cmd))
    # 숨긴 콘솔 + 새 프로세스 그룹: 우리가 종료돼도 살아남고 창은 안 뜬다 (DETACHED_PROCESS 는 powershell 이 못 뜸)
    subprocess.Popen(cmd, creationflags=CREATE_NO_WINDOW | 0x00000200, close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return script
