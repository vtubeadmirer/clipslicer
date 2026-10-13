"""UI 문자열 번역. 코드에는 한국어를 그대로 두고, tr("...") 가 현재 언어 사전에서 찾아 바꾼다.

언어: 'ko' | 'en' | 'auto'(시스템 로캘). 사전에 없는 문자열은 한국어 그대로 보여 준다.
"""
from __future__ import annotations

import locale
import logging
import os

LOG = logging.getLogger("clipslicer")
LANGUAGES = [("auto", "시스템 설정 따라가기 (Auto)"), ("ko", "한국어"), ("en", "English")]

_lang = "ko"
_table: dict[str, str] = {}
_missing: set[str] = set()


def system_language() -> str:
    try:
        loc = locale.getlocale()[0] or ""
    except Exception:
        loc = ""
    loc = (os.environ.get("LANG") or loc or "").lower()
    return "ko" if loc.startswith(("ko", "korean")) else "en"


def set_language(code: str):
    """'auto' 는 시스템 언어로. 사전 로드."""
    global _lang, _table
    code = (code or "auto").lower()
    if code == "auto":
        code = system_language()
    _lang = "en" if code == "en" else "ko"
    if _lang == "en":
        from .i18n_en import EN
        _table = EN
    else:
        _table = {}
    LOG.info("UI 언어: %s", _lang)


def language() -> str:
    return _lang


def tr(text: str) -> str:
    if not _table:
        return text
    out = _table.get(text)
    if out is None:
        if text not in _missing:
            _missing.add(text)
            LOG.debug("번역 없음: %r", text)
        return text
    return out


def missing() -> set[str]:
    return set(_missing)
