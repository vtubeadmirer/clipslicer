"""분석 결과(썸네일·파형·키프레임) 캐시.

%LOCALAPPDATA%\\ClipSlicer\\cache 한곳에 모은다 (영상 폴더에 파일을 만들지 않음). 0.9.10 까지 영상 옆에 만들던
<영상>.clipslicer.cache 는 읽을 수 있으면 한 번 쓰고, 새 위치에 저장한 뒤 지운다. 전체가 MAX_BYTES 를 넘으면
오래 안 쓴 것부터 지운다.
"""
from __future__ import annotations

import hashlib
import logging
import os
import pickle

LOG = logging.getLogger("clipslicer")
SUFFIX = ".clipslicer.cache"
VERSION = 2
MAX_BYTES = 2 * 1024 ** 3      # 캐시 폴더 상한 (넘으면 오래 안 쓴 것부터 정리)
TARGET_BYTES = int(MAX_BYTES * 0.75)


def cache_dir() -> str:
    from .paths import data_dir
    return data_dir("cache")


def central_path(video: str) -> str:
    h = hashlib.sha1(os.path.abspath(video).encode("utf-8", "replace")).hexdigest()[:16]
    return os.path.join(cache_dir(), h + SUFFIX)


def legacy_path(video: str) -> str:
    return video + SUFFIX


def cache_paths(video: str) -> list[str]:
    """읽는 순서: 새 위치 → 예전 영상 옆."""
    return [central_path(video), legacy_path(video)]


def _stamp(video: str) -> tuple[int, int]:
    st = os.stat(video)
    return int(st.st_size), int(st.st_mtime)


def load(video: str) -> dict | None:
    try:
        stamp = _stamp(video)
    except OSError:
        return None
    for p in cache_paths(video):
        if not os.path.isfile(p):
            continue
        try:
            with open(p, "rb") as f:
                data = pickle.load(f)
            if data.get("version") == VERSION and tuple(data.get("stamp", ())) == stamp:
                if p == central_path(video):
                    try:
                        os.utime(p)   # 최근에 쓴 캐시 표시 (정리할 때 오래된 것부터)
                    except OSError:
                        pass
                return data
        except Exception:
            LOG.warning("캐시 읽기 실패: %s", p, exc_info=True)
    return None


def save(video: str, thumbs: list, waveform, keyframes: list) -> bool:
    try:
        data = {"version": VERSION, "stamp": _stamp(video), "thumbs": thumbs,
                "waveform": waveform, "keyframes": keyframes}
    except OSError:
        return False
    p = central_path(video)
    tmp = p + ".tmp"
    try:
        with open(tmp, "wb") as f:
            pickle.dump(data, f, protocol=4)
        os.replace(tmp, p)
    except OSError:
        LOG.warning("캐시 저장 실패: %s", p, exc_info=True)
        return False
    try:
        os.remove(legacy_path(video))   # 예전 위치(영상 옆) 캐시는 정리
    except OSError:
        pass
    prune()
    return True


def remove(video: str):
    for p in cache_paths(video):
        try:
            os.remove(p)
        except OSError:
            pass


def prune(max_bytes: int = MAX_BYTES, target_bytes: int = TARGET_BYTES) -> int:
    """캐시 폴더가 max_bytes 를 넘으면 오래 안 쓴 것부터 target_bytes 아래로 지운다. 지운 개수."""
    try:
        files = [os.path.join(cache_dir(), n) for n in os.listdir(cache_dir()) if n.endswith(SUFFIX)]
        entries = sorted(((os.path.getmtime(f), os.path.getsize(f), f) for f in files))
    except OSError:
        return 0
    total = sum(s for _, s, _ in entries)
    if total <= max_bytes:
        return 0
    n = 0
    for _, size, f in entries:
        if total <= target_bytes:
            break
        try:
            os.remove(f)
            total -= size
            n += 1
        except OSError:
            pass
    LOG.info("분석 캐시 정리: %d개 삭제", n)
    return n
