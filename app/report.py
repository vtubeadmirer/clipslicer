"""문제 보고용 정보: 버전 · 윈도우 · 폴더 · 최근 로그 (토큰 · 쿠키 · 인증 값은 가림)."""
from __future__ import annotations

import os
import platform
import re
import sys

SECRET_PATTERNS = [
    (re.compile(r"(?i)\b(authorization|cookie|set-cookie|x-[\w-]*token)\s*[:=]\s*[^\r\n,]+"), r"\1: ***"),
    (re.compile(r"(?i)([?&](?:token|sig|signature|key|auth|session|policy|expires|hdnts|_lsu_sa_)=)[^&\s\"']+"), r"\1***"),
    (re.compile(r"(?i)(bearer\s+)[\w\-.~+/]+=*"), r"\1***"),
    (re.compile(r"(?i)(\"?(?:access_token|refresh_token|client_secret)\"?\s*[:=]\s*\"?)[^\"\s,}]+"), r"\1***"),
]


def redact(text: str) -> str:
    for pat, rep in SECRET_PATTERNS:
        text = pat.sub(rep, text)
    return text


def tail_lines(path: str, n: int = 120) -> list[str]:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read().splitlines()[-n:]
    except OSError:
        return []


def build_report(log_file: str, extra: dict | None = None, lines: int = 120) -> str:
    from . import __version__
    from .paths import base_dir
    head = [
        f"ClipSlicer {__version__} ({'exe' if getattr(sys, 'frozen', False) else 'source'})",
        f"Windows: {platform.platform()}",
        f"Python: {platform.python_version()}",
        f"폴더: {base_dir()}",
    ]
    for k, v in (extra or {}).items():
        head.append(f"{k}: {v}")
    body = tail_lines(log_file, lines)
    return redact("\n".join(head + ["", f"--- 최근 로그 {len(body)}줄 ({os.path.basename(log_file)}) ---"] + body)) + "\n"
