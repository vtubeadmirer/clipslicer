"""ffmpeg 공유(shared) 빌드를 받아 bin/ffmpeg/ 에 넣는다.

정적 빌드(ffmpeg.exe 141MB + ffprobe.exe 141MB)와 달리 DLL 을 공유해서 전체 약 100MB.
BtbN/FFmpeg-Builds 의 특정 autobuild 태그에 고정 (재현 가능한 빌드).

사용: python tools/get_ffmpeg.py [--tag autobuild-YYYY-MM-DD-HH-MM]
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
import sys
import urllib.request
import zipfile

# 고정 버전. 올릴 때는 두 값을 같이 바꾸고 integration 테스트를 돌린다.
TAG = "autobuild-2026-10-12-13-12"
ASSET = "ffmpeg-n8.1.3-18-g46d899d7a0-win64-gpl-shared-8.1.zip"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST = os.path.join(ROOT, "bin", "ffmpeg")


def main(argv):
    tag = TAG
    asset = ASSET
    if "--tag" in argv:
        tag = argv[argv.index("--tag") + 1]
        api = f"https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/tags/{tag}"
        with urllib.request.urlopen(api) as r:
            rel = json.load(r)
        asset = next(a["name"] for a in rel["assets"]
                     if "win64-gpl-shared" in a["name"] and a["name"].endswith(".zip") and "-N-" not in a["name"])
    url = f"https://github.com/BtbN/FFmpeg-Builds/releases/download/{tag}/{asset}"
    print(f"다운로드: {asset}")
    with urllib.request.urlopen(url) as r:
        data = r.read()
    print(f"  {len(data) / 1e6:.1f} MB 받음, 압축 해제…")
    if os.path.isdir(DEST):
        shutil.rmtree(DEST)
    os.makedirs(DEST, exist_ok=True)
    n = 0
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for name in z.namelist():
            parts = name.split("/")
            # <root>/bin/ffmpeg.exe, <root>/bin/*.dll 만
            if len(parts) >= 3 and parts[1] == "bin" and parts[-1] and (
                    parts[-1].lower().endswith((".exe", ".dll"))):
                if parts[-1].lower() == "ffplay.exe":
                    continue
                with z.open(name) as src, open(os.path.join(DEST, parts[-1]), "wb") as dst:
                    shutil.copyfileobj(src, dst)
                n += 1
    # 혹시 남아 있는 정적 빌드는 치운다 (공유 빌드가 우선되도록)
    for old in ("ffmpeg.exe", "ffprobe.exe"):
        p = os.path.join(ROOT, "bin", old)
        if os.path.isfile(p):
            os.remove(p)
            print(f"  정적 빌드 제거: bin\\{old}")
    with open(os.path.join(DEST, "VERSION.txt"), "w", encoding="utf-8") as f:
        f.write(f"{tag}\n{asset}\n")
    size = sum(os.path.getsize(os.path.join(DEST, f)) for f in os.listdir(DEST)) / 1e6
    print(f"완료: {DEST} ({n}개 파일, {size:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
