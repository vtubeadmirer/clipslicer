"""업데이트 확인 · 다운로드 · 교체.

흐름: GitHub Releases 최신 태그 조회 → 새 버전이면 알림 → zip 다운로드(+SHA-256 검증) → 임시 폴더에 풀기
      → 프로그램 종료 → PowerShell 교체 스크립트가 백업 후 파일 교체 → 재실행.
settings.ini, logs\\, 작업 파일은 건드리지 않는다.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
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


# --------------------------------------------------------------------------- 버전
def parse_version(text: str) -> tuple[int, ...]:
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text or "")
    if not m:
        return (0,)
    return tuple(int(x or 0) for x in m.groups())


def is_newer(remote: str, local: str) -> bool:
    return parse_version(remote) > parse_version(local)


def parse_release(data: dict) -> dict | None:
    """GitHub release JSON → {version, tag, notes, url, zip_url, zip_size, sha_url} (zip 없으면 None)."""
    tag = data.get("tag_name") or ""
    zip_asset = sha_asset = None
    for a in data.get("assets", []):
        name = a.get("name", "")
        if name.lower().endswith("win64.zip"):
            zip_asset = a
        elif name.lower().endswith(".sha256"):
            sha_asset = a
    if not zip_asset:
        return None
    return {
        "version": ".".join(str(x) for x in parse_version(tag)),
        "tag": tag,
        "notes": data.get("body") or "",
        "url": data.get("html_url") or RELEASES_URL,
        "zip_url": zip_asset["browser_download_url"],
        "zip_name": zip_asset["name"],
        "zip_size": int(zip_asset.get("size") or 0),
        "sha_url": sha_asset["browser_download_url"] if sha_asset else "",
    }


def can_self_update() -> tuple[bool, str]:
    """(가능 여부, 안 되는 이유). exe 로 실행 중이고 프로그램 폴더에 쓸 수 있어야 한다."""
    if not getattr(sys, "frozen", False):
        return False, "소스로 실행 중입니다 (git pull 로 갱신)"
    d = base_dir()
    try:
        probe = os.path.join(d, ".update_write_test")
        with open(probe, "w"):
            pass
        os.remove(probe)
    except OSError:
        return False, "프로그램 폴더에 쓸 수 없습니다 (읽기 전용 위치)"
    return True, ""


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
                LOG.info("새 버전 있음: %s (현재 %s)", rel["tag"], self.current_version)
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

    def __init__(self, rel: dict, parent=None):
        super().__init__(parent)
        self.rel = rel
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
                    raise RuntimeError("취소됨")
                chunk = r.read(1 << 18)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                if total:
                    self.progress.emit(min(got / total, 0.99) * 0.85, f"받는 중 {got / 1e6:.0f} / {total / 1e6:.0f} MB")

    def run(self):
        work = os.path.join(tempfile.gettempdir(), "ClipSlicer-update")
        try:
            shutil.rmtree(work, ignore_errors=True)
            os.makedirs(work, exist_ok=True)
            zip_path = os.path.join(work, self.rel["zip_name"])
            self._fetch(self.rel["zip_url"], zip_path, self.rel.get("zip_size", 0))

            if self.rel.get("sha_url"):
                self.progress.emit(0.86, "체크섬 확인 중…")
                sha_path = os.path.join(work, "expected.sha256")
                self._fetch(self.rel["sha_url"], sha_path, 0)
                expected = open(sha_path, encoding="utf-8", errors="replace").read().split()[0].lower()
                actual = sha256_file(zip_path)
                if expected != actual:
                    raise RuntimeError("받은 파일이 손상되었습니다 (체크섬 불일치). 다시 시도해 주세요.")
            else:
                LOG.warning("체크섬 파일이 없어 검증을 건너뜀")

            self.progress.emit(0.9, "압축 푸는 중…")
            new_root = os.path.join(work, "new")
            with zipfile.ZipFile(zip_path) as z:
                z.extractall(new_root)
            new_dir = find_app_dir(new_root)
            if not new_dir:
                raise RuntimeError("압축 안에 ClipSlicer.exe 가 없습니다")
            os.remove(zip_path)
            self.progress.emit(1.0, "준비 완료")
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
REPLACER = r"""
# ClipSlicer 업데이트 교체 스크립트 (자동 생성)
param([int]$ProcId, [string]$App, [string]$New, [string]$Exe)
$ErrorActionPreference = "Continue"
$log = Join-Path $App "logs\update.log"
New-Item -ItemType Directory -Force (Split-Path $log) | Out-Null
function Log($m) { "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $m | Out-File -FilePath $log -Append -Encoding utf8 }
Log "교체 시작 pid=$ProcId app=$App new=$New"
try { Wait-Process -Id $ProcId -Timeout 60 -ErrorAction Stop } catch { }
Start-Sleep -Milliseconds 800
$keepDirs = @("_backup", "logs")
$keepFiles = @("settings.ini")
$backup = Join-Path $App "_backup"
Log "백업"
& robocopy $App $backup /MIR /XD $keepDirs /XF $keepFiles /NFL /NDL /NJH /NJS /R:2 /W:1 | Out-Null
Log "교체"
& robocopy $New $App /MIR /XD $keepDirs /XF $keepFiles /NFL /NDL /NJH /NJS /R:3 /W:2 | Out-Null
$rc = $LASTEXITCODE
if ($rc -ge 8) {
  Log "실패 rc=$rc → 백업에서 복구"
  & robocopy $backup $App /MIR /XD $keepDirs /XF $keepFiles /NFL /NDL /NJH /NJS /R:2 /W:1 | Out-Null
  Start-Process -FilePath (Join-Path $App $Exe) -ArgumentList "--update-failed" -WorkingDirectory $App
  exit 1
}
Log "성공 rc=$rc"
Remove-Item -LiteralPath $New -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath (Split-Path $New) -Recurse -Force -ErrorAction SilentlyContinue
Start-Process -FilePath (Join-Path $App $Exe) -ArgumentList "--updated" -WorkingDirectory $App
exit 0
"""


def write_replacer(path: str):
    with open(path, "w", encoding="utf-8-sig") as f:
        f.write(REPLACER.strip() + "\n")


def launch_replacer(new_dir: str, app_dir: str | None = None, exe_name: str = "ClipSlicer.exe", pid: int | None = None) -> str:
    """교체 스크립트를 별도 PowerShell 프로세스로 띄운다. 호출한 쪽은 곧바로 종료해야 한다. 스크립트 경로를 돌려준다."""
    app_dir = app_dir or base_dir()
    script = os.path.join(tempfile.gettempdir(), "ClipSlicer-update", "replace.ps1")
    os.makedirs(os.path.dirname(script), exist_ok=True)
    write_replacer(script)
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", script,
           "-ProcId", str(pid or os.getpid()), "-App", app_dir, "-New", new_dir, "-Exe", exe_name]
    LOG.info("교체 스크립트 실행: %s", " ".join(cmd))
    # 숨긴 콘솔 + 새 프로세스 그룹: 우리가 종료돼도 살아남고 창은 안 뜬다 (DETACHED_PROCESS 는 powershell 이 못 뜸)
    subprocess.Popen(cmd, creationflags=CREATE_NO_WINDOW | 0x00000200, close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return script
