"""libmpv-2.dll 을 shinchiro/mpv-winbuild-cmake 최신 릴리스에서 받아 bin/ 에 넣는다.

사용: python tools/get_libmpv.py
필요: pip install py7zr
"""
import io
import json
import os
import sys
import urllib.request

API = "https://api.github.com/repos/shinchiro/mpv-winbuild-cmake/releases/latest"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "bin")


def main():
    try:
        import py7zr
    except ImportError:
        print("py7zr 가 필요합니다:  pip install py7zr")
        return 1
    with urllib.request.urlopen(API) as r:
        rel = json.load(r)
    asset = next((a for a in rel["assets"]
                  if a["name"].startswith("mpv-dev-x86_64-") and "-v3-" not in a["name"]
                  and a["name"].endswith(".7z")), None)
    if not asset:
        print("mpv-dev-x86_64 아카이브를 찾지 못했습니다.")
        return 1
    print(f"다운로드: {asset['name']} ({asset['size'] / 1e6:.1f} MB)")
    with urllib.request.urlopen(asset["browser_download_url"]) as r:
        data = r.read()
    os.makedirs(BIN, exist_ok=True)
    with py7zr.SevenZipFile(io.BytesIO(data), "r") as z:
        names = [n for n in z.getnames() if n.endswith("libmpv-2.dll")]
        if not names:
            print("아카이브 안에 libmpv-2.dll 이 없습니다.")
            return 1
        z.extract(path=BIN, targets=names)
    src = os.path.join(BIN, names[0])
    dst = os.path.join(BIN, "libmpv-2.dll")
    if os.path.abspath(src) != os.path.abspath(dst):
        os.replace(src, dst)
    print(f"완료: {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
