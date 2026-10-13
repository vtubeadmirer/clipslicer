"""ffmpeg / ffprobe 호출 유틸리티.

프로브 · 썸네일 · 파형 · 키프레임 · 무음 감지 · 자르기(빠르게/정확하게/스마트) · 합치기 · 오디오 추출 · GPU 인코더 감지
· 출력 효과(음량 정규화 · 캡션 · 자막 굽기 · 세로 블러 · 워터마크 · 인트로/아웃트로)
"""
from __future__ import annotations

from .i18n import tr
import array
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Callable

from .paths import find_tool

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
LOG = logging.getLogger("clipslicer")
ProgressCb = Callable[[float], None]


def _popen_kwargs():
    return dict(creationflags=CREATE_NO_WINDOW, stdin=subprocess.DEVNULL)


def _run(cmd: list[str], timeout: float | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, **_popen_kwargs())


# --------------------------------------------------------------------------- 분석
def probe(path: str) -> dict:
    """duration(초), width, height, fps, vcodec, acodec, pix_fmt, has_audio."""
    cmd = [
        find_tool("ffprobe"), "-v", "error", "-print_format", "json",
        "-show_entries",
        "format=duration:stream=codec_type,codec_name,width,height,r_frame_rate,avg_frame_rate,pix_fmt,profile",
        path,
    ]
    out = _run(cmd)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or tr("ffprobe 실패"))
    data = json.loads(out.stdout)
    info = {"duration": float(data.get("format", {}).get("duration", 0) or 0),
            "width": 0, "height": 0, "fps": 30.0, "has_audio": False,
            "vcodec": "", "acodec": "", "pix_fmt": "", "profile": ""}
    for s in data.get("streams", []):
        if s.get("codec_type") == "video" and not info["width"]:
            info["width"] = int(s.get("width", 0) or 0)
            info["height"] = int(s.get("height", 0) or 0)
            info["vcodec"] = s.get("codec_name", "") or ""
            info["pix_fmt"] = s.get("pix_fmt", "") or ""
            info["profile"] = s.get("profile", "") or ""
            rate = s.get("avg_frame_rate") or s.get("r_frame_rate") or "30/1"
            try:
                n, d = rate.split("/")
                if float(d) > 0 and float(n) > 0:
                    info["fps"] = float(n) / float(d)
            except ValueError:
                pass
        elif s.get("codec_type") == "audio" and not info["has_audio"]:
            info["has_audio"] = True
            info["acodec"] = s.get("codec_name", "") or ""
    return info


def extract_thumbnails(path: str, duration: float, max_count: int = 200, height: int = 90) -> list[tuple[float, bytes]]:
    """영상 전체를 균등 분할한 썸네일(JPEG bytes) 목록. 1초 간격 이하로는 안 쪼갠다."""
    if duration <= 0:
        return []
    interval = max(duration / max_count, 1.0)
    tmp = tempfile.mkdtemp(prefix="clipslicer_thumbs_")
    pattern = os.path.join(tmp, "t_%05d.jpg")
    # -skip_frame nokey: 키프레임만 디코딩 → 전체 디코딩보다 10배 이상 빠르다 (썸네일엔 충분)
    cmd = [find_tool("ffmpeg"), "-v", "error", "-y", "-skip_frame", "nokey", "-an", "-sn", "-i", path,
           "-vf", f"fps=1/{interval},scale=-2:{height}", "-vsync", "vfr", "-q:v", "6", pattern]
    subprocess.run(cmd, capture_output=True, **_popen_kwargs())
    result = []
    for i, name in enumerate(sorted(os.listdir(tmp))):
        fp = os.path.join(tmp, name)
        with open(fp, "rb") as f:
            result.append((i * interval, f.read()))
        os.remove(fp)
    shutil.rmtree(tmp, ignore_errors=True)
    return result


def _chunk_peak(data: bytes) -> int:
    """s16le 바이트 덩어리의 절대 피크. audioop(C) 가 있으면 쓰고 없으면 순수 파이썬."""
    try:
        import audioop  # Python 3.12 까지 내장 (3.13 에서 제거)
        return audioop.max(data, 2)
    except ImportError:
        arr = array.array("h")
        arr.frombytes(data[: len(data) - len(data) % 2])
        return max((abs(x) for x in arr), default=0)


def compute_waveform(path: str, buckets: int = 4000) -> list[float] | None:
    """모노 8kHz PCM 으로 디코드한 뒤 bucket 별 피크(0~1) 목록."""
    cmd = [find_tool("ffmpeg"), "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "-"]
    proc = subprocess.run(cmd, capture_output=True, **_popen_kwargs())
    raw = proc.stdout
    n_samples = len(raw) // 2
    if proc.returncode != 0 or n_samples < 2:
        return None
    n = min(buckets, n_samples)
    per = n_samples // n
    peaks = [float(_chunk_peak(raw[i * per * 2:(i + 1) * per * 2])) for i in range(n)]
    top = max(peaks)
    return [v / top for v in peaks] if top > 0 else peaks


def keyframes(path: str) -> list[float]:
    """비디오 키프레임(I-frame) 시각 목록. 디코딩 없이 패킷만 읽어서 빠르다."""
    cmd = [find_tool("ffprobe"), "-v", "error", "-select_streams", "v:0",
           "-show_entries", "packet=pts_time,dts_time,flags", "-of", "csv=p=0", path]
    out = _run(cmd)
    if out.returncode != 0:
        return []
    kfs = []
    for line in out.stdout.splitlines():
        parts = line.strip().split(",")
        if len(parts) < 3 or "K" not in parts[2]:
            continue
        t = parts[0] if parts[0] not in ("N/A", "") else parts[1]
        try:
            kfs.append(float(t))
        except ValueError:
            pass
    kfs.sort()
    return kfs


def detect_silence(path: str, noise_db: float = -35.0, min_dur: float = 1.0) -> list[tuple[float, float]]:
    """silencedetect 필터로 (시작, 끝) 무음 구간 목록."""
    cmd = [find_tool("ffmpeg"), "-hide_banner", "-nostats", "-i", path, "-vn",
           "-af", f"silencedetect=noise={noise_db}dB:d={min_dur}", "-f", "null", "-"]
    out = _run(cmd)
    text = out.stderr
    starts = [float(m) for m in re.findall(r"silence_start:\s*([0-9.]+)", text)]
    ends = [float(m) for m in re.findall(r"silence_end:\s*([0-9.]+)", text)]
    spans = list(zip(starts, ends))
    if len(starts) > len(ends):  # 파일 끝까지 무음
        spans.append((starts[-1], float("inf")))
    return spans


def detect_scenes(path: str, duration: float, threshold: float = 0.4, min_gap: float = 2.0,
                  on_progress: ProgressCb | None = None, cancel=None) -> list[float]:
    """장면 전환 시각 목록. 작은 해상도로 줄여서 전체를 훑는다 (길이에 비례해 시간이 걸림)."""
    # scdet 은 모든 프레임을 통과시키므로 -progress 가 정확하고, 전환 지점은 로그로 알려 준다.
    # scdet 점수는 평균 프레임 차(0~255 스케일, 기본 임계값 10) → UI 의 0~1 민감도를 ×25 로 맞춘다.
    cmd = [find_tool("ffmpeg"), "-hide_banner", "-nostats", "-v", "info", "-i", path, "-an", "-sn",
           "-vf", f"scale=160:-2,scdet=threshold={threshold * 25:.2f}", "-progress", "pipe:1", "-f", "null", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace", **_popen_kwargs())
    times: list[float] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        if cancel is not None and cancel():
            proc.kill()
            break
        m = re.search(r"lavfi\.scd\.time:\s*([0-9.]+)", line)
        if m:
            t = float(m.group(1))
            if not times or t - times[-1] >= min_gap:
                times.append(t)
        elif on_progress and line.startswith("out_time_us="):
            try:
                on_progress(min(int(line.split("=", 1)[1]) / 1e6 / max(duration, 0.01), 1.0))
            except ValueError:
                pass
    proc.wait()
    return times


def grab_frame(path: str, t: float, fmt: str = "png") -> bytes:
    """t 초의 프레임 한 장 (png/jpeg 바이트)."""
    codec = "png" if fmt == "png" else "mjpeg"
    cmd = [find_tool("ffmpeg"), "-v", "error", "-ss", f"{max(t, 0):.3f}", "-i", path, "-an", "-sn",
           "-frames:v", "1", "-f", "image2", "-c:v", codec, "-"]
    proc = subprocess.run(cmd, capture_output=True, **_popen_kwargs())
    if proc.returncode != 0 or not proc.stdout:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace").strip() or tr("프레임을 읽지 못했습니다"))
    return proc.stdout


def vertical_crop_filter(width: int, height: int, frac: float, out_w: int = 1080, out_h: int = 1920) -> str:
    """9:16 크롭 + 스케일 필터. frac 은 가로(또는 세로) 위치 0~1."""
    frac = min(1.0, max(0.0, frac))
    if width / max(height, 1) > 9 / 16:
        cw = int(height * 9 / 16) // 2 * 2
        ch = height // 2 * 2
        cx = int((width - cw) * frac) // 2 * 2
        cy = 0
    else:
        cw = width // 2 * 2
        ch = int(width * 16 / 9) // 2 * 2
        cx = 0
        cy = int((height - ch) * frac) // 2 * 2
    return f"crop={cw}:{ch}:{cx}:{cy},scale={out_w}:{out_h}:flags=lanczos"


# --------------------------------------------------------------------------- 출력 효과 필터
def _escape_level1(s: str) -> str:
    """필터 옵션 값 단계 (':' 로 옵션을 나누는 파서): \\ ' : 를 이스케이프."""
    return s.replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:")


def _escape_level2(s: str) -> str:
    """필터그래프 단계 ([ ] , ; 로 체인을 나누는 파서): \\ ' [ ] , ; 를 이스케이프."""
    for ch in "\\'[],;":
        s = s.replace(ch, "\\" + ch)
    return s


def filter_escape(value: str) -> str:
    """필터 옵션 값에 그대로 넣을 문자열. ffmpeg 는 필터그래프 → 옵션 값 두 단계로 풀므로 두 번 이스케이프한다.

    (-vf / -filter_complex 를 subprocess 인자 목록으로 넘길 때 기준. 셸을 거치면 한 단계가 더 필요하다)
    """
    return _escape_level2(_escape_level1(value))


def _filter_path(path: str) -> str:
    """윈도 경로를 필터 옵션용으로: 역슬래시는 / 로, 드라이브 콜론 등 특수문자는 이스케이프."""
    return filter_escape(path.replace("\\", "/"))


def default_font_path() -> str:
    """캡션 기본 글꼴 파일. 맑은 고딕 → Arial → '' (없으면 fontconfig 의 font=Arial 사용)."""
    for p in ("C:/Windows/Fonts/malgun.ttf", "C:/Windows/Fonts/arial.ttf"):
        if os.path.isfile(p):
            return p
    return ""


def drawtext_filter(text: str, font_path: str | None = None, size: int | None = None, position: str = "bottom") -> str:
    """캡션을 영상에 굽는 drawtext 필터 문자열.

    text 는 drawtext 확장 문법(\\ 와 %) 과 필터그래프 두 단계 이스케이프를 모두 거친다. 줄바꿈은 그대로 넘기면
    drawtext 가 여러 줄로 그린다. 흰 글자 + 검은 테두리 + 반투명 검은 상자, 가운데 정렬.
    size 가 없으면 영상 높이의 5%, position: bottom | top | center (위아래 여백은 높이의 6%).
    """
    body = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    body = body.replace("\\", "\\\\").replace("%", "\\%")  # drawtext 자체 확장 단계
    parts = [f"text={filter_escape(body)}"]
    font = default_font_path() if font_path is None else font_path
    parts.append(f"fontfile={_filter_path(font)}" if font else "font=Arial")
    if size:
        size = max(int(size), 8)
        parts.append(f"fontsize={size}")
        margin = str(max(size, 10))
        boxw = max(size // 3, 6)
    else:
        parts.append("fontsize=h*0.05")
        margin = "h*0.06"
        boxw = 10
    y = {"top": margin, "center": "(h-text_h)/2"}.get(position, f"h-text_h-{margin}")
    parts += ["x=(w-text_w)/2", f"y={y}", "fontcolor=white", "borderw=2", "bordercolor=black",
              "box=1", "boxcolor=black@0.45", f"boxborderw={boxw}"]
    return "drawtext=" + ":".join(parts)


def subtitles_filter(srt_path: str, font_name: str = "Malgun Gothic") -> str:
    """자막 파일(.srt/.ass …)을 굽는 subtitles 필터. 윈도 경로의 드라이브 콜론·특수문자를 이스케이프한다.

    .ass/.ssa 는 파일에 스타일이 들어 있으므로 force_style 을 덮어씌우지 않는다.
    """
    s = f"subtitles=filename={_filter_path(srt_path)}"
    if os.path.splitext(srt_path)[1].lower() not in (".ass", ".ssa"):
        s += ":force_style=" + filter_escape(f"FontName={font_name},Outline=1,Shadow=0")
    return s


_SRT_TIME = re.compile(r"(\d+):(\d\d):(\d\d)[,.](\d{1,3})")
_ASS_TIME = re.compile(r"^(\d+):(\d\d):(\d\d)[.:](\d\d)$")


def _fmt_srt(t: float, sep: str) -> str:
    ms = int(round(max(t, 0.0) * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d}{sep}{ms % 1000:03d}"


def _fmt_ass(t: float) -> str:
    cs = int(round(max(t, 0.0) * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _shift_srt_text(text: str, offset: float, renumber: bool) -> str:
    """srt / vtt 블록의 시각을 offset 초만큼 빼서 돌려준다. offset 전에 끝나는 자막은 버린다."""
    out: list[str] = []
    n = 0
    for block in re.split(r"\n\s*\n", text.strip("\n")):
        lines = block.split("\n")
        idx = next((i for i, ln in enumerate(lines) if "-->" in ln), -1)
        if idx < 0:
            out.append(block)  # 헤더(WEBVTT 등) 또는 알 수 없는 블록은 그대로
            continue
        times = _SRT_TIME.findall(lines[idx])
        if len(times) < 2:
            continue
        sep = "," if "," in lines[idx] else "."
        a, b = [int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000 - offset
                for h, m, s, ms in times[:2]]
        if b <= 0:
            continue
        lines[idx] = f"{_fmt_srt(a, sep)} --> {_fmt_srt(b, sep)}"
        if renumber:
            n += 1
            if idx > 0 and lines[0].strip().isdigit():
                lines[0] = str(n)
        out.append("\n".join(lines))
    return "\n\n".join(out) + "\n"


def _shift_ass_text(text: str, offset: float) -> str:
    out: list[str] = []
    for line in text.split("\n"):
        if line.lower().startswith("dialogue:"):
            f = line.split(",", 9)
            if len(f) >= 3:
                ma, mb = _ASS_TIME.match(f[1].strip()), _ASS_TIME.match(f[2].strip())
                if ma and mb:
                    a, b = [int(h) * 3600 + int(m) * 60 + int(s) + int(cs) / 100 - offset
                            for h, m, s, cs in (ma.groups(), mb.groups())]
                    if b <= 0:
                        continue
                    f[1], f[2] = _fmt_ass(a), _fmt_ass(b)
                    line = ",".join(f)
        out.append(line)
    return "\n".join(out)


def shift_subtitles(path: str, offset: float, dst: str) -> str:
    """자막 시각을 offset 초만큼 앞당겨 dst 에 저장하고 dst 를 돌려준다.

    원본 영상 기준으로 만든 자막을 잘라낸 구간(-ss 입력 탐색 뒤 0 초부터 시작)에 맞추는 용도.
    srt / vtt / ass / ssa 를 지원하고, 그 외 형식은 그대로 복사한다.
    """
    ext = os.path.splitext(path)[1].lower()
    if ext not in (".srt", ".vtt", ".ass", ".ssa"):
        shutil.copyfile(path, dst)
        return dst
    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        text = f.read().replace("\r\n", "\n").replace("\r", "\n")
    if ext in (".ass", ".ssa"):
        text = _shift_ass_text(text, offset)
    else:
        text = _shift_srt_text(text, offset, renumber=(ext == ".srt"))
    with open(dst, "w", encoding="utf-8") as f:
        f.write(text)
    return dst


def vertical_blur_filter(width: int, height: int, out_w: int = 1080, out_h: int = 1920) -> str:
    """9:16 '블러' 레이아웃: 확대·크롭해 흐리게 만든 배경 위에 원본 전체 화면을 가로 out_w 에 맞춰 가운데 얹는다.

    -vf 와 filter_complex 양쪽에 쓸 수 있도록 입력·출력 라벨은 붙이지 않는다 (split 으로 시작, overlay 로 끝).
    """
    width, height = max(int(width), 2), max(int(height), 2)
    fw, fh = out_w, int(round(height * out_w / width)) // 2 * 2
    if fh > out_h:  # 세로로 긴 원본은 높이에 맞춘다
        fh, fw = out_h, int(round(width * out_h / height)) // 2 * 2
    fw, fh = max(fw, 2), max(fh, 2)
    bg = (f"scale={out_w}:{out_h}:force_original_aspect_ratio=increase:force_divisible_by=2,"
          f"crop={out_w}:{out_h},boxblur=luma_radius=24:luma_power=3:chroma_radius=12:chroma_power=3")
    return (f"split[bg][fg];[bg]{bg}[bgb];[fg]scale={fw}:{fh}:flags=lanczos[fgs];"
            f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2")


WATERMARK_POSITIONS = {"tl": "24:24", "tr": "W-w-24:24", "bl": "24:H-h-24", "br": "W-w-24:H-h-24"}


def watermark_filter(pos: str = "br", opacity: float = 0.8, video: str = "[v]", logo: str = "[1:v]",
                     out: str = "[vout]") -> str:
    """두 번째 입력(PNG)을 투명도 opacity 로 겹치는 filter_complex 조각. pos: tl | tr | bl | br (여백 24px)."""
    opacity = min(1.0, max(0.0, float(opacity)))
    xy = WATERMARK_POSITIONS.get(pos, WATERMARK_POSITIONS["br"])
    return f"{logo}format=rgba,colorchannelmixer=aa={opacity:.3f}[wm];{video}[wm]overlay={xy}{out}"


@dataclass
class RenderOptions:
    """재인코딩 출력에 얹는 효과: 세로 레이아웃 · 캡션 · 자막 · 워터마크 · 음량 정규화."""
    vertical: float | None = None    # 세로 9:16 크롭 위치 0~1 (None 이면 원본 비율)
    layout: str = "crop"             # 세로 출력: crop | blur
    caption: str = ""                # 영상에 굽는 글자
    subtitle_path: str = ""          # 굽는 자막 파일 (.srt/.ass …)
    watermark: str = ""              # PNG 경로
    watermark_pos: str = "br"        # tl | tr | bl | br
    watermark_opacity: float = 0.8
    normalize: bool = False

    @property
    def has_overlays(self) -> bool:
        """캡션 · 자막 · 워터마크 중 하나라도 있으면 (재인코딩 필요)."""
        return bool(self.caption.strip() or self.subtitle_path or self.watermark)


def render_filter_args(opts: RenderOptions, info: dict, subtitle_path: str | None = None) -> tuple[list[str], list[str]]:
    """(추가 -i 입력 인자, 스트림 매핑 + 필터 인자).

    적용 순서: 세로 크롭/블러 → 자막 → 캡션 → 워터마크. 워터마크가 있으면 filter_complex([v][1:v]overlay),
    없으면 -vf. subtitle_path 를 주면 (구간에 맞춰 옮긴) 자막 파일로 바꿔 쓴다.
    """
    w, h = int(info.get("width") or 1920), int(info.get("height") or 1080)
    out_h = h
    graph = ""
    chain: list[str] = []
    if opts.vertical is not None:
        out_h = 1920
        if opts.layout == "blur":
            graph = vertical_blur_filter(w, h)
        else:
            chain.append(vertical_crop_filter(w, h, opts.vertical))
    sub = opts.subtitle_path if subtitle_path is None else subtitle_path
    if sub:
        chain.append(subtitles_filter(sub))
    if opts.caption.strip():
        chain.append(drawtext_filter(opts.caption, size=max(int(out_h * 0.05), 12)))
    vf = graph + ("," if graph and chain else "") + ",".join(chain)
    if not opts.watermark:
        return [], stream_map_args("", keep_subs=False) + (["-vf", vf] if vf else [])
    label = "[0:v]"
    fc = ""
    if vf:
        fc = f"[0:v]{vf}[v];"
        label = "[v]"
    fc += watermark_filter(opts.watermark_pos, opts.watermark_opacity, label, "[1:v]", "[vout]")
    return ["-i", opts.watermark], ["-filter_complex", fc, "-map", "[vout]", "-map", "0:a?", "-dn", "-sn"]


# --------------------------------------------------------------------------- 인코더
_GPU_CACHE: dict[str, str | None] = {}


def detect_gpu_encoder(family: str = "h264") -> str | None:
    """사용 가능한 하드웨어 인코더 이름 (h264_nvenc / h264_qsv / h264_amf …) 또는 None."""
    if family in _GPU_CACHE:
        return _GPU_CACHE[family]
    found = None
    for enc in (f"{family}_nvenc", f"{family}_qsv", f"{family}_amf"):
        cmd = [find_tool("ffmpeg"), "-v", "error", "-f", "lavfi", "-i", "color=s=256x256:d=0.3:r=10",
               "-c:v", enc, "-f", "null", "-"]
        try:
            if _run(cmd, timeout=20).returncode == 0:
                found = enc
                break
        except subprocess.TimeoutExpired:
            pass
    _GPU_CACHE[family] = found
    return found


def video_encoder_args(family: str, gpu: str | None, crf: int = 18) -> list[str]:
    """family: h264 | hevc. gpu: detect_gpu_encoder 결과(없으면 None)."""
    if gpu:
        if gpu.endswith("nvenc"):
            return ["-c:v", gpu, "-preset", "p5", "-rc", "vbr", "-cq", str(crf + 4), "-b:v", "0"]
        if gpu.endswith("qsv"):
            return ["-c:v", gpu, "-global_quality", str(crf + 4), "-preset", "medium"]
        if gpu.endswith("amf"):
            return ["-c:v", gpu, "-quality", "balanced", "-rc", "cqp", "-qp_i", str(crf + 4), "-qp_p", str(crf + 4)]
    if family == "hevc":
        return ["-c:v", "libx265", "-preset", "fast", "-crf", str(crf + 4)]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf)]


AUDIO_ENCODERS = {
    "aac": ["-c:a", "aac", "-b:a", "192k"],
    "mp3": ["-c:a", "libmp3lame", "-b:a", "192k"],
    "opus": ["-c:a", "libopus", "-b:a", "128k"],
    "vorbis": ["-c:a", "libvorbis", "-q:a", "5"],
    "ac3": ["-c:a", "ac3", "-b:a", "384k"],
    "eac3": ["-c:a", "eac3", "-b:a", "384k"],
    "flac": ["-c:a", "flac"],
    "alac": ["-c:a", "alac"],
    "pcm_s16le": ["-c:a", "pcm_s16le"],
    "pcm_s24le": ["-c:a", "pcm_s24le"],
}

LOUDNORM = "loudnorm=I=-14:TP=-1.5:LRA=11"   # 유튜브·쇼츠 권장 -14 LUFS


def audio_normalize_args() -> list[str]:
    """음량 정규화(loudnorm) + aac 192k 인코딩 인자.

    loudnorm 은 내부적으로 192kHz 로 올려서 내보내므로 -ar 48000 으로 되돌린다 (안 하면 aac 가 96kHz 가 됨).
    """
    return ["-af", LOUDNORM, "-ar", "48000", "-c:a", "aac", "-b:a", "192k"]


MP4_LIKE = {".mp4", ".m4v", ".mov", ".m4a"}


def stream_map_args(dst: str, keep_subs: bool = True) -> list[str]:
    """복사/인코딩 때 가져갈 스트림: 첫 비디오 + 모든 오디오. 데이터 스트림은 버린다.

    자막은 mkv 같은 컨테이너에서만 유지한다 (mp4 는 srt/ass 를 못 담아 ffmpeg 가 실패함).
    """
    args = ["-map", "0:v:0", "-map", "0:a?", "-dn"]
    if keep_subs and os.path.splitext(dst)[1].lower() not in MP4_LIKE:
        args += ["-map", "0:s?", "-c:s", "copy"]
    else:
        args += ["-sn"]
    return args


# --------------------------------------------------------------------------- 실행기
class CutProcess:
    """진행률 콜백을 주는 ffmpeg 실행기. cancel() 로 중단."""

    def __init__(self, cmd: list[str], duration: float):
        self.cmd = cmd
        self.duration = max(duration, 0.01)
        self.proc: subprocess.Popen | None = None
        self._cancelled = False

    def cancel(self):
        self._cancelled = True
        if self.proc and self.proc.poll() is None:
            self.proc.kill()

    def run(self, on_progress: ProgressCb) -> tuple[bool, str]:
        # stderr 를 stdout 으로 합쳐 파이프 하나만 읽는다.
        # (따로 두면 Windows 의 4KB 파이프 버퍼가 차서 ffmpeg 가 멈춘다)
        self.proc = subprocess.Popen(
            self.cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", **_popen_kwargs(),
        )
        assert self.proc.stdout is not None
        progress_keys = ("out_time_us=", "out_time_ms=", "frame=", "fps=", "bitrate=", "total_size=",
                         "out_time=", "dup_frames=", "drop_frames=", "speed=", "progress=", "stream_")
        other: list[str] = []
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            if line.startswith("out_time_us="):
                try:
                    on_progress(min(int(line.split("=", 1)[1]) / 1e6 / self.duration, 1.0))
                except ValueError:
                    pass
            elif not line.startswith(progress_keys):
                other.append(line)
                if len(other) > 20:
                    other.pop(0)
        self.proc.wait()
        if self._cancelled:
            return False, tr("취소됨")
        return self.proc.returncode == 0, "\n".join(other[-5:])


class Cancelled(Exception):
    pass


class Cutter:
    """한 구간(또는 합치기)을 여러 ffmpeg 단계로 처리. 단계마다 진행률을 합산해 보고한다."""

    def __init__(self):
        self._current: CutProcess | None = None
        self._cancelled = False

    def cancel(self):
        self._cancelled = True
        if self._current:
            self._current.cancel()

    def _step(self, cmd: list[str], duration: float, cb: ProgressCb) -> str:
        if self._cancelled:
            raise Cancelled()
        self._current = CutProcess(cmd, duration)
        ok, msg = self._current.run(cb)
        self._current = None
        if self._cancelled:
            raise Cancelled()
        if not ok:
            LOG.error("ffmpeg 실패: %s\n  cmd: %s", msg, " ".join(cmd))
            raise RuntimeError(msg or tr("ffmpeg 실패"))
        return msg

    # ---- 기본 명령 ----
    @staticmethod
    def _base(src: str, start: float, dur: float) -> list[str]:
        return [find_tool("ffmpeg"), "-hide_banner", "-v", "error", "-y", "-nostats",
                "-ss", f"{start:.3f}", "-i", src, "-t", f"{dur:.3f}"]

    @staticmethod
    def _audio_args(audio: str, acodec: str, normalize: bool = False) -> list[str]:
        """audio: 'copy' | 'aac' | 'mp3'. normalize 면 loudnorm 을 거쳐 반드시 재인코딩."""
        if audio == "mp3":
            return ["-vn"] + (["-af", LOUDNORM, "-ar", "48000"] if normalize else []) + ["-c:a", "libmp3lame", "-q:a", "2"]
        if audio == "aac":
            if normalize:
                return ["-vn"] + audio_normalize_args()
            return ["-vn"] + (["-c:a", "copy"] if acodec == "aac" else ["-c:a", "aac", "-b:a", "192k"])
        return []

    def cut_copy(self, src: str, start: float, end: float, dst: str, cb: ProgressCb, audio_only: str = "",
                 normalize: bool = False):
        """재인코딩 없이 복사. normalize 면 비디오는 복사하고 오디오만 loudnorm → aac 로 다시 인코딩."""
        cmd = self._base(src, start, end - start)
        if audio_only:
            cmd += self._audio_args(audio_only, "", normalize) + ["-sn", "-dn"]
        else:
            cmd += stream_map_args(dst) + ["-c:v", "copy"] + (audio_normalize_args() if normalize else ["-c:a", "copy"])
        cmd += ["-avoid_negative_ts", "make_zero", "-progress", "pipe:1", dst]
        self._step(cmd, end - start, cb)

    def cut_audio(self, src: str, start: float, end: float, dst: str, fmt: str, acodec: str, cb: ProgressCb,
                  normalize: bool = False):
        # 입력 -ss 는 비디오 키프레임까지 당겨서 읽으므로 오디오 복사본에 그 앞부분(음수 ts)이 숨어 들어간다
        # (m4a 는 edit list 로 가려지지만 concat 때 드러남). 출력 -ss 0 으로 시작점 이전 패킷을 버린다.
        cmd = self._base(src, start, end - start) + ["-ss", "0"] + self._audio_args(fmt, acodec, normalize) + ["-sn", "-dn"]
        cmd += ["-progress", "pipe:1", dst]
        self._step(cmd, end - start, cb)

    def cut_encode(self, src: str, start: float, end: float, dst: str, cb: ProgressCb,
                   family: str = "h264", gpu: str | None = None, extra_video: list[str] | None = None,
                   audio_args: list[str] | None = None):
        """프레임 단위 정확 재인코딩. 오디오도 같이 재인코딩해야 시작점이 정확해진다.

        (-ss 입력 탐색은 비디오 키프레임 기준이라, 오디오를 copy 하면 앞쪽에 여분이 붙는다)
        """
        cmd = self._base(src, start, end - start) + stream_map_args(dst, keep_subs=False)
        cmd += video_encoder_args(family, gpu)
        cmd += extra_video or ["-pix_fmt", "yuv420p"]
        cmd += audio_args if audio_args is not None else AUDIO_ENCODERS["aac"]
        cmd += ["-movflags", "+faststart", "-avoid_negative_ts", "make_zero", "-progress", "pipe:1", dst]
        self._step(cmd, end - start, cb)

    def cut_vertical(self, src: str, start: float, end: float, dst: str, info: dict, frac: float,
                     cb: ProgressCb, gpu: str | None = None, normalize: bool = False):
        """세로 9:16 (1080x1920) 크롭 재인코딩 출력."""
        vf = vertical_crop_filter(info.get("width", 1920), info.get("height", 1080), frac)
        self.cut_encode(src, start, end, dst, cb, "h264", gpu, extra_video=["-vf", vf, "-pix_fmt", "yuv420p"],
                        audio_args=audio_normalize_args() if normalize else None)

    def cut_render(self, src: str, start: float, end: float, dst: str, info: dict, opts: RenderOptions,
                   cb: ProgressCb, gpu: str | None = None):
        """세로 레이아웃(크롭/블러) · 자막 · 캡션 · 워터마크를 얹어 h264 로 재인코딩.

        자막은 구간 시작에 맞춰 시각을 옮긴 임시 파일을 굽는다 (-ss 입력 탐색 뒤엔 0 초부터 시작하므로).
        """
        tmp = None
        sub = opts.subtitle_path
        try:
            if sub and start > 0.001:
                tmp = tempfile.mkdtemp(prefix="clipslicer_sub_")
                sub = shift_subtitles(sub, start, os.path.join(tmp, "sub" + os.path.splitext(sub)[1].lower()))
            inputs, fargs = render_filter_args(opts, info, sub)
            # -t 는 모든 입력 뒤에 둬야 출력 옵션이 된다 (워터마크 -i 앞에 오면 그 입력의 옵션이 됨)
            cmd = [find_tool("ffmpeg"), "-hide_banner", "-v", "error", "-y", "-nostats",
                   "-ss", f"{start:.3f}", "-i", src] + inputs + ["-t", f"{end - start:.3f}"] + fargs
            cmd += video_encoder_args("h264", gpu) + ["-pix_fmt", "yuv420p"]
            cmd += audio_normalize_args() if opts.normalize else AUDIO_ENCODERS["aac"]
            cmd += ["-movflags", "+faststart", "-avoid_negative_ts", "make_zero", "-progress", "pipe:1", dst]
            self._step(cmd, end - start, cb)
        finally:
            if tmp:
                shutil.rmtree(tmp, ignore_errors=True)

    def cut_smart(self, src: str, start: float, end: float, dst: str, info: dict, kfs: list[float],
                  cb: ProgressCb, gpu: str | None = None, normalize: bool = False) -> str:
        """시작~첫 키프레임만 재인코딩, 나머지는 복사, 둘을 이어 붙인다.

        반환: 실제로 쓴 방식 설명 ('copy' / 'smart' / 'encode'). normalize 는 마지막 단계에서 한 번만 적용.
        """
        vcodec = info.get("vcodec", "")
        fps = info.get("fps", 30.0) or 30.0
        frame = 1.0 / fps
        family = "h264" if vcodec == "h264" else "hevc" if vcodec in ("hevc", "h265") else None
        inside = [k for k in kfs if start - frame / 2 <= k <= end]
        if inside and inside[0] <= start + frame / 2:
            # 시작점이 이미 키프레임 → 그냥 복사
            self.cut_copy(src, start, end, dst, cb, normalize=normalize)
            return "copy"
        acodec = info.get("acodec", "")
        if info.get("has_audio"):
            audio_args = AUDIO_ENCODERS.get(acodec)
        else:
            audio_args = ["-an"]
        if family is None or not inside or audio_args is None:
            # 지원 안 하는 코덱이거나 구간 안에 키프레임이 없음 → 전체 재인코딩
            self.cut_encode(src, start, end, dst, cb, family or "h264", gpu,
                            audio_args=audio_normalize_args() if normalize else None)
            return "encode"
        k = inside[0]
        tmp = tempfile.mkdtemp(prefix="clipslicer_smart_")
        head = os.path.join(tmp, "head" + (os.path.splitext(dst)[1] or ".mp4"))
        try:
            head_len = k - start
            total = end - start
            self.encode_head(src, start, k, head, info, gpu, family, audio_args,
                             lambda p: cb(p * head_len / total))
            # 나머지는 원본에서 바로 읽어 붙인다 (임시 복사 없음 → 파일을 한 번만 쓴다)
            self.concat([head, (src, k, end)], dst, lambda p: cb((head_len + p * (end - k)) / total), total,
                        normalize=normalize)
            return "smart"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def encode_head(self, src: str, start: float, k: float, dst: str, info: dict, gpu: str | None,
                    family: str, audio_args: list[str], cb: ProgressCb):
        """스마트 컷의 앞 조각(시작~키프레임) 재인코딩. 원본과 같은 해상도·fps·픽셀 포맷·프로파일로."""
        fps = info.get("fps", 30.0) or 30.0
        extra = ["-pix_fmt", info.get("pix_fmt") or "yuv420p",
                 "-s", f"{info['width']}x{info['height']}", "-r", f"{fps:.6f}"]
        if family == "h264" and info.get("profile"):
            prof = info["profile"].lower().replace(" ", "")
            if prof in ("baseline", "main", "high"):
                extra += ["-profile:v", prof]
        self.cut_encode(src, start, k, dst, cb, family, gpu, extra_video=extra, audio_args=audio_args)

    @staticmethod
    def smart_plan(info: dict, kfs: list[float], start: float, end: float):
        """스마트 컷 계획: (family, audio_args, k) 또는 None(전체 재인코딩 필요). k 가 None 이면 그냥 복사."""
        vcodec = info.get("vcodec", "")
        fps = info.get("fps", 30.0) or 30.0
        frame = 1.0 / fps
        family = "h264" if vcodec == "h264" else "hevc" if vcodec in ("hevc", "h265") else None
        inside = [k for k in kfs if start - frame / 2 <= k <= end]
        if inside and inside[0] <= start + frame / 2:
            return family, None, None
        audio_args = AUDIO_ENCODERS.get(info.get("acodec", "")) if info.get("has_audio") else ["-an"]
        if family is None or not inside or audio_args is None:
            return None
        return family, audio_args, inside[0]

    def concat(self, parts: list, dst: str, cb: ProgressCb, total: float = 0.0, normalize: bool = False):
        """같은 코덱의 조각들을 재인코딩 없이 이어 붙인다 (concat demuxer).

        parts 항목: 파일 경로 문자열, 또는 (경로, inpoint, outpoint) 튜플.
        튜플이면 원본에서 그 구간만 읽어 붙이므로 임시 파일을 만들 필요가 없다.
        (inpoint 가 키프레임이 아니면 앞 키프레임부터 들어간다 — '빠르게' 모드와 같은 동작)
        normalize 면 비디오는 복사하고 오디오만 loudnorm → aac (합치기의 마지막 단계에서 한 번만).
        """
        lst = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8")
        try:
            est = 0.0
            for p in parts:
                if isinstance(p, tuple):
                    path, a, b = p
                    lst.write(f"file '{_concat_escape(path)}'\ninpoint {a:.3f}\noutpoint {b:.3f}\n")
                    est += b - a
                else:
                    lst.write(f"file '{_concat_escape(p)}'\n")
                    try:
                        est += probe(p)["duration"]
                    except Exception:
                        pass
            lst.close()
            cmd = [find_tool("ffmpeg"), "-hide_banner", "-v", "error", "-y", "-nostats",
                   "-f", "concat", "-safe", "0", "-i", lst.name]
            ext = os.path.splitext(dst)[1].lower()
            if ext in (".m4a", ".mp3"):
                # 오디오만 합치기: 비디오 스트림이 없으므로 -map 0:v:0 을 쓰면 ffmpeg 가 실패한다. 컨테이너에 맞는 코덱으로.
                cmd += ["-vn", "-map", "0:a", "-dn", "-sn"]
                if not normalize:
                    cmd += ["-c:a", "copy"]
                elif ext == ".mp3":
                    cmd += ["-af", LOUDNORM, "-ar", "48000", "-c:a", "libmp3lame", "-q:a", "2"]
                else:
                    cmd += audio_normalize_args()
            else:
                cmd += stream_map_args(dst) + ["-c:v", "copy"]
                cmd += audio_normalize_args() if normalize else ["-c:a", "copy"]
            cmd += ["-avoid_negative_ts", "make_zero", "-movflags", "+faststart", "-progress", "pipe:1", dst]
            self._step(cmd, max(total or est, 0.1), cb)
        finally:
            try:
                os.remove(lst.name)
            except OSError:
                pass

    def concat_render(self, files: list[str], dst: str, cb: ProgressCb, size: tuple[int, int] | None = None,
                      fps: float | None = None, gpu: str | None = None, normalize: bool = False):
        """규격이 다른 영상들(인트로 · 본편 · 아웃트로)을 같은 크기·fps 로 맞춰 재인코딩하며 이어 붙인다 (concat 필터).

        비디오는 size 에 맞춰 scale + pad(가운데, sar=1), 오디오는 48kHz 스테레오 aac. 오디오 없는 파일엔 무음을 넣는다.
        size / fps 가 없으면 첫 번째 비디오 파일 기준.
        """
        infos = [probe(f) for f in files]
        first = next((i for i in infos if i["width"]), infos[0])
        w, h = size or (first["width"], first["height"])
        fps = fps or first["fps"] or 30.0
        any_audio = any(i["has_audio"] for i in infos)
        chains: list[str] = []
        streams: list[str] = []
        for n, i in enumerate(infos):
            chains.append(f"[{n}:v]scale={w}:{h}:force_original_aspect_ratio=decrease:force_divisible_by=2:flags=lanczos,"
                          f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps:.6f},format=yuv420p[v{n}]")
            streams.append(f"[v{n}]")
            if any_audio:
                src_a = f"[{n}:a]aresample=48000" if i["has_audio"] else \
                    f"aevalsrc=0|0:s=48000:d={max(i['duration'], 0.1):.3f}"
                chains.append(f"{src_a},aformat=sample_fmts=fltp:channel_layouts=stereo[a{n}]")
                streams.append(f"[a{n}]")
        graph = ";".join(chains) + f";{''.join(streams)}concat=n={len(files)}:v=1:a={1 if any_audio else 0}[v]"
        audio_label = ""
        if any_audio:
            graph += "[a]"
            audio_label = "[a]"
            if normalize:
                graph += f";[a]{LOUDNORM},aresample=48000[aout]"
                audio_label = "[aout]"
        cmd = [find_tool("ffmpeg"), "-hide_banner", "-v", "error", "-y", "-nostats"]
        for f in files:
            cmd += ["-i", f]
        cmd += ["-filter_complex", graph, "-map", "[v]"] + (["-map", audio_label] if any_audio else []) + ["-dn", "-sn"]
        cmd += video_encoder_args("h264", gpu) + ["-pix_fmt", "yuv420p"]
        if any_audio:
            cmd += AUDIO_ENCODERS["aac"]
        cmd += ["-movflags", "+faststart", "-progress", "pipe:1", dst]
        self._step(cmd, sum(i["duration"] for i in infos), cb)


def _concat_escape(path: str) -> str:
    return path.replace("\\", "/").replace("'", "'\\''")
