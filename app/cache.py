"""분석 결과(썸네일·파형·키프레임) 캐시. 영상 옆 <영상>.clipslicer.cache, 못 쓰면 %LOCALAPPDATA%."""
from __future__ import annotations

import hashlib
import logging
import os
import pickle

LOG = logging.getLogger("clipslicer")
SUFFIX = ".clipslicer.cache"
VERSION = 2


def _fallback_dir() -> str:
    d = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "ClipSlicer", "cache")
    os.makedirs(d, exist_ok=True)
    return d


def cache_paths(video: str) -> list[str]:
    h = hashlib.sha1(os.path.abspath(video).encode("utf-8", "replace")).hexdigest()[:16]
    return [video + SUFFIX, os.path.join(_fallback_dir(), h + SUFFIX)]


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
    for p in cache_paths(video):
        try:
            tmp = p + ".tmp"
            with open(tmp, "wb") as f:
                pickle.dump(data, f, protocol=4)
            os.replace(tmp, p)
            return True
        except OSError:
            continue
    return False


def remove(video: str):
    for p in cache_paths(video):
        try:
            os.remove(p)
        except OSError:
            pass
