"""ffmpeg 가 있을 때만 도는 실제 자르기 통합 테스트 (mpv 불필요)."""
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.paths import find_tool  # noqa: E402

pytestmark = pytest.mark.skipif(not (find_tool("ffmpeg") and find_tool("ffprobe")), reason="ffmpeg 없음")

from app import ffmpeg_tools as ft  # noqa: E402


def _run(cmd):
    subprocess.run(cmd, check=True, capture_output=True)


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    d = tmp_path_factory.mktemp("media")
    mp4 = str(d / "t.mp4")
    # 20초, 30fps, 키프레임 3초 간격, 6~9초 무음
    _run([find_tool("ffmpeg"), "-v", "error", "-y",
          "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30:duration=20",
          "-f", "lavfi", "-i", "sine=frequency=440:duration=20",
          "-af", "volume='if(between(t,6,9),0,1)':eval=frame",
          "-c:v", "libx264", "-preset", "ultrafast", "-g", "90", "-pix_fmt", "yuv420p",
          "-c:a", "aac", "-shortest", mp4])
    srt = d / "s.srt"
    srt.write_text("1\n00:00:01,000 --> 00:00:03,000\nhello\n\n2\n00:00:10,000 --> 00:00:12,000\nworld\n", encoding="utf-8")
    mkv = str(d / "t.mkv")
    _run([find_tool("ffmpeg"), "-v", "error", "-y", "-i", mp4, "-i", str(srt),
          "-map", "0", "-map", "1", "-c:v", "copy", "-c:a", "copy", "-c:s", "srt", mkv])
    noaudio = str(d / "na.mp4")
    _run([find_tool("ffmpeg"), "-v", "error", "-y", "-i", mp4, "-an", "-c:v", "copy", noaudio])
    return {"mp4": mp4, "mkv": mkv, "noaudio": noaudio, "dir": str(d)}


def dur(p):
    return ft.probe(p)["duration"]


def test_probe(media):
    info = ft.probe(media["mp4"])
    assert abs(info["duration"] - 20) < 0.2
    assert info["width"] == 320 and info["vcodec"] == "h264" and info["acodec"] == "aac" and info["has_audio"]
    assert abs(info["fps"] - 30) < 0.01
    assert ft.probe(media["noaudio"])["has_audio"] is False


def test_keyframes_thumbs_waveform(media):
    kfs = ft.keyframes(media["mp4"])
    assert kfs[:3] == [0.0, 3.0, 6.0] and len(kfs) == 7
    th = ft.extract_thumbnails(media["mp4"], 20.0)
    assert 5 <= len(th) <= 25 and th[0][1][:2] == b"\xff\xd8"
    wave = ft.compute_waveform(media["mp4"], 200)
    assert len(wave) == 200 and max(wave) == 1.0
    assert max(wave[65:85]) < 0.05  # 6.5~8.5초 무음
    assert ft.compute_waveform(media["noaudio"]) is None


def test_silence(media):
    spans = ft.detect_silence(media["mp4"], -40, 0.8)
    assert len(spans) == 1 and abs(spans[0][0] - 6) < 0.2 and abs(spans[0][1] - 9) < 0.2


def test_fast_copy_lands_on_keyframe(media):
    out = os.path.join(media["dir"], "fast.mp4")
    ft.Cutter().cut_copy(media["mp4"], 4.0, 12.0, out, lambda p: None)
    assert abs(dur(out) - 9.0) < 0.3  # 앞 키프레임(3.0)부터 12.0 까지


def test_smart_is_frame_accurate(media):
    info = ft.probe(media["mp4"])
    kfs = ft.keyframes(media["mp4"])
    out = os.path.join(media["dir"], "smart.mp4")
    how = ft.Cutter().cut_smart(media["mp4"], 4.0, 12.0, out, info, kfs, lambda p: None)
    assert how == "smart" and abs(dur(out) - 8.0) < 0.1
    out2 = os.path.join(media["dir"], "smart_kf.mp4")
    assert ft.Cutter().cut_smart(media["mp4"], 6.0, 12.0, out2, info, kfs, lambda p: None) == "copy"
    out3 = os.path.join(media["dir"], "smart_nokf.mp4")
    assert ft.Cutter().cut_smart(media["mp4"], 4.0, 5.0, out3, info, kfs, lambda p: None) == "encode"
    assert abs(dur(out3) - 1.0) < 0.1


def test_precise_encode(media):
    out = os.path.join(media["dir"], "precise.mp4")
    ft.Cutter().cut_encode(media["mp4"], 4.5, 7.5, out, lambda p: None)
    assert abs(dur(out) - 3.0) < 0.1


def test_concat_inpoint_merge(media):
    out = os.path.join(media["dir"], "merged.mp4")
    ft.Cutter().concat([(media["mp4"], 0.0, 3.0), (media["mp4"], 9.0, 15.0)], out, lambda p: None, 9.0)
    assert abs(dur(out) - 9.0) < 0.1


def test_audio_extract(media):
    c = ft.Cutter()
    m4a = os.path.join(media["dir"], "a.m4a")
    c.cut_audio(media["mp4"], 2.0, 5.0, m4a, "aac", "aac", lambda p: None)
    mp3 = os.path.join(media["dir"], "a.mp3")
    c.cut_audio(media["mp4"], 2.0, 5.0, mp3, "mp3", "aac", lambda p: None)
    assert abs(dur(m4a) - 3.0) < 0.15 and abs(dur(mp3) - 3.0) < 0.15


def test_mkv_with_subtitles_to_mp4(media):
    """mkv 의 srt 자막은 mp4 로 복사할 수 없다 → 영상·오디오만 복사해서 성공해야 한다."""
    c = ft.Cutter()
    out = os.path.join(media["dir"], "subs.mp4")
    c.cut_copy(media["mkv"], 3.0, 9.0, out, lambda p: None)
    # mkv 는 탐색 지점(cue)이 성겨서 더 앞에서 시작할 수 있다: 끝점은 정확, 요청 구간은 포함
    assert 6.0 - 0.3 <= dur(out) <= 9.0 + 0.3
    merged = os.path.join(media["dir"], "subs_merged.mp4")
    c.concat([(media["mkv"], 0.0, 3.0), (media["mkv"], 9.0, 12.0)], merged, lambda p: None, 6.0)
    assert 6.0 - 0.3 <= dur(merged) <= 12.0 + 0.3
    r = subprocess.run([find_tool("ffprobe"), "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", out],
                       capture_output=True, text=True)
    assert "subtitle" not in r.stdout and "video" in r.stdout
    keep = os.path.join(media["dir"], "subs_keep.mkv")  # mkv → mkv 는 자막 유지
    c.cut_copy(media["mkv"], 0.0, 12.0, keep, lambda p: None)
    r = subprocess.run([find_tool("ffprobe"), "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", keep],
                       capture_output=True, text=True)
    assert "subtitle" in r.stdout


def test_no_audio_video(media):
    c = ft.Cutter()
    out = os.path.join(media["dir"], "na_cut.mp4")
    c.cut_copy(media["noaudio"], 3.0, 9.0, out, lambda p: None)
    assert abs(dur(out) - 6.0) < 0.3
    info = ft.probe(media["noaudio"])
    out2 = os.path.join(media["dir"], "na_smart.mp4")
    assert ft.Cutter().cut_smart(media["noaudio"], 4.0, 9.0, out2, info, ft.keyframes(media["noaudio"]), lambda p: None) == "smart"
    assert abs(dur(out2) - 5.0) < 0.1


def test_missing_input_reports_error(media):
    with pytest.raises(RuntimeError):
        ft.Cutter().cut_copy(os.path.join(media["dir"], "nope.mp4"), 0, 1, os.path.join(media["dir"], "x.mp4"), lambda p: None)
