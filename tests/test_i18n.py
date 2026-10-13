"""영문 사전이 모든 UI 문자열을 덮고, 자리표시자가 일치하는지."""
import os
import re
import string
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import i18n  # noqa: E402
from app.i18n_en import EN  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_PREFIX = ("\n# ClipSlicer 업데이트 교체 스크립트",)  # 번역 대상이 아닌 템플릿


def _keys():
    with open(os.path.join(ROOT, "tools", "i18n_keys.txt"), encoding="utf-8") as f:
        return [line.rstrip("\n").replace("\\n", "\n") for line in f if line.strip()]


def _placeholders(s: str):
    out = set()
    for _lit, field, _spec, _conv in string.Formatter().parse(s.replace("%p%", "")):
        if field is not None:
            out.add(field)
    return out


def test_all_keys_translated():
    missing = [k for k in _keys() if k not in EN and not k.startswith(SKIP_PREFIX)]
    assert not missing, f"번역 없음 {len(missing)}개: {missing[:5]}"


def test_placeholders_match():
    bad = []
    for k, v in EN.items():
        try:
            pk, pv = _placeholders(k), _placeholders(v)
        except ValueError:
            continue  # 중괄호가 포맷용이 아닌 문자열 (HTML/CSS)
        if pk != pv:
            bad.append((k[:40], pk, pv))
    assert not bad, bad[:5]


def test_no_hangul_in_translations():
    hangul = re.compile(r"[가-힣]")
    leaks = [k for k, v in EN.items() if hangul.search(v) and k not in ("한국어",)]
    assert not leaks, leaks[:5]


def test_tr_switch_and_fallback():
    i18n.set_language("en")
    assert i18n.tr("취소") == "Cancel"
    assert i18n.tr("이건 사전에 없음") == "이건 사전에 없음"
    assert i18n.tr("{0}개 파일이 이미 있습니다.").format(3) == "3 files already exist."
    i18n.set_language("ko")
    assert i18n.tr("취소") == "취소"
    assert i18n.language() == "ko"
    assert i18n.system_language() in ("ko", "en")
