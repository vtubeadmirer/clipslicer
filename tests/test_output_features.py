"""출력 기능 테스트: 음량 정규화 · 캡션 · 자막 굽기 · 세로 블러 · 워터마크 · 인트로/아웃트로 · drawtext 이스케이프 · ExportJob 기본값."""
import os
import re
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.paths import find_tool  # noqa: E402
from app import ffmpeg_tools as ft  # noqa: E402

needs_ffmpeg = pytest.mark.skipif(not (find_tool("ffmpeg") and find_tool("ffprobe")), reason="ffmpeg 없음")
W, H = 320, 180


# --------------------------------------------------------------------------- ffmpeg 없이
def _unescape(s: str) -> str:
    """ffmpeg 파서 한 단계: 역슬래시 다음 글자를 그대로."""
    return re.sub(r"\\(.)", r"\1", s, flags=re.S)


def test_drawtext_escaping():
    raw = "a'b:c%d\\e,f;g[h] \"q\" 한글 100% {x}"
    s = ft.drawtext_filter(raw, font_path="C:/Windows/Fonts/malgun.ttf", size=20)
    assert s.startswith("drawtext=text=") and ":fontfile=C\\\\:/Windows/Fonts/malgun.ttf:" in s
    assert "fontsize=20" in s and "fontcolor=white" in s and "box=1" in s and "x=(w-text_w)/2" in s
    text = s[len("drawtext=text="):].split(":fontfile=")[0]
    # 필터그래프 단계: [ ] , ; ' \ 가 전부 이스케이프돼 있어야 한다
    assert not re.search(r"(?<!\\)[\[\],;']", text)
    level1 = _unescape(text)
    assert not re.search(r"(?<!\\):", level1)          # 옵션 값 단계: ':' 이스케이프
    drawtext = _unescape(level1)
    assert not re.search(r"(?<!\\)%", drawtext)        # drawtext 확장 단계: '%' 이스케이프
    assert _unescape(drawtext) == raw                  # 세 단계를 거치면 원문 그대로
    # 줄바꿈은 그대로, CRLF 는 LF 로
    assert "\n" in ft.drawtext_filter("a\r\nb") and "\r" not in ft.drawtext_filter("a\r\nb")
    assert "fontsize=h*0.05" in ft.drawtext_filter("x") and "y=h*0.06" in ft.drawtext_filter("x", position="top")
    assert "font=Arial" in ft.drawtext_filter("x", font_path="")


def test_subtitles_and_overlay_filters():
    s = ft.subtitles_filter(r"C:\Users\x y\한글 [1].srt")
    assert s.startswith("subtitles=filename=C\\\\:/Users/x y/한글 \\[1\\].srt:force_style=")
    assert "FontName=Malgun Gothic" in s and "\\," in s
    assert "force_style" not in ft.subtitles_filter("C:/a/b.ass")
    vb = ft.vertical_blur_filter(1920, 1080)
    assert vb.startswith("split[bg][fg];[bg]scale=1080:1920:") and "boxblur" in vb
    assert "[fg]scale=1080:608:flags=lanczos[fgs]" in vb and vb.endswith("[bgb][fgs]overlay=(W-w)/2:(H-h)/2")
    assert "[fg]scale=1080:1920:" in ft.vertical_blur_filter(1080, 1920)   # 세로 원본은 높이에 맞춤
    assert ft.watermark_filter("tl", 0.5) == "[1:v]format=rgba,colorchannelmixer=aa=0.500[wm];[v][wm]overlay=24:24[vout]"
    assert ft.watermark_filter("br", 2.0).endswith("overlay=W-w-24:H-h-24[vout]") and "aa=1.000" in ft.watermark_filter("br", 2.0)
    assert ft.audio_normalize_args()[:2] == ["-af", "loudnorm=I=-14:TP=-1.5:LRA=11"]
    assert ft.audio_normalize_args()[-4:] == ["-c:a", "aac", "-b:a", "192k"]


def test_render_filter_args():
    info = {"width": 1920, "height": 1080}
    inputs, args = ft.render_filter_args(ft.RenderOptions(vertical=0.5, caption="hi"), info)
    assert inputs == [] and args[:4] == ["-map", "0:v:0", "-map", "0:a?"] and args[-2] == "-vf"
    assert args[-1].startswith("crop=606:1080:656:0,scale=1080:1920:flags=lanczos,drawtext=") and "fontsize=96" in args[-1]
    inputs, args = ft.render_filter_args(ft.RenderOptions(vertical=0.5, layout="blur", subtitle_path="s.srt", watermark="w.png"), info)
    assert inputs == ["-i", "w.png"] and args[0] == "-filter_complex" and args[2:4] == ["-map", "[vout]"]
    fc = args[1]
    assert fc.startswith("[0:v]split[bg][fg];") and "overlay=(W-w)/2:(H-h)/2,subtitles=filename=s.srt" in fc
    assert fc.endswith("[v];[1:v]format=rgba,colorchannelmixer=aa=0.800[wm];[v][wm]overlay=W-w-24:H-h-24[vout]")
    inputs, args = ft.render_filter_args(ft.RenderOptions(watermark="w.png"), info)
    assert args[1].startswith("[1:v]format=rgba") and "[0:v][wm]overlay" in args[1]
    assert ft.render_filter_args(ft.RenderOptions(), info)[1] == ["-map", "0:v:0", "-map", "0:a?", "-dn", "-sn"]
    assert ft.RenderOptions(caption=" ").has_overlays is False and ft.RenderOptions(watermark="w").has_overlays


def test_shift_subtitles(tmp_path):
    srt = tmp_path / "a.srt"
    srt.write_text("1\n00:00:00,500 --> 00:00:00,900\nold\n\n2\n00:00:00,500 --> 00:00:02,500\n걸침\n\n"
                   "3\n00:01:00,000 --> 00:01:01,250\nlater\n", encoding="utf-8")
    out = ft.shift_subtitles(str(srt), 1.0, str(tmp_path / "b.srt"))
    text = open(out, encoding="utf-8").read()
    assert text == "1\n00:00:00,000 --> 00:00:01,500\n걸침\n\n2\n00:00:59,000 --> 00:01:00,250\nlater\n"
    ass = tmp_path / "a.ass"
    ass.write_text("[Script Info]\nTitle: t\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
                   "Dialogue: 0,0:00:00.50,0:00:00.90,Default,,0,0,0,,old\n"
                   "Dialogue: 0,0:00:01.50,0:01:02.25,Default,,0,0,0,,a, b\n", encoding="utf-8")
    out = ft.shift_subtitles(str(ass), 1.0, str(tmp_path / "b.ass"))
    text = open(out, encoding="utf-8").read()
    assert "old" not in text and "Dialogue: 0,0:00:00.50,0:01:01.25,Default,,0,0,0,,a, b" in text and "[Script Info]" in text


def test_export_job_defaults():
    from app.workers import ExportJob, ExportPart
    job = ExportJob("a.mp4", {"width": 320}, [0.0], [ExportPart(0.0, 1.0)], "b.mp4", "fast", "", None, None)
    assert (job.normalize, job.caption, job.subtitle_path, job.layout) == (False, "", "", "crop")
    assert (job.watermark, job.watermark_pos, job.watermark_opacity, job.intro, job.outro, job.note) == ("", "br", 0.8, "", "", "")
    assert not job.has_overlays and not job.needs_encode
    assert ExportJob("a", {}, [], [], "b", "fast", "", None, None, caption="x").needs_encode
    assert ExportJob("a", {}, [], [], "b", "fast", "", 0.5, None).needs_encode
    assert not ExportJob("a", {}, [], [], "b", "precise", "aac", None, None).needs_encode
    assert not ExportJob("a", {}, [], [], "b", "fast", "", None, None, normalize=True).needs_encode
    opts = ExportJob("a", {}, [], [], "b", "fast", "", 0.3, None, layout="blur", watermark="w.png", normalize=True).render_options(False)
    assert (opts.vertical, opts.layout, opts.watermark, opts.normalize) == (0.3, "blur", "w.png", False)


# --------------------------------------------------------------------------- ffmpeg 필요
def _run(cmd):
    subprocess.run(cmd, check=True, capture_output=True)


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    d = tmp_path_factory.mktemp("outfx")
    src = str(d / "src.mp4")
    # 10초, 320x180, 어두운 회색 화면 + 440Hz 사인파 (44.1kHz)
    _run([find_tool("ffmpeg"), "-v", "error", "-y",
          "-f", "lavfi", "-i", f"color=c=0x202020:s={W}x{H}:r=30:d=10",
          "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=10",
          "-c:v", "libx264", "-preset", "ultrafast", "-g", "30", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", src])
    png = str(d / "wm.png")
    _run([find_tool("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=64x64:r=1",
          "-frames:v", "1", "-pix_fmt", "rgba", png])
    srt = d / "sub.srt"
    srt.write_text("1\n00:00:00,500 --> 00:00:02,500\n안녕 hello\n", encoding="utf-8")
    intro = str(d / "intro.mp4")   # 다른 크기, 오디오 없음
    _run([find_tool("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=blue:s=160x120:r=25:d=2",
          "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", intro])
    outro = str(d / "outro.mp4")   # 다른 크기, 오디오 있음
    _run([find_tool("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=lime:s=640x360:r=30:d=2",  # lime = 순수 초록
          "-f", "lavfi", "-i", "sine=frequency=880:duration=2",
          "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", outro])
    return {"src": src, "png": png, "srt": str(srt), "intro": intro, "outro": outro, "dir": str(d),
            "info": ft.probe(src)}


def _region(path: str, t: float, x: int, y: int, w: int, h: int) -> bytes:
    """t 초 프레임의 (x, y, w, h) 영역 rgb24 바이트."""
    p = subprocess.run([find_tool("ffmpeg"), "-v", "error", "-ss", f"{t:.3f}", "-i", path, "-frames:v", "1",
                        "-vf", f"crop={w}:{h}:{x}:{y}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                       capture_output=True, check=True)
    return p.stdout


def _bright(buf: bytes, thresh: int = 128) -> int:
    return sum(1 for i in range(0, len(buf), 3) if max(buf[i], buf[i + 1], buf[i + 2]) > thresh)


def _mean_rgb(buf: bytes) -> tuple[float, float, float]:
    n = max(len(buf) // 3, 1)
    return (sum(buf[0::3]) / n, sum(buf[1::3]) / n, sum(buf[2::3]) / n)


def _sample_rate(path: str) -> int:
    p = subprocess.run([find_tool("ffprobe"), "-v", "error", "-select_streams", "a:0", "-show_entries",
                        "stream=sample_rate", "-of", "csv=p=0", path], capture_output=True, text=True)
    return int(p.stdout.strip() or 0)


class Progress(list):
    def __call__(self, p: float):
        assert 0.0 <= p <= 1.0
        self.append(p)


@needs_ffmpeg
def test_normalize_cut_copy(media, tmp_path):
    out = str(tmp_path / "norm.mp4")
    prog = Progress()
    ft.Cutter().cut_copy(media["src"], 1.0, 4.0, out, prog, normalize=True)
    o = ft.probe(out)
    assert o["vcodec"] == "h264" and o["acodec"] == "aac" and o["has_audio"]
    assert abs(o["duration"] - 3.0) < 0.15 and _sample_rate(out) == 48000
    assert prog and prog[-1] > 0.9
    # 오디오만 + 정규화
    m4a = str(tmp_path / "norm.m4a")
    ft.Cutter().cut_audio(media["src"], 0.0, 2.0, m4a, "aac", "aac", prog, normalize=True)
    assert ft.probe(m4a)["acodec"] == "aac" and abs(ft.probe(m4a)["duration"] - 2.0) < 0.15
    # 합치기(concat demuxer) 에서 한 번만 정규화
    merged = str(tmp_path / "merged.mp4")
    ft.Cutter().concat([(media["src"], 0.0, 1.0), (media["src"], 5.0, 6.0)], merged, prog, 2.0, normalize=True)
    assert abs(ft.probe(merged)["duration"] - 2.0) < 0.2 and _sample_rate(merged) == 48000


@needs_ffmpeg
def test_caption_burn(media, tmp_path):
    out = str(tmp_path / "cap.mp4")
    opts = ft.RenderOptions(caption="안녕 ClipSlicer: 100% 'ok' \\ [x]\n둘째 줄")
    prog = Progress()
    ft.Cutter().cut_render(media["src"], 2.0, 4.0, out, media["info"], opts, prog)
    o = ft.probe(out)
    assert o["width"] == W and o["height"] == H and abs(o["duration"] - 2.0) < 0.15 and o["has_audio"]
    assert _bright(_region(out, 1.0, 0, H - 50, W, 50)) > 50     # 아래쪽에 글자
    assert _bright(_region(out, 1.0, 0, 0, W, 40)) == 0           # 위쪽은 그대로
    assert prog and prog[-1] > 0.9


@needs_ffmpeg
def test_drawtext_matches_textfile(media, tmp_path):
    """이스케이프한 text= 와 textfile(expansion=none) 렌더 결과가 픽셀 단위로 같아야 한다."""
    raw = "a'b:c%d\\e,f;g[h] \"q\" 한글 100% {x}\nline2"
    tf = tmp_path / "t.txt"
    with open(tf, "w", encoding="utf-8", newline="") as f:
        f.write(raw)
    font = "C:/Windows/Fonts/malgun.ttf"
    if not os.path.isfile(font):
        pytest.skip("malgun.ttf 없음")

    def frame(vf):
        p = subprocess.run([find_tool("ffmpeg"), "-v", "error", "-f", "lavfi", "-i", f"color=c=black:s={W}x{H}:r=1",
                            "-frames:v", "1", "-vf", vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                           capture_output=True, check=True)
        return p.stdout

    a = frame(ft.drawtext_filter(raw, font_path=font, size=20))
    ref = frame(f"drawtext=fontfile={ft._filter_path(font)}:fontsize=20:x=(w-text_w)/2:y=h-text_h-20:fontcolor=white:"
                f"borderw=2:bordercolor=black:box=1:boxcolor=black@0.45:boxborderw=6:expansion=none:"
                f"textfile={ft._filter_path(str(tf))}")
    assert len(a) == W * H * 3 and a == ref and _bright(a) > 100


@needs_ffmpeg
def test_subtitle_burn(media, tmp_path):
    out = str(tmp_path / "sub.mp4")
    opts = ft.RenderOptions(subtitle_path=media["srt"])
    ft.Cutter().cut_render(media["src"], 0.0, 3.0, out, media["info"], opts, lambda p: None)
    o = ft.probe(out)
    assert o["width"] == W and abs(o["duration"] - 3.0) < 0.15
    assert _bright(_region(out, 1.5, 0, 0, W, H)) > 20      # 0.5~2.5초 자막
    assert _bright(_region(out, 2.9, 0, 0, W, H)) == 0
    # 1초부터 자르면 자막이 구간 시작에 맞춰 0~1.5초로 옮겨져야 한다
    out2 = str(tmp_path / "sub2.mp4")
    ft.Cutter().cut_render(media["src"], 1.0, 4.0, out2, media["info"], opts, lambda p: None)
    assert _bright(_region(out2, 0.5, 0, 0, W, H)) > 20
    assert _bright(_region(out2, 2.0, 0, 0, W, H)) == 0


@needs_ffmpeg
def test_vertical_blur(media, tmp_path):
    out = str(tmp_path / "blur.mp4")
    opts = ft.RenderOptions(vertical=0.5, layout="blur", caption="쇼츠")
    prog = Progress()
    ft.Cutter().cut_render(media["src"], 0.0, 1.0, out, media["info"], opts, prog)
    o = ft.probe(out)
    assert o["width"] == 1080 and o["height"] == 1920 and abs(o["duration"] - 1.0) < 0.15
    assert prog and prog[-1] > 0.9


@needs_ffmpeg
def test_watermark(media, tmp_path):
    out = str(tmp_path / "wm.mp4")
    opts = ft.RenderOptions(watermark=media["png"], watermark_pos="br", watermark_opacity=0.8)
    ft.Cutter().cut_render(media["src"], 3.0, 5.0, out, media["info"], opts, lambda p: None)
    o = ft.probe(out)
    assert o["width"] == W and o["height"] == H and abs(o["duration"] - 2.0) < 0.15
    r, g, b = _mean_rgb(_region(out, 1.0, W - 64 - 24, H - 64 - 24, 64, 64))
    assert r > 150 and g < 60 and b < 60                      # 오른쪽 아래에 빨간 워터마크 (80% 불투명)
    r2, g2, b2 = _mean_rgb(_region(out, 1.0, 0, 0, 64, 64))
    assert abs(r2 - 32) < 12 and abs(g2 - 32) < 12            # 왼쪽 위는 원래 회색
    # 세로 크롭 + 워터마크 + 캡션 (filter_complex 조합)
    out2 = str(tmp_path / "wm_vert.mp4")
    opts2 = ft.RenderOptions(vertical=0.5, watermark=media["png"], watermark_pos="tl", caption="hi")
    ft.Cutter().cut_render(media["src"], 0.0, 1.0, out2, media["info"], opts2, lambda p: None)
    o2 = ft.probe(out2)
    assert o2["width"] == 1080 and o2["height"] == 1920
    r3, g3, _ = _mean_rgb(_region(out2, 0.5, 24, 24, 64, 64))
    assert r3 > 150 and g3 < 60


@needs_ffmpeg
def test_intro_outro(media, tmp_path):
    main = str(tmp_path / "main.mp4")
    ft.Cutter().cut_encode(media["src"], 0.0, 3.0, main, lambda p: None)
    out = str(tmp_path / "full.mp4")
    prog = Progress()
    ft.Cutter().concat_render([media["intro"], main, media["outro"]], out, prog, size=(W, H), fps=30.0, normalize=True)
    o = ft.probe(out)
    assert o["width"] == W and o["height"] == H and o["has_audio"] and abs(o["fps"] - 30) < 0.5  # avg_frame_rate
    assert abs(o["duration"] - 7.0) < 0.4 and _sample_rate(out) == 48000
    assert prog and prog[-1] > 0.9
    # 인트로(파랑) → 본편(회색) → 아웃트로(초록) 순서
    r, g, b = _mean_rgb(_region(out, 1.0, 0, 0, W, H))
    assert b > 150 and r < 60
    r, g, b = _mean_rgb(_region(out, 6.5, 0, 0, W, H))
    assert g > 150 and r < 60


@needs_ffmpeg
def test_export_worker_routing(media, tmp_path):
    """빠르게 + 캡션 + 인트로/아웃트로 + 정규화 → 재인코딩 경로, 진행률 0~1, 길이 = 본편 + 4초."""
    from PySide6.QtCore import QCoreApplication
    from app.workers import ExportJob, ExportPart, ExportWorker
    QCoreApplication.instance() or QCoreApplication([])
    dst = str(tmp_path / "job.mp4")
    job = ExportJob(media["src"], media["info"], [0.0, 1.0, 2.0], [ExportPart(1.0, 3.0), ExportPart(5.0, 6.0)], dst,
                    "fast", "", None, None, normalize=True, caption="테스트", intro=media["intro"], outro=media["outro"],
                    watermark=str(tmp_path / "missing.png"))   # 없는 워터마크는 무시
    assert job.needs_encode
    results, prog = [], []
    w = ExportWorker([job])
    w.jobProgress.connect(lambda i, p: prog.append(p))
    w.jobFinished.connect(lambda i, ok, msg: results.append((ok, msg)))
    w.run()
    assert results and results[0][0], results
    assert prog and all(0.0 <= p <= 1.0 for p in prog) and prog == sorted(prog) and prog[-1] == 1.0
    o = ft.probe(dst)
    assert abs(o["duration"] - 7.0) < 0.5 and o["width"] == W and o["has_audio"] and _sample_rate(dst) == 48000
    assert job.watermark == ""
    # 정규화만 켠 빠르게 모드는 비디오 복사 (인트로/아웃트로는 붙지 않음)
    dst2 = str(tmp_path / "copy.mp4")
    job2 = ExportJob(media["src"], media["info"], [], [ExportPart(0.0, 2.0)], dst2, "fast", "", None, None,
                     normalize=True, intro=media["intro"])
    assert not job2.needs_encode
    results.clear()
    w2 = ExportWorker([job2])
    w2.jobFinished.connect(lambda i, ok, msg: results.append((ok, msg)))
    w2.run()
    assert results[0][0] and abs(ft.probe(dst2)["duration"] - 2.0) < 0.15 and _sample_rate(dst2) == 48000


@needs_ffmpeg
@pytest.mark.parametrize("mode,merge,caption", [("fast", False, ""), ("smart", True, ""), ("precise", False, ""),
                                                ("fast", False, "캡션")])
def test_video_only_export(media, tmp_path, mode, merge, caption):
    """영상만 (소리 없음): 어떤 방식·합치기·재인코딩이든 결과에 오디오 스트림이 없고 길이는 그대로, 임시 파일은 안 남는다."""
    from PySide6.QtCore import QCoreApplication
    from app.workers import ExportJob, ExportPart, ExportWorker
    QCoreApplication.instance() or QCoreApplication([])
    parts = [ExportPart(1.0, 3.0), ExportPart(5.0, 6.0)] if merge else [ExportPart(1.0, 3.0)]
    dst = str(tmp_path / f"v_{mode}.mp4")
    job = ExportJob(media["src"], media["info"], ft.keyframes(media["src"]), parts, dst, mode, "", None, None,
                    normalize=True, caption=caption, mute=True)
    results, prog = [], []
    w = ExportWorker([job])
    w.jobProgress.connect(lambda i, p: prog.append(p))
    w.jobFinished.connect(lambda i, ok, msg: results.append((ok, msg)))
    w.run()
    assert results and results[0][0], results
    assert "소리 제거" in results[0][1] and job.dst == dst
    assert prog and prog == sorted(prog) and prog[-1] == 1.0
    o = ft.probe(dst)
    assert not o["has_audio"] and o["width"] == W
    assert abs(o["duration"] - sum(p.end - p.start for p in parts)) < 0.3
    assert os.listdir(tmp_path) == [os.path.basename(dst)]
