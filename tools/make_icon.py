"""assets/icon.png, assets/icon.ico 생성 (Pillow 필요)."""
import sys

# CI 러너처럼 콘솔 인코딩이 UTF-8 이 아닌 곳에서도 한글 출력이 죽지 않게
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
import os
import sys

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")


def draw(size: int) -> Image.Image:
    s = size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = s * 0.22
    d.rounded_rectangle((0, 0, s - 1, s - 1), radius=r, fill=(30, 30, 36, 255))
    # 필름 띠
    band_top, band_bot = s * 0.30, s * 0.70
    d.rectangle((s * 0.08, band_top, s * 0.92, band_bot), fill=(66, 165, 245, 255))
    hole = s * 0.07
    n = 5
    for i in range(n):
        x = s * 0.12 + i * (s * 0.76 - hole) / (n - 1)
        d.rectangle((x, band_top + s * 0.03, x + hole, band_top + s * 0.03 + hole), fill=(30, 30, 36, 255))
        d.rectangle((x, band_bot - s * 0.03 - hole, x + hole, band_bot - s * 0.03), fill=(30, 30, 36, 255))
    # 빨간 자르기 선 + 삼각형
    cx = s * 0.60
    w = max(2, int(s * 0.045))
    d.rectangle((cx - w / 2, s * 0.14, cx + w / 2, s * 0.86), fill=(239, 83, 80, 255))
    t = s * 0.09
    d.polygon([(cx - t, s * 0.10), (cx + t, s * 0.10), (cx, s * 0.10 + t * 1.2)], fill=(239, 83, 80, 255))
    d.polygon([(cx - t, s * 0.90), (cx + t, s * 0.90), (cx, s * 0.90 - t * 1.2)], fill=(239, 83, 80, 255))
    return img


def main():
    os.makedirs(ASSETS, exist_ok=True)
    big = draw(512)
    big.save(os.path.join(ASSETS, "icon.png"))
    sizes = [16, 24, 32, 48, 64, 128, 256]
    frames = [draw(z) for z in sizes]
    frames[-1].save(os.path.join(ASSETS, "icon.ico"), format="ICO",
                    sizes=[(z, z) for z in sizes], append_images=frames[:-1])
    print("완료:", ASSETS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
