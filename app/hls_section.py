"""HLS(m3u8) 재생 목록에서 일부 구간의 세그먼트만 받아 파일로 만든다.

yt-dlp 의 내장 HLS 다운로더는 구간 다운로드를 지원하지 않고, ffmpeg 다운로더는 서명 토큰이 붙은
세그먼트 주소(네이버 VOD)를 처리하지 못한다. 그래서 재생 목록을 직접 읽어 필요한 세그먼트만 받는다.
"""
from __future__ import annotations

from .i18n import tr
import os
import re
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ClipSlicer"


def fetch(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def parse_playlist(text: str, base_url: str, extra_query: str = "") -> list[tuple[float, float, str]]:
    """(시작시각, 길이, 세그먼트 URL) 목록. extra_query 가 있으면 각 세그먼트 URL 에 붙인다."""
    segs = []
    t = 0.0
    dur = None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#EXTINF:"):
            try:
                dur = float(line[8:].split(",")[0])
            except ValueError:
                dur = None
        elif not line.startswith("#"):
            if dur is None:
                continue
            url = urllib.parse.urljoin(base_url, line)
            if extra_query and extra_query not in url:
                url += ("&" if "?" in url else "?") + extra_query
            segs.append((t, dur, url))
            t += dur
            dur = None
    return segs


def select_segments(segs: list[tuple[float, float, str]], start: float, end: float) -> list[tuple[float, float, str]]:
    """[start, end] 와 겹치는 세그먼트만."""
    return [s for s in segs if s[0] + s[1] > start and s[0] < end]


def is_mpegts(data: bytes) -> bool:
    return len(data) > 188 and data[0] == 0x47 and data[188] == 0x47


def download_section(playlist_url: str, start: float, end: float, dst: str, extra_query: str = "",
                     on_progress: Callable[[float, str], None] | None = None, cancel: Callable[[], bool] | None = None,
                     workers: int = 4) -> tuple[float, float]:
    """구간과 겹치는 세그먼트를 순서대로 이어 붙여 dst 에 저장. (실제 시작 시각, 실제 끝 시각) 반환.

    마스터 재생 목록이 들어오면 첫 번째(최고 대역) 변형을 따라간다.
    """
    text = fetch(playlist_url).decode("utf-8", "replace")
    if "#EXT-X-STREAM-INF" in text:
        variants = [l.strip() for l in text.splitlines() if l.strip() and not l.startswith("#")]
        if not variants:
            raise RuntimeError(tr("재생 목록에 변형이 없습니다"))
        playlist_url = urllib.parse.urljoin(playlist_url, variants[0])
        if extra_query and extra_query not in playlist_url:
            playlist_url += ("&" if "?" in playlist_url else "?") + extra_query
        text = fetch(playlist_url).decode("utf-8", "replace")
    segs = parse_playlist(text, playlist_url, extra_query)
    if not segs:
        raise RuntimeError(tr("세그먼트를 찾지 못했습니다"))
    if re.search(r"#EXT-X-KEY:METHOD=(?!NONE)", text):
        raise RuntimeError(tr("암호화된 HLS 는 구간 다운로드를 지원하지 않습니다"))
    picked = select_segments(segs, start, end)
    if not picked:
        raise RuntimeError(tr("요청한 구간이 영상 길이 밖입니다"))
    total = len(picked)
    done = 0
    buffers: dict[int, bytes] = {}

    def get(i: int):
        if cancel and cancel():
            return i, b""
        last_err = None
        for _ in range(3):
            try:
                return i, fetch(picked[i][2])
            except Exception as ex:  # 재시도
                last_err = ex
        raise RuntimeError(tr("세그먼트 {0} 다운로드 실패: {1}").format(i, last_err))

    with open(dst, "wb") as out, ThreadPoolExecutor(max_workers=workers) as pool:
        next_write = 0
        for i, data in pool.map(get, range(total)):
            if cancel and cancel():
                raise RuntimeError(tr("취소됨"))
            buffers[i] = data
            while next_write in buffers:
                out.write(buffers.pop(next_write))
                next_write += 1
            done += 1
            if on_progress:
                on_progress(done / total, tr("세그먼트 {0}/{1}").format(done, total))
    return picked[0][0], picked[-1][0] + picked[-1][1]
