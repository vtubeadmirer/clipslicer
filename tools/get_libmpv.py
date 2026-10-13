"""libmpv-2.dll 을 shinchiro/mpv-winbuild-cmake 최신 릴리스에서 받아 bin/ 에 넣는다.

사용: python tools/get_libmpv.py
압축 해제: 7-Zip / Bandizip / NanaZip 이 있으면 그걸 쓰고, 없으면 py7zr 로 시도
(mpv 빌드는 BCJ2 필터를 쓰기 때문에 py7zr 로는 실패할 수 있음 — 그 경우 7-Zip 이나 Bandizip 설치).
"""
import sys

# CI 러너처럼 콘솔 인코딩이 UTF-8 이 아닌 곳에서도 한글 출력이 죽지 않게
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request

# 고정 버전 (API 조회 없이 직접 받음 — GitHub Actions 러너는 비인증 API 호출이 자주 막힌다).
# 올릴 때는 두 값을 같이 바꾸고 실제 재생 테스트를 할 것. --latest 를 주면 API 로 최신을 찾는다.
TAG = "20261013"
ASSET = "mpv-dev-x86_64-20261013-git-9d144e57b6.7z"
API = "https://api.github.com/repos/shinchiro/mpv-winbuild-cmake/releases/latest"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "bin")
DLL = "libmpv-2.dll"

EXTRACTORS = [
    # (실행 파일 후보, 인자 생성 함수)
    (["7z", r"C:\Program Files\7-Zip\7z.exe", r"C:\Program Files\NanaZip\7z.exe"],
     lambda exe, archive, out: [exe, "e", "-y", f"-o{out}", archive, DLL, "-r"]),
    (["bz", r"C:\Program Files\Bandizip\bz.exe"],
     lambda exe, archive, out: [exe, "x", "-y", f"-o:{out}", archive, DLL]),
]


def find_extractor():
    for cands, argf in EXTRACTORS:
        for c in cands:
            exe = shutil.which(c) if not os.path.isabs(c) else (c if os.path.isfile(c) else None)
            if exe:
                return exe, argf
    return None, None


def extract_with_tool(exe, argf, archive: str, out: str) -> str | None:
    subprocess.run(argf(exe, archive, out), check=False, capture_output=True)
    for dirpath, _, files in os.walk(out):
        if DLL in files:
            return os.path.join(dirpath, DLL)
    return None


def extract_with_py7zr(data: bytes, out: str) -> str | None:
    try:
        import py7zr
    except ImportError:
        print("py7zr 가 없습니다 (pip install py7zr) — 또는 7-Zip/Bandizip 을 설치하세요.")
        return None
    with py7zr.SevenZipFile(io.BytesIO(data), "r") as z:
        names = [n for n in z.getnames() if n.endswith(DLL)]
        if not names:
            return None
        z.extract(path=out, targets=names)
    return os.path.join(out, names[0])


def main():
    tag, name = TAG, ASSET
    if "--latest" in sys.argv:
        req = urllib.request.Request(API, headers={"User-Agent": "ClipSlicer-tools"})
        with urllib.request.urlopen(req) as r:
            rel = json.load(r)
        asset = next((a for a in rel["assets"]
                      if a["name"].startswith("mpv-dev-x86_64-") and "-v3-" not in a["name"]
                      and a["name"].endswith(".7z")), None)
        if not asset:
            print("mpv-dev-x86_64 아카이브를 찾지 못했습니다.")
            return 1
        tag, name = rel["tag_name"], asset["name"]
    url = f"https://github.com/shinchiro/mpv-winbuild-cmake/releases/download/{tag}/{name}"
    print(f"다운로드: {name}")
    req = urllib.request.Request(url, headers={"User-Agent": "ClipSlicer-tools"})
    with urllib.request.urlopen(req) as r:
        data = r.read()
    print(f"  {len(data) / 1e6:.1f} MB 받음")

    tmp = tempfile.mkdtemp(prefix="libmpv_")
    archive = os.path.join(tmp, name)
    with open(archive, "wb") as f:
        f.write(data)

    exe, argf = find_extractor()
    found = None
    if exe:
        print(f"압축 해제: {exe}")
        found = extract_with_tool(exe, argf, archive, tmp)
    if not found:
        print("py7zr 로 시도…")
        try:
            found = extract_with_py7zr(data, tmp)
        except Exception as ex:
            print(f"py7zr 실패: {ex}")
    if not found:
        print("libmpv-2.dll 을 꺼내지 못했습니다. 7-Zip 또는 Bandizip 을 설치한 뒤 다시 실행하세요.")
        return 1

    os.makedirs(BIN, exist_ok=True)
    dst = os.path.join(BIN, DLL)
    shutil.copy2(found, dst)
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"완료: {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
