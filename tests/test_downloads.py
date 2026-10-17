"""녹화 · 다운로드 목록: 여러 개 동시 녹화, 중복 방지, 줄마다 따로 중지, 종료 시 모두 저장."""
import http.server
import json
import os
import subprocess
import sys
import threading

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.downloads import task_key  # noqa: E402
from app.paths import find_tool  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_task_key_ignores_tokens():
    assert task_key("https://cdn.x/live/a.m3u8?token=1") == task_key("https://CDN.x/live/a.m3u8?token=2#t")
    assert task_key("https://cdn.x/live/a.m3u8") != task_key("https://cdn.x/live/b.m3u8")


class _H(http.server.SimpleHTTPRequestHandler):
    root = ""

    def translate_path(self, path):
        return os.path.join(self.root, path.split("?")[0].lstrip("/").replace("/", os.sep))

    def log_message(self, *a):
        pass


@pytest.fixture(scope="module")
def streams(tmp_path_factory):
    ff = find_tool("ffmpeg")
    if not ff:
        pytest.skip("ffmpeg 없음")
    d = tmp_path_factory.mktemp("multi")
    vod = d / "vod"
    vod.mkdir()
    subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30:duration=8",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=8", "-c:v", "libx264", "-preset", "ultrafast",
                    "-g", "60", "-c:a", "aac", "-shortest", "-f", "hls", "-hls_time", "2", "-hls_playlist_type", "vod",
                    str(vod / "index.m3u8")], check=True, capture_output=True)
    text = (vod / "index.m3u8").read_text(encoding="utf-8")
    live_text = "\n".join(l for l in text.splitlines() if "ENDLIST" not in l and "PLAYLIST-TYPE" not in l) + "\n"
    for name in ("live1", "live2", "live3"):
        p = d / name
        p.mkdir()
        for f in vod.glob("*.ts"):
            (p / f.name).write_bytes(f.read_bytes())
        (p / "index.m3u8").write_text(live_text, encoding="utf-8")
    _H.root = str(d)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


_SCRIPT = r"""
import json, os, sys, time
sys.path.insert(0, sys.argv[1])
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from app.downloads import DownloadsWindow, DONE, LIVE
base, out = sys.argv[2], sys.argv[3]
app = QApplication([])
w = DownloadsWindow()
ready, counts, res = [], [], {}
w.fileReady.connect(lambda p, page: ready.append([p, page]))
w.countChanged.connect(counts.append)

def params(path, title):
    return {"url": base + path, "out_dir": out, "quality": "best", "section": None, "cookies": "", "referer": "",
            "headers": {"User-Agent": "test"}, "title": title, "page": "https://site/" + title, "cookie_file": ""}

r1 = w.add(params("/live1/index.m3u8?t=1", "방송1"))
r2 = w.add(params("/live2/index.m3u8", "방송2"))
r3 = w.add(params("/vod/index.m3u8", "다시보기"))
res["dup_rejected"] = w.add(params("/live1/index.m3u8?t=2", "방송1 again")) is None

def wait(cond, sec):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.05)
    return False

res["both_live"] = wait(lambda: r1.state == LIVE and r2.state == LIVE, 30)
res["active_at_peak"] = w.active_count()
wait(lambda: False, 3)
r1.stop_recording()                       # 하나만 먼저 멈춤 → 나머지는 계속
res["r2_still_live_after_r1_stop"] = wait(lambda: r1.state == DONE, 30) and r2.state == LIVE
res["vod_done"] = wait(lambda: r3.state == DONE, 60)
r4 = w.add(params("/live3/index.m3u8", "방송3"))
wait(lambda: r4.state == LIVE, 30)
wait(lambda: False, 2)
res["stop_all"] = w.stop_all_and_wait(60)  # 종료할 때와 같은 경로
res["states"] = [r.state for r in w.rows]
res["paths"] = [r.path for r in w.rows]
res["ready"] = ready
res["final_count"] = counts[-1] if counts else None
print("RESULT=" + json.dumps(res, ensure_ascii=True))
"""


def test_concurrent_recordings(streams, tmp_path):
    from app import ffmpeg_tools as ft
    env = dict(os.environ, PYTHONIOENCODING="utf-8", QT_QPA_PLATFORM="offscreen")
    r = subprocess.run([sys.executable, "-c", _SCRIPT, ROOT, streams, str(tmp_path)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=240, env=env)
    line = next((l for l in r.stdout.splitlines() if l.startswith("RESULT=")), None)
    assert line, (r.returncode, r.stdout[-800:], r.stderr[-1500:])
    res = json.loads(line[len("RESULT="):])
    assert res["dup_rejected"] and res["both_live"] and res["active_at_peak"] == 3, res
    assert res["r2_still_live_after_r1_stop"] and res["vod_done"] and res["stop_all"], res
    assert res["states"] == ["done"] * 4 and res["final_count"] == 0, res
    assert len(res["ready"]) == 4 and {p for _, p in res["ready"]} >= {"https://site/방송1", "https://site/다시보기"}
    names = sorted(os.path.basename(p) for p in res["paths"])
    assert [n.split(" ")[0] for n in names] == sorted(["방송1", "방송2", "방송3", "다시보기"]), names
    for p in res["paths"]:
        assert p.endswith(".mp4") and ft.probe(p)["duration"] > 1.0, p
    assert not [f for f in os.listdir(tmp_path) if f.endswith(".ts")]
