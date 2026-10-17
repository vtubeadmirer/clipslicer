"""문제 보고(비밀 값 가리기) · 자체 점검(--selftest)."""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.report import build_report, redact  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_redact_hides_secrets():
    s = redact("GET https://cdn.x/a.m3u8?sig=abc123&x=1&token=zzz\n"
               "Authorization: Bearer eyJhbGciOi.xx\nCookie: sess=ok; a=b\n"
               '{"refresh_token": "r-123", "access_token":"a-9"}\nbearer QWERTY==')
    for secret in ("abc123", "zzz", "eyJhbGciOi", "sess=ok", "r-123", "a-9", "QWERTY"):
        assert secret not in s, (secret, s)
    assert "x=1" in s and "cdn.x/a.m3u8" in s


def test_build_report(tmp_path):
    log = tmp_path / "clipslicer.log"
    log.write_text("\n".join(f"line {i}" for i in range(300)) + "\nurl?token=SECRET\n", encoding="utf-8")
    r = build_report(str(log), {"확장 연결": "대기 중"}, lines=50)
    assert r.startswith("ClipSlicer ") and "확장 연결: 대기 중" in r
    assert "line 299" in r and "line 200" not in r and "SECRET" not in r
    assert "최근 로그" in build_report(str(tmp_path / "none.log"))


def test_selftest_from_source(tmp_path):
    out = tmp_path / "st.json"
    env = dict(os.environ, PYTHONIOENCODING="utf-8", QT_QPA_PLATFORM="offscreen")
    r = subprocess.run([sys.executable, os.path.join(ROOT, "main.py"), "--selftest", str(out)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120, env=env)
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert set(rep["checks"]) == {"ffmpeg", "ffprobe", "libmpv", "webengine", "bridge", "updater", "settings", "extension"}
    failed = {k: v for k, v in rep["checks"].items() if not v["ok"]}
    assert r.returncode == (0 if not failed else 1)
    # ffmpeg/libmpv 가 없는 환경(CI 의 소스 테스트)에서는 그 둘만 실패할 수 있다
    assert set(failed) <= {"ffmpeg", "ffprobe", "libmpv"}, failed
