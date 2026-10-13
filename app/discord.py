"""디스코드 웹훅으로 잘린 파일 보내기.

외부 라이브러리 없이 urllib 로 multipart/form-data 를 직접 만든다. 웹훅은 디스코드 채널 설정 ▸ 연동 ▸ 웹훅에서 만든다.
설정 키: discord_webhook / discord_limit_mb / discord_template
"""
from __future__ import annotations

from .i18n import tr
import io
import json
import logging
import mimetypes
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit, QComboBox, QPlainTextEdit, QPushButton,
    QDialogButtonBox, QMessageBox,
)

from .youtube import fill_template

LOG = logging.getLogger("clipslicer")

WEBHOOK_PREFIXES = ("https://discord.com/api/webhooks/", "https://discordapp.com/api/webhooks/")
LIMITS_MB = [10, 25, 50, 100]          # 무료 / (예전 무료) / 부스트 2단계·니트로 베이직 / 부스트 3단계
DEFAULT_LIMIT_MB = 10
DEFAULT_USERNAME = "ClipSlicer"
DEFAULT_TEMPLATE = "{title}"
MAX_CONTENT = 2000                     # 디스코드 메시지 글자 수 한도
KEY_WEBHOOK, KEY_LIMIT, KEY_TEMPLATE = "discord_webhook", "discord_limit_mb", "discord_template"


class DiscordError(Exception):
    pass


# --------------------------------------------------------------------------- 검증 / 설정
def is_webhook_url(url: str) -> bool:
    u = (url or "").strip()
    return any(u.startswith(p) and len(u) > len(p) for p in WEBHOOK_PREFIXES)


def _check_url(url: str) -> str:
    if not is_webhook_url(url):
        raise DiscordError(tr("디스코드 웹훅 URL 이 아닙니다 (https://discord.com/api/webhooks/… 형식이어야 합니다)"))
    return url.strip()


def config(settings) -> dict:
    """settings → {'webhook', 'limit_mb', 'template'}."""
    try:
        limit = int(settings.value(KEY_LIMIT, DEFAULT_LIMIT_MB) or DEFAULT_LIMIT_MB)
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT_MB
    return {"webhook": str(settings.value(KEY_WEBHOOK, "") or "").strip(),
            "limit_mb": limit if limit > 0 else DEFAULT_LIMIT_MB,
            "template": str(settings.value(KEY_TEMPLATE, DEFAULT_TEMPLATE) or DEFAULT_TEMPLATE)}


def split_by_limit(paths: list[str], limit_mb: float) -> tuple[list[str], list[tuple[str, int]]]:
    """(보낼 수 있는 파일 목록, [(너무 큰 파일, 크기)]). 없는 파일은 둘 다에서 뺀다."""
    limit = int(limit_mb * 1024 * 1024)
    ok, big = [], []
    for p in paths:
        try:
            size = os.path.getsize(p)
        except OSError:
            continue
        (ok if size <= limit else big).append(p if size <= limit else (p, size))
    return ok, big


# --------------------------------------------------------------------------- multipart
def build_multipart(fields: dict[str, str], files: list[tuple[str, str, bytes, str]],
                    boundary: str | None = None) -> tuple[bytes, str]:
    """multipart/form-data 본문. files: (필드명, 파일명, 바이트, MIME). (body, Content-Type 헤더값) 반환."""
    boundary = boundary or ("----ClipSlicer" + secrets.token_hex(16))
    b = boundary.encode("ascii")
    out = bytearray()
    for name, value in fields.items():
        out += b"--" + b + b"\r\n"
        out += f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8")
        out += str(value).encode("utf-8") + b"\r\n"
    for name, filename, data, mime in files:
        fn = "".join("_" if ch in '"\\\r\n' else ch for ch in filename) or "file"
        out += b"--" + b + b"\r\n"
        out += f'Content-Disposition: form-data; name="{name}"; filename="{fn}"\r\n'.encode("utf-8")
        out += f"Content-Type: {mime or 'application/octet-stream'}\r\n\r\n".encode("utf-8")
        out += bytes(data) + b"\r\n"
    out += b"--" + b + b"--\r\n"
    return bytes(out), "multipart/form-data; boundary=" + boundary


class _ProgressBody:
    """urllib 에 넘기는 파일 객체. http.client 가 8 KB 씩 읽어 보내는 동안 진행률을 알리고 취소를 확인한다."""

    def __init__(self, data: bytes, on_progress: Callable[[float], None] | None, cancel: Callable[[], bool] | None):
        self._buf = io.BytesIO(data)
        self._total = len(data)
        self._cb, self._cancel = on_progress, cancel

    def __len__(self) -> int:
        return self._total

    def read(self, n: int = -1) -> bytes:
        if self._cancel and self._cancel():
            raise DiscordError(tr("취소됨"))
        chunk = self._buf.read(n)
        if self._cb and self._total:
            self._cb(min(self._buf.tell() / self._total, 1.0))
        return chunk


def _error_text(status: int, body: bytes) -> str:
    msg = ""
    code = 0
    try:
        j = json.loads(body.decode("utf-8", "replace"))
        msg = str(j.get("message", ""))
        code = int(j.get("code", 0) or 0)
    except Exception:
        msg = body[:200].decode("utf-8", "replace")
    if status in (401, 403, 404):
        return tr("웹훅 URL 이 잘못되었거나 삭제되었습니다. 설정 ▸ 디스코드 웹훅… 에서 다시 등록하세요.")
    if status == 413 or code == 40005:
        return tr("파일이 서버 한도보다 큽니다. 설정 ▸ 디스코드 웹훅… 에서 크기 한도를 낮추세요.")
    return tr("디스코드 오류 {0}: {1}").format(status, msg or "-")


def _post(url: str, body: bytes, content_type: str, on_progress=None, cancel=None, timeout: int = 300) -> dict:
    """wait=true 로 보내서 만들어진 메시지 JSON 을 돌려준다. 429 는 잠시 기다렸다가 다시 보낸다."""
    full = url + ("&" if "?" in url else "?") + "wait=true"
    for _attempt in range(4):
        req = urllib.request.Request(full, data=_ProgressBody(body, on_progress, cancel), method="POST", headers={
            "Content-Type": content_type, "Content-Length": str(len(body)), "User-Agent": "ClipSlicer"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                status, resp = r.status, r.read()
        except urllib.error.HTTPError as e:
            status, resp = e.code, e.read()
        except (urllib.error.URLError, OSError, TimeoutError) as ex:
            raise DiscordError(tr("네트워크 오류: {0}").format(getattr(ex, "reason", ex)))
        if status == 429:
            try:
                wait = float(json.loads(resp.decode("utf-8", "replace")).get("retry_after", 2))
            except Exception:
                wait = 2.0
            LOG.info("디스코드 429, %.1f초 대기", wait)
            time.sleep(min(max(wait, 0.5), 30))
            continue
        if status in (200, 201, 204):
            try:
                return json.loads(resp) if resp else {}
            except ValueError:
                return {}
        raise DiscordError(_error_text(status, resp))
    raise DiscordError(tr("디스코드 요청이 너무 잦습니다 (429). 잠시 뒤 다시 시도하세요."))


# --------------------------------------------------------------------------- 보내기
def send_file(webhook_url: str, path: str, content: str = "", username: str = DEFAULT_USERNAME,
              on_progress: Callable[[float], None] | None = None, limit_mb: float = DEFAULT_LIMIT_MB,
              cancel: Callable[[], bool] | None = None, timeout: int = 300) -> dict:
    """파일 하나를 웹훅으로 올린다. limit_mb(서버 등급별 10/25/50/100) 를 넘으면 보내지 않고 DiscordError.

    만들어진 메시지 JSON(id, channel_id, attachments[...]) 을 돌려준다.
    """
    url = _check_url(webhook_url)
    name = os.path.basename(path)
    size = os.path.getsize(path)
    if size <= 0:
        raise DiscordError(tr("{0}: 비어 있는 파일입니다").format(name))
    if size > int(limit_mb * 1024 * 1024):
        raise DiscordError(tr("{0}: {1:.1f} MB — 서버 한도 {2} MB 를 넘어 보낼 수 없습니다").format(name, size / 1024 ** 2, limit_mb))
    with open(path, "rb") as f:
        data = f.read()
    payload = {"content": (content or "")[:MAX_CONTENT], "username": username or DEFAULT_USERNAME}
    body, ctype = build_multipart({"payload_json": json.dumps(payload, ensure_ascii=False)},
                                  [("files[0]", name, data, mimetypes.guess_type(path)[0] or "application/octet-stream")])
    LOG.info("디스코드 전송: %s (%.1f MB)", name, size / 1024 ** 2)
    return _post(url, body, ctype, on_progress, cancel, timeout)


def test_webhook(webhook_url: str, username: str = DEFAULT_USERNAME) -> dict:
    """짧은 글 하나를 보내서 웹훅이 살아 있는지 확인. 메시지 JSON 반환."""
    url = _check_url(webhook_url)
    body = json.dumps({"content": tr("ClipSlicer 웹훅 연결 테스트 ✅"), "username": username or DEFAULT_USERNAME},
                      ensure_ascii=False).encode("utf-8")
    return _post(url, body, "application/json", timeout=30)


def attachment_url(message: dict) -> str:
    att = (message or {}).get("attachments") or []
    return str(att[0].get("url", "")) if att and isinstance(att[0], dict) else ""


class DiscordWorker(QThread):
    """items: [(파일 경로, {'title', 'source'})] 를 순서대로 보낸다."""
    fileStarted = Signal(int, str)
    fileProgress = Signal(int, float)
    fileDone = Signal(int, bool, str)   # idx, ok, 첨부 URL 또는 오류
    allDone = Signal(int, int)          # ok, fail

    def __init__(self, items: list[tuple[str, dict]], webhook_url: str, limit_mb: float = DEFAULT_LIMIT_MB,
                 template: str = DEFAULT_TEMPLATE, username: str = DEFAULT_USERNAME, parent=None):
        super().__init__(parent)
        self.items = list(items)
        self.webhook_url, self.limit_mb, self.template, self.username = webhook_url, limit_mb, template, username
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def content_for(self, path: str, info: dict) -> str:
        values = {"title": info.get("title") or os.path.splitext(os.path.basename(path))[0], "source": info.get("source", "")}
        return fill_template(self.template or DEFAULT_TEMPLATE, values).strip()[:MAX_CONTENT]

    def run(self):
        ok = fail = 0
        for i, (path, info) in enumerate(self.items):
            if self._cancel:
                break
            self.fileStarted.emit(i, os.path.basename(path))
            try:
                msg = send_file(self.webhook_url, path, self.content_for(path, info), self.username,
                                lambda f, i=i: self.fileProgress.emit(i, f), self.limit_mb, lambda: self._cancel)
                ok += 1
                self.fileDone.emit(i, True, attachment_url(msg))
            except Exception as ex:
                fail += 1
                LOG.warning("디스코드 전송 실패: %s: %s", path, ex)
                self.fileDone.emit(i, False, str(ex))
                if self._cancel:
                    break
        self.allDone.emit(ok, fail)


# --------------------------------------------------------------------------- 설정 대화상자
class _TestWorker(QThread):
    done = Signal(object, str)

    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self.url = url

    def run(self):
        try:
            self.done.emit(test_webhook(self.url), "")
        except Exception as ex:
            self.done.emit(None, str(ex))


class DiscordSettingsDialog(QDialog):
    """설정 ▸ 디스코드 웹훅…"""

    def __init__(self, parent=None, settings=None):
        super().__init__(parent)
        self.setWindowTitle(tr("디스코드 웹훅"))
        self.resize(560, 360)
        self.settings = settings
        self.worker = None
        cfg = config(settings) if settings is not None else {"webhook": "", "limit_mb": DEFAULT_LIMIT_MB, "template": DEFAULT_TEMPLATE}
        lay = QVBoxLayout(self)
        intro = QLabel(tr("내보낸 파일을 디스코드 채널에 바로 올립니다. 웹훅은 디스코드에서 채널 설정 ▸ 연동 ▸ 웹훅 ▸ 새 웹훅 ▸ 웹훅 URL 복사로 만듭니다."))
        intro.setWordWrap(True)
        lay.addWidget(intro)
        form = QFormLayout()
        self.ed_url = QLineEdit(cfg["webhook"])
        self.ed_url.setPlaceholderText("https://discord.com/api/webhooks/…")
        form.addRow(tr("웹훅 URL"), self.ed_url)
        self.cb_limit = QComboBox()
        labels = {10: tr("10 MB (기본 서버)"), 25: tr("25 MB"), 50: tr("50 MB (부스트 2단계)"), 100: tr("100 MB (부스트 3단계)")}
        for mb in LIMITS_MB:
            self.cb_limit.addItem(labels.get(mb, f"{mb} MB"), mb)
        i = self.cb_limit.findData(cfg["limit_mb"])
        self.cb_limit.setCurrentIndex(i if i >= 0 else 0)
        self.cb_limit.setToolTip(tr("이 크기를 넘는 파일은 보내지 않고 건너뜁니다. 서버 부스트 단계에 맞춰 고르세요."))
        form.addRow(tr("파일 크기 한도"), self.cb_limit)
        self.ed_template = QPlainTextEdit(cfg["template"])
        self.ed_template.setMaximumHeight(70)
        self.ed_template.setPlaceholderText(DEFAULT_TEMPLATE)
        form.addRow(tr("메시지 템플릿"), self.ed_template)
        lay.addLayout(form)
        hint = QLabel(tr("자리표시자: {title} (파일 이름) · {source} (원본 영상 이름)"))
        hint.setStyleSheet("color:#9aa0a6")
        lay.addWidget(hint)
        row = QHBoxLayout()
        self.b_test = QPushButton(tr("테스트 메시지 보내기"))
        self.b_test.clicked.connect(self._test)
        row.addWidget(self.b_test)
        self.lbl_status = QLabel("")
        row.addWidget(self.lbl_status, 1)
        lay.addLayout(row)
        lay.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(tr("저장"))
        bb.button(QDialogButtonBox.Cancel).setText(tr("취소"))
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    @property
    def webhook(self) -> str:
        return self.ed_url.text().strip()

    @property
    def limit_mb(self) -> int:
        return int(self.cb_limit.currentData() or DEFAULT_LIMIT_MB)

    @property
    def template(self) -> str:
        return self.ed_template.toPlainText().strip() or DEFAULT_TEMPLATE

    def _test(self):
        if not is_webhook_url(self.webhook):
            QMessageBox.warning(self, tr("디스코드 웹훅"), tr("디스코드 웹훅 URL 이 아닙니다 (https://discord.com/api/webhooks/… 형식이어야 합니다)"))
            return
        self.b_test.setEnabled(False)
        self.lbl_status.setText(tr("보내는 중…"))
        self.worker = _TestWorker(self.webhook, self)
        self.worker.done.connect(self._on_test)
        self.worker.start()

    def _on_test(self, msg, err: str):
        self.b_test.setEnabled(True)
        self.lbl_status.setText(tr("실패: {0}").format(err[:80]) if err else tr("성공 — 채널에 테스트 메시지가 올라갔습니다"))

    def _save(self):
        if self.webhook and not is_webhook_url(self.webhook):
            QMessageBox.warning(self, tr("디스코드 웹훅"), tr("디스코드 웹훅 URL 이 아닙니다 (https://discord.com/api/webhooks/… 형식이어야 합니다)"))
            return
        if self.settings is not None:
            self.settings.setValue(KEY_WEBHOOK, self.webhook)
            self.settings.setValue(KEY_LIMIT, self.limit_mb)
            self.settings.setValue(KEY_TEMPLATE, self.template)
        self.accept()

    def closeEvent(self, e):
        if self.worker and self.worker.isRunning():
            self.worker.wait(2000)
        super().closeEvent(e)
