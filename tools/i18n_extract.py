"""tr("...") 문자열을 모아 tools/i18n_keys.txt 를 다시 쓴다.

app/*.py 와 main.py 를 tokenize 로 훑어 tr( 바로 뒤에 오는 문자열 리터럴(암시적 이어붙이기 포함, "..." '...' 세 따옴표 모두)을
ast.literal_eval 로 풀어 키로 삼는다. tr(변수) 처럼 리터럴이 아니면 건너뛴다. 한 줄에 키 하나, 줄바꿈은 \\n 으로 적는다
(tests/test_i18n.py 가 같은 규칙으로 읽는다).

사용: python tools/i18n_extract.py [--check]
  --check : 파일을 쓰지 않고, app/i18n_en.py 의 EN 에 없는 키만 출력한다 (있으면 종료 코드 1).
"""
from __future__ import annotations

import ast
import io
import os
import sys
import tokenize

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEYS_FILE = os.path.join(ROOT, "tools", "i18n_keys.txt")


def source_files() -> list[str]:
    files = [os.path.join(ROOT, "main.py")]
    app_dir = os.path.join(ROOT, "app")
    for name in sorted(os.listdir(app_dir)):
        if name.endswith(".py") and name not in ("i18n.py", "i18n_en.py"):
            files.append(os.path.join(app_dir, name))
    return [f for f in files if os.path.isfile(f)]


def extract_from_source(src: str) -> list[str]:
    """소스 한 파일에서 tr(리터럴) 의 리터럴 값을 나온 순서대로."""
    out: list[str] = []
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except (tokenize.TokenError, SyntaxError):
        return out
    i = 0
    n = len(toks)
    while i < n:
        t = toks[i]
        if t.type == tokenize.NAME and t.string == "tr" and i + 1 < n and toks[i + 1].type == tokenize.OP and toks[i + 1].string == "(":
            # tr 이 속성(obj.tr)이면 건너뛴다
            if i > 0 and toks[i - 1].type == tokenize.OP and toks[i - 1].string == ".":
                i += 1
                continue
            j = i + 2
            parts: list[str] = []
            while j < n:
                tj = toks[j]
                if tj.type == tokenize.STRING:
                    parts.append(tj.string)
                    j += 1
                elif tj.type in (tokenize.NL, tokenize.NEWLINE, tokenize.COMMENT, tokenize.INDENT, tokenize.DEDENT):
                    j += 1
                else:
                    break
            if parts and j < n and toks[j].type == tokenize.OP and toks[j].string == ")":
                try:
                    value = ast.literal_eval(" ".join(parts))
                except (ValueError, SyntaxError):
                    value = None
                if isinstance(value, str) and value:
                    out.append(value)
            i = j
            continue
        i += 1
    return out


def extract_all() -> list[str]:
    seen: set[str] = set()
    keys: list[str] = []
    for path in source_files():
        with open(path, encoding="utf-8") as f:
            src = f.read()
        for k in extract_from_source(src):
            if k not in seen:
                seen.add(k)
                keys.append(k)
    return keys


def encode(key: str) -> str:
    return key.replace("\n", "\\n")


def write_keys(keys: list[str]):
    with open(KEYS_FILE, "w", encoding="utf-8", newline="\n") as f:
        for k in keys:
            f.write(encode(k) + "\n")


def main(argv: list[str]) -> int:
    keys = extract_all()
    ambiguous = [k for k in keys if "\\n" in k]
    for k in ambiguous:
        print(f"경고: 역슬래시+n 이 들어 있어 키 파일에서 줄바꿈과 구분되지 않음: {k!r}", file=sys.stderr)
    if "--check" in argv:
        sys.path.insert(0, ROOT)
        from app.i18n_en import EN
        missing = [k for k in keys if k not in EN]
        for k in missing:
            print(encode(k))
        print(f"-- 키 {len(keys)}개, 번역 없음 {len(missing)}개", file=sys.stderr)
        return 1 if missing else 0
    write_keys(keys)
    print(f"{len(keys)}개 키 → {os.path.relpath(KEYS_FILE, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
