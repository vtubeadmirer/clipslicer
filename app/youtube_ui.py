"""유튜브 계정 연결 대화상자, 업로드 대화상자(메타데이터 카드 + 큐), 제목·설명·태그 프리셋."""
from __future__ import annotations

from .i18n import tr
import datetime
import json
import logging
import os
import webbrowser

from PySide6.QtCore import Qt, QThread, Signal, QDateTime
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QPlainTextEdit, QComboBox,
    QListWidget, QListWidgetItem, QProgressBar, QFileDialog, QMessageBox, QGroupBox, QFormLayout,
    QCheckBox, QSplitter, QWidget, QTextBrowser, QDateTimeEdit,
)

from . import youtube as yt
from . import upload_history
from .segments import fmt_time

LOG = logging.getLogger("clipslicer")

SETUP_HTML = tr("\n<style>body{font-family:'Malgun Gothic',sans-serif;font-size:12.5px;color:#e4e4e8} ol li{margin:4px 0} code{color:#9fe3c9}</style>\n<p><b>한 번만 하면 되는 준비 (약 10분)</b> — 유튜브 API 는 구글이 발급한 \"OAuth 클라이언트\"가 있어야 쓸 수 있습니다.</p>\n<ol>\n <li><a href=\"https://console.cloud.google.com/projectcreate\">Google Cloud 콘솔 ▸ 새 프로젝트</a> — 이름 아무거나 (예: ClipSlicer)</li>\n <li><a href=\"https://console.cloud.google.com/apis/library/youtube.googleapis.com\">YouTube Data API v3</a> 페이지에서 <b>사용 설정</b></li>\n <li><a href=\"https://console.cloud.google.com/apis/credentials/consent\">OAuth 동의 화면</a> — 외부(External), 앱 이름·이메일 입력, 범위는 건너뛰고,\n     <b>테스트 사용자</b>에 본인 구글 계정 추가 (심사 없이 쓰려면 필수)</li>\n <li><a href=\"https://console.cloud.google.com/apis/credentials\">사용자 인증 정보 ▸ 사용자 인증 정보 만들기 ▸ OAuth 클라이언트 ID</a> —\n     유형 <b>데스크톱 앱</b> → 만들기 → <b>JSON 다운로드</b></li>\n <li>아래 <b>client_secret.json 등록</b> 으로 그 파일을 고른 뒤 <b>계정 연결</b> → 브라우저에서 로그인·허용</li>\n</ol>\n<p style=\"color:#9aa0a6\">심사(앱 검증)를 받지 않은 프로젝트로 올린 영상은 <b>비공개로 고정</b>됩니다. 제목·설명·썸네일·재생목록까지 다 채워 올린 뒤,\n유튜브 스튜디오에서 공개 버튼만 누르면 됩니다. 하루 업로드 한도는 약 6개(API 할당량)입니다.</p>\n")

PLACEHOLDER_HINT = "{title} {source} {start} {end} {n}"


class _Worker(QThread):
    done = Signal(object, str)  # result, error

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self.fn = fn
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            self.done.emit(self.fn(lambda: self._cancel), "")
        except Exception as ex:
            self.done.emit(None, str(ex))


class ConnectDialog(QDialog):
    """설정 ▸ 유튜브 계정 연결."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("유튜브 계정 연결"))
        self.resize(680, 560)
        self.worker = None
        lay = QVBoxLayout(self)
        tb = QTextBrowser()
        tb.setOpenExternalLinks(True)
        tb.setHtml(SETUP_HTML)
        lay.addWidget(tb, 1)
        row = QHBoxLayout()
        self.b_file = QPushButton(tr("client_secret.json 등록…"))
        self.b_file.clicked.connect(self._pick_file)
        row.addWidget(self.b_file)
        self.lbl_file = QLabel("")
        self.lbl_file.setStyleSheet("color:#9aa0a6")
        row.addWidget(self.lbl_file, 1)
        lay.addLayout(row)
        row2 = QHBoxLayout()
        self.b_connect = QPushButton(tr("계정 연결 (브라우저 열림)"))
        self.b_connect.setObjectName("exportBtn")
        self.b_connect.clicked.connect(self._connect)
        row2.addWidget(self.b_connect)
        self.b_disconnect = QPushButton(tr("연결 해제"))
        self.b_disconnect.clicked.connect(self._disconnect)
        row2.addWidget(self.b_disconnect)
        row2.addStretch(1)
        self.lbl_status = QLabel("")
        row2.addWidget(self.lbl_status)
        lay.addLayout(row2)
        b_close = QPushButton(tr("닫기"))
        b_close.clicked.connect(self.accept)
        lay.addWidget(b_close, 0, Qt.AlignRight)
        self._refresh()

    def _refresh(self):
        has_client = os.path.isfile(yt.client_path())
        self.lbl_file.setText((tr("등록됨: ") + yt.client_path()) if has_client else tr("아직 없음"))
        self.b_connect.setEnabled(has_client)
        connected = yt.is_connected()
        self.b_disconnect.setEnabled(connected)
        if connected:
            self.lbl_status.setText(tr("연결됨 — 채널 확인 중…"))
            self.worker = _Worker(lambda c: yt.my_channel(), self)
            self.worker.done.connect(lambda ch, err: self.lbl_status.setText(
                tr("연결됨: {0}").format(ch['title']) if ch else tr("연결됨 (확인 실패: {0})").format(err[:60])))
            self.worker.start()
        else:
            self.lbl_status.setText(tr("연결 안 됨"))

    def _pick_file(self):
        p, _ = QFileDialog.getOpenFileName(self, tr("client_secret.json 선택"), "", "JSON (*.json)")
        if not p:
            return
        try:
            yt.install_client_file(p)
        except Exception as ex:
            QMessageBox.warning(self, "client_secret.json", str(ex))
            return
        self._refresh()

    def _connect(self):
        self.b_connect.setEnabled(False)
        self.lbl_status.setText(tr("브라우저에서 로그인하고 허용을 누르세요…"))
        self.worker = _Worker(lambda c: yt.authorize(cancel=c), self)
        self.worker.done.connect(self._on_connected)
        self.worker.start()

    def _on_connected(self, tok, err):
        self.b_connect.setEnabled(True)
        if err:
            QMessageBox.warning(self, tr("계정 연결"), err)
            self.lbl_status.setText(tr("연결 실패"))
            return
        self._refresh()

    def _disconnect(self):
        if QMessageBox.question(self, tr("연결 해제"), tr("저장된 로그인 정보를 지울까요?")) == QMessageBox.Yes:
            yt.disconnect()
            self._refresh()

    def closeEvent(self, e):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
        super().closeEvent(e)


# --------------------------------------------------------------------------- 프리셋
PRESET_KEYS = ("name", "title", "description", "tags", "category", "shorts")


def normalize_preset(p: dict) -> dict:
    """키를 모두 갖춘 새 dict. category '' 는 '변경 안 함'."""
    return {"name": str(p.get("name") or "").strip(), "title": str(p.get("title") or ""),
            "description": str(p.get("description") or ""), "tags": str(p.get("tags") or ""),
            "category": str(p.get("category") or ""), "shorts": bool(p.get("shorts", False))}


class PresetStore:
    """제목·설명·태그 프리셋 목록. settings 의 yt_presets 키에 JSON 문자열로, 마지막 사용은 yt_last_preset 에."""
    KEY = "yt_presets"
    LAST_KEY = "yt_last_preset"

    def __init__(self, settings):
        self.settings = settings

    def load(self) -> list[dict]:
        raw = self.settings.value(self.KEY, "")
        if isinstance(raw, (list, tuple)):      # ini 를 손으로 고쳐 쉼표로 쪼개진 경우
            raw = ",".join(str(x) for x in raw)
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", "replace")
        try:
            data = json.loads(raw) if raw else []
        except (TypeError, ValueError):
            LOG.warning("프리셋 설정이 깨져 무시합니다")
            return []
        out = []
        for p in data if isinstance(data, list) else []:
            if isinstance(p, dict):
                q = normalize_preset(p)
                if q["name"]:
                    out.append(q)
        return out

    def save(self, presets: list[dict]):
        self.settings.setValue(self.KEY, json.dumps([normalize_preset(p) for p in presets], ensure_ascii=False))

    def names(self) -> list[str]:
        return [p["name"] for p in self.load()]

    def get(self, name: str) -> dict | None:
        return next((p for p in self.load() if p["name"] == name), None)

    def upsert(self, preset: dict) -> list[dict]:
        """같은 이름이 있으면 바꾸고 없으면 덧붙인다."""
        q = normalize_preset(preset)
        items = self.load()
        for i, p in enumerate(items):
            if p["name"] == q["name"]:
                items[i] = q
                break
        else:
            items.append(q)
        self.save(items)
        return items

    def delete(self, name: str) -> bool:
        items = self.load()
        rest = [p for p in items if p["name"] != name]
        if len(rest) == len(items):
            return False
        self.save(rest)
        if self.last == name:
            self.last = ""
        return True

    @property
    def last(self) -> str:
        return str(self.settings.value(self.LAST_KEY, "") or "")

    @last.setter
    def last(self, name: str):
        self.settings.setValue(self.LAST_KEY, name or "")


class UploadItem:
    def __init__(self, path: str, title: str, description: str, tags: str, source: str = "", start: float = 0.0, end: float = 0.0,
                 n: str = ""):
        self.path = path
        self.title = title
        self.description = description
        self.tags = tags
        self.thumbnail = ""
        self.source = source
        self.start, self.end = start, end
        self.n = str(n or "")
        self.base_title, self.base_description, self.base_tags = title, description, tags  # 프리셋 적용 전 값
        self.video_id = ""
        self.error = ""

    def values(self, idx: int = 0) -> dict:
        """템플릿 자리표시자 값. {title} 은 프리셋 적용 전 제목."""
        return {"title": self.base_title, "source": self.source, "start": fmt_time(self.start, ms=False),
                "end": fmt_time(self.end, ms=False), "n": self.n or f"{idx + 1:02d}"}

    def reset(self):
        self.title, self.description, self.tags = self.base_title, self.base_description, self.base_tags


def apply_preset(items: list[UploadItem], preset: dict) -> int:
    """프리셋의 제목·설명·태그 템플릿을 모든 항목에 채운다 (빈 템플릿은 그대로 둠). 바뀐 항목 수 반환."""
    p = normalize_preset(preset)
    for i, it in enumerate(items):
        it.reset()
        v = it.values(i)
        if p["title"].strip():
            it.title = yt.fill_template(p["title"], v).strip()[:100] or it.base_title
        if p["description"].strip():
            it.description = yt.fill_template(p["description"], v)
        if p["tags"].strip():
            it.tags = p["tags"]
    return len(items)


class PresetDialog(QDialog):
    """프리셋 추가/편집/삭제. 저장을 누르면 store 에 쓰고, 취소하면 버린다."""

    def __init__(self, parent=None, store: PresetStore | None = None):
        super().__init__(parent)
        self.setWindowTitle(tr("업로드 프리셋"))
        self.resize(760, 440)
        self.store = store
        self.presets: list[dict] = store.load() if store else []
        self._cur = -1
        lay = QVBoxLayout(self)
        intro = QLabel(tr("자주 쓰는 제목·설명·태그·카테고리 묶음입니다. 올리기 창의 프리셋 목록에서 고르면 모든 항목에 한 번에 채워집니다.\n자리표시자: {0}").format(PLACEHOLDER_HINT))
        intro.setWordWrap(True)
        intro.setStyleSheet("color:#9aa0a6")
        lay.addWidget(intro)
        split = QSplitter(Qt.Horizontal)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        for p in self.presets:
            self.list.addItem(QListWidgetItem(p["name"]))
        self.list.currentRowChanged.connect(self._show)
        lv.addWidget(self.list, 1)
        lrow = QHBoxLayout()
        self.b_add = QPushButton(tr("추가"))
        self.b_add.clicked.connect(self._add)
        self.b_del = QPushButton(tr("삭제"))
        self.b_del.clicked.connect(self._delete)
        lrow.addWidget(self.b_add)
        lrow.addWidget(self.b_del)
        lv.addLayout(lrow)
        split.addWidget(left)

        right = QWidget()
        form = QFormLayout(right)
        self.ed_name = QLineEdit()
        self.ed_name.textEdited.connect(self._on_name)
        form.addRow(tr("이름"), self.ed_name)
        self.ed_title = QLineEdit()
        self.ed_title.setPlaceholderText(tr("비우면 파일 이름 그대로 (예: {title} — {source})"))
        self.ed_title.textEdited.connect(lambda t: self._set("title", t))
        form.addRow(tr("제목 템플릿"), self.ed_title)
        self.ed_desc = QPlainTextEdit()
        self.ed_desc.setPlaceholderText(tr("비우면 설명을 바꾸지 않음"))
        self.ed_desc.textChanged.connect(lambda: self._set("description", self.ed_desc.toPlainText()))
        form.addRow(tr("설명 템플릿"), self.ed_desc)
        self.ed_tags = QLineEdit()
        self.ed_tags.setPlaceholderText(tr("쉼표로 구분 · 비우면 태그를 바꾸지 않음"))
        self.ed_tags.textEdited.connect(lambda t: self._set("tags", t))
        form.addRow(tr("태그"), self.ed_tags)
        self.cb_cat = QComboBox()
        self.cb_cat.addItem(tr("(변경 안 함)"), "")
        for cid, name in yt.CATEGORIES:
            self.cb_cat.addItem(name, cid)
        self.cb_cat.currentIndexChanged.connect(lambda _i: self._set("category", self.cb_cat.currentData() or ""))
        form.addRow(tr("카테고리"), self.cb_cat)
        self.cb_shorts = QCheckBox(tr("제목에 #Shorts 붙이기"))
        self.cb_shorts.toggled.connect(lambda c: self._set("shorts", bool(c)))
        form.addRow("", self.cb_shorts)
        split.addWidget(right)
        split.setSizes([220, 540])
        lay.addWidget(split, 1)

        brow = QHBoxLayout()
        brow.addStretch(1)
        b_cancel = QPushButton(tr("취소"))
        b_cancel.clicked.connect(self.reject)
        brow.addWidget(b_cancel)
        b_save = QPushButton(tr("저장"))
        b_save.setObjectName("exportBtn")
        b_save.clicked.connect(self._save)
        brow.addWidget(b_save)
        lay.addLayout(brow)
        self._set_form_enabled(False)
        if self.presets:
            self.list.setCurrentRow(0)

    def _set_form_enabled(self, on: bool):
        for w in (self.ed_name, self.ed_title, self.ed_desc, self.ed_tags, self.cb_cat, self.cb_shorts):
            w.setEnabled(on)
        self.b_del.setEnabled(on)

    def _show(self, row: int):
        self._cur = -1
        ok = 0 <= row < len(self.presets)
        self._set_form_enabled(ok)
        if not ok:
            for w in (self.ed_name, self.ed_title, self.ed_tags):
                w.clear()
            self.ed_desc.clear()
            return
        p = self.presets[row]
        self.ed_name.setText(p["name"])
        self.ed_title.setText(p["title"])
        self.ed_desc.setPlainText(p["description"])
        self.ed_tags.setText(p["tags"])
        i = self.cb_cat.findData(p["category"])
        self.cb_cat.setCurrentIndex(i if i >= 0 else 0)
        self.cb_shorts.setChecked(p["shorts"])
        self._cur = row

    def _set(self, key: str, value):
        if 0 <= self._cur < len(self.presets):
            self.presets[self._cur][key] = value

    def _on_name(self, text: str):
        self._set("name", text.strip())
        if 0 <= self._cur < len(self.presets):
            self.list.item(self._cur).setText(text.strip() or tr("(이름 없음)"))

    def _add(self):
        names = {p["name"] for p in self.presets}
        n = 1
        while tr("새 프리셋 {0}").format(n) in names:
            n += 1
        self.presets.append(normalize_preset({"name": tr("새 프리셋 {0}").format(n)}))
        self.list.addItem(QListWidgetItem(self.presets[-1]["name"]))
        self.list.setCurrentRow(len(self.presets) - 1)
        self.ed_name.setFocus()
        self.ed_name.selectAll()

    def _delete(self):
        row = self.list.currentRow()
        if not (0 <= row < len(self.presets)):
            return
        if QMessageBox.question(self, tr("프리셋 삭제"), tr("'{0}' 프리셋을 지울까요?").format(self.presets[row]["name"])) != QMessageBox.Yes:
            return
        self._cur = -1
        self.presets.pop(row)
        self.list.takeItem(row)
        self._show(self.list.currentRow())

    def validate(self) -> str:
        """저장 가능하면 '', 아니면 오류 메시지."""
        names = [p["name"].strip() for p in self.presets]
        if any(not n for n in names):
            return tr("이름이 비어 있는 프리셋이 있습니다.")
        dup = {n for n in names if names.count(n) > 1}
        if dup:
            return tr("프리셋 이름이 겹칩니다: {0}").format(", ".join(sorted(dup)))
        return ""

    def _save(self):
        err = self.validate()
        if err:
            QMessageBox.warning(self, tr("업로드 프리셋"), err)
            return
        if self.store is not None:
            self.store.save(self.presets)
            if self.store.last and self.store.last not in {p["name"] for p in self.presets}:
                self.store.last = ""
        self.accept()


# --------------------------------------------------------------------------- 업로드
class UploadWorker(QThread):
    itemProgress = Signal(int, float, str)
    itemDone = Signal(int, str, str)   # idx, video_id, error

    allDone = Signal(int, int)

    def __init__(self, items: list[UploadItem], privacy: str, category: str, playlist_id: str,
                 publish_at: str | None = None, channel: str = "", parent=None):
        super().__init__(parent)
        self.items, self.privacy, self.category, self.playlist_id = items, privacy, category, playlist_id
        self.publish_at, self.channel = publish_at or None, channel or ""
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def _record(self, it: UploadItem, vid: str):
        try:
            upload_history.record({"file": it.path, "title": it.title, "video_id": vid, "url": yt.video_url(vid),
                                   "channel": self.channel, "privacy": "private" if self.publish_at else self.privacy,
                                   "publish_at": self.publish_at or ""})
        except Exception:
            LOG.warning("업로드 이력 기록 실패", exc_info=True)

    def run(self):
        ok = fail = 0
        for i, it in enumerate(self.items):
            if self._cancel:
                break
            try:
                meta = yt.build_metadata(it.title, it.description, [t for t in it.tags.replace("，", ",").split(",")],
                                         self.privacy, self.category, publish_at=self.publish_at)
                vid = yt.upload_video(it.path, meta, lambda f, t: self.itemProgress.emit(i, f, t), lambda: self._cancel)
                it.video_id = vid
                self._record(it, vid)
                extra = []
                if self.playlist_id:
                    try:
                        yt.add_to_playlist(self.playlist_id, vid)
                    except Exception as ex:
                        extra.append(tr("재생목록 추가 실패: {0}").format(ex))
                if it.thumbnail and os.path.isfile(it.thumbnail):
                    try:
                        yt.set_thumbnail(vid, it.thumbnail)
                    except Exception as ex:
                        extra.append(tr("썸네일 실패: {0}").format(ex))
                ok += 1
                self.itemDone.emit(i, vid, "; ".join(extra))
            except Exception as ex:
                fail += 1
                it.error = str(ex)
                self.itemDone.emit(i, "", str(ex))
                if tr("취소") in str(ex):
                    break
        self.allDone.emit(ok, fail)


class UploadDialog(QDialog):
    """잘린 파일들을 유튜브에 올리기 (비공개)."""

    def __init__(self, parent, items: list[UploadItem], settings):
        super().__init__(parent)
        self.setWindowTitle(tr("유튜브에 올리기"))
        self.resize(900, 680)
        self.items = items
        self.settings = settings
        self.store = PresetStore(settings)
        self.worker = None
        self.channel_title = ""
        self._ch_worker = None
        self._cur = -1
        lay = QVBoxLayout(self)

        if not yt.is_connected():
            warn = QLabel(tr("유튜브 계정이 연결되어 있지 않습니다. 설정 ▸ 유튜브 계정 연결을 먼저 하세요."))
            warn.setStyleSheet("color:#ffa726; font-weight:bold")
            lay.addWidget(warn)

        prow = QHBoxLayout()
        prow.addWidget(QLabel(tr("프리셋")))
        self.cb_preset = QComboBox()
        self.cb_preset.setToolTip(tr("고르면 모든 항목의 제목·설명·태그·카테고리를 프리셋대로 채웁니다. '(프리셋 없음)' 을 고르면 원래대로."))
        self.cb_preset.currentIndexChanged.connect(self._on_preset_changed)
        prow.addWidget(self.cb_preset, 1)
        self.b_presets = QPushButton(tr("관리…"))
        self.b_presets.clicked.connect(self._manage_presets)
        prow.addWidget(self.b_presets)
        lay.addLayout(prow)

        split = QSplitter(Qt.Horizontal)
        self.list = QListWidget()
        self.list.setMinimumWidth(260)
        for it in items:
            self.list.addItem(QListWidgetItem(os.path.basename(it.path)))
        self.list.currentRowChanged.connect(self._show)
        split.addWidget(self.list)

        right = QWidget()
        rv = QVBoxLayout(right)
        form = QFormLayout()
        self.ed_title = QLineEdit()
        self.ed_title.setMaxLength(100)
        self.ed_title.textEdited.connect(lambda t: self._set("title", t))
        form.addRow(tr("제목"), self.ed_title)
        self.ed_desc = QPlainTextEdit()
        self.ed_desc.setMaximumHeight(120)
        self.ed_desc.textChanged.connect(lambda: self._set("description", self.ed_desc.toPlainText()))
        form.addRow(tr("설명"), self.ed_desc)
        self.ed_tags = QLineEdit()
        self.ed_tags.setPlaceholderText(tr("쉼표로 구분"))
        self.ed_tags.textEdited.connect(lambda t: self._set("tags", t))
        form.addRow(tr("태그"), self.ed_tags)
        trow = QHBoxLayout()
        self.ed_thumb = QLineEdit()
        self.ed_thumb.setPlaceholderText(tr("선택 사항 (PNG/JPG, Ctrl+P 로 저장한 화면)"))
        self.ed_thumb.textEdited.connect(lambda t: self._set("thumbnail", t))
        b_thumb = QPushButton("…")
        b_thumb.clicked.connect(self._pick_thumb)
        trow.addWidget(self.ed_thumb, 1)
        trow.addWidget(b_thumb)
        form.addRow(tr("썸네일"), trow)
        rv.addLayout(form)

        grp = QGroupBox(tr("공통 설정"))
        gf = QFormLayout(grp)
        self.cb_privacy = QComboBox()
        self.cb_privacy.addItem(tr("비공개 (심사 전 프로젝트는 이것만 됨)"), "private")
        self.cb_privacy.addItem(tr("일부공개"), "unlisted")
        self.cb_privacy.addItem(tr("공개"), "public")
        gf.addRow(tr("공개 범위"), self.cb_privacy)
        self.cb_cat = QComboBox()
        for cid, name in yt.CATEGORIES:
            self.cb_cat.addItem(name, cid)
        i = self.cb_cat.findData(settings.value("yt_category", "20"))
        self.cb_cat.setCurrentIndex(i if i >= 0 else 0)
        gf.addRow(tr("카테고리"), self.cb_cat)
        prow = QHBoxLayout()
        self.cb_playlist = QComboBox()
        self.cb_playlist.addItem(tr("(재생목록 없음)"), "")
        b_pl = QPushButton(tr("불러오기"))
        b_pl.clicked.connect(self._load_playlists)
        prow.addWidget(self.cb_playlist, 1)
        prow.addWidget(b_pl)
        gf.addRow(tr("재생목록"), prow)
        self.cb_shorts = QCheckBox(tr("제목에 #Shorts 붙이기 (세로 영상일 때)"))
        gf.addRow("", self.cb_shorts)
        srow = QHBoxLayout()
        self.cb_schedule = QCheckBox(tr("예약 공개"))
        self.cb_schedule.setToolTip(tr("비공개로 올린 뒤 이 시각(내 컴퓨터 시간)에 유튜브가 자동으로 공개합니다"))
        self.cb_schedule.toggled.connect(self._on_schedule_toggled)
        srow.addWidget(self.cb_schedule)
        self.dt_publish = QDateTimeEdit()
        self.dt_publish.setCalendarPopup(True)
        self.dt_publish.setDisplayFormat("yyyy-MM-dd HH:mm")
        now = QDateTime.currentDateTime()
        self.dt_publish.setDateTime(now.addSecs(3600 - now.time().second()))
        self.dt_publish.setEnabled(False)
        srow.addWidget(self.dt_publish)
        srow.addStretch(1)
        gf.addRow("", srow)
        self.lbl_schedule = QLabel(tr("예약하면 공개 범위는 비공개로 올라가고 예약 시각에 공개됩니다. 심사(검증)받지 않은 프로젝트에서는 예약이 무시되고 비공개로 남을 수 있습니다."))
        self.lbl_schedule.setWordWrap(True)
        self.lbl_schedule.setStyleSheet("color:#9aa0a6")
        self.lbl_schedule.hide()
        gf.addRow("", self.lbl_schedule)
        rv.addWidget(grp)
        rv.addStretch(1)
        split.addWidget(right)
        split.setSizes([280, 600])
        lay.addWidget(split, 1)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setFormat("")
        lay.addWidget(self.progress)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(90)
        lay.addWidget(self.log)
        brow = QHBoxLayout()
        self.b_links = QPushButton(tr("링크 복사"))
        self.b_links.setEnabled(False)
        self.b_links.clicked.connect(self._copy_links)
        brow.addWidget(self.b_links)
        self.b_studio = QPushButton(tr("유튜브 스튜디오 열기"))
        self.b_studio.clicked.connect(lambda: webbrowser.open("https://studio.youtube.com/"))
        brow.addWidget(self.b_studio)
        self.b_history = QPushButton(tr("업로드 이력…"))
        self.b_history.clicked.connect(lambda: upload_history.HistoryDialog(self).exec())
        brow.addWidget(self.b_history)
        brow.addStretch(1)
        self.b_cancel = QPushButton(tr("닫기"))
        self.b_cancel.clicked.connect(self._close)
        brow.addWidget(self.b_cancel)
        self.b_upload = QPushButton(tr("올리기 ({0}개)").format(len(items)))
        self.b_upload.setObjectName("exportBtn")
        self.b_upload.setEnabled(yt.is_connected() and bool(items))
        self.b_upload.clicked.connect(self._start)
        brow.addWidget(self.b_upload)
        lay.addLayout(brow)
        self._refresh_presets(self.store.last)
        if items:
            self.list.setCurrentRow(0)
        if yt.is_connected():
            self._fetch_channel()

    # ---- 채널 (이력에 기록할 이름; 실패해도 무시) ----
    def _fetch_channel(self):
        self._ch_worker = _Worker(lambda c: yt.my_channel(), self)
        self._ch_worker.done.connect(self._on_channel)
        self._ch_worker.start()

    def _on_channel(self, ch, err: str):
        if ch:
            self.channel_title = ch.get("title", "")
            if self.worker:
                self.worker.channel = self.channel_title
        else:
            LOG.info("채널 이름 확인 실패: %s", err)

    # ---- 프리셋 ----
    def _refresh_presets(self, select: str = ""):
        self.cb_preset.blockSignals(True)
        self.cb_preset.clear()
        self.cb_preset.addItem(tr("(프리셋 없음)"), "")
        for name in self.store.names():
            self.cb_preset.addItem(name, name)
        i = self.cb_preset.findData(select) if select else -1
        self.cb_preset.setCurrentIndex(i if i >= 0 else 0)
        self.cb_preset.blockSignals(False)
        self._on_preset_changed(self.cb_preset.currentIndex())

    def _on_preset_changed(self, index: int):
        name = self.cb_preset.itemData(index) if index >= 0 else ""
        preset = self.store.get(name) if name else None
        if preset:
            n = apply_preset(self.items, preset)
            if preset["category"]:
                i = self.cb_cat.findData(preset["category"])
                if i >= 0:
                    self.cb_cat.setCurrentIndex(i)
            self.cb_shorts.setChecked(preset["shorts"])
            self.store.last = preset["name"]
            self.log.appendPlainText(tr("프리셋 '{0}' 적용: {1}개 항목").format(preset["name"], n))
        else:
            for it in self.items:
                it.reset()
            self.store.last = ""
        self._show(self.list.currentRow())

    def _manage_presets(self):
        d = PresetDialog(self, self.store)
        d.exec()
        self._refresh_presets(self.store.last)

    def _on_schedule_toggled(self, on: bool):
        self.dt_publish.setEnabled(on)
        self.lbl_schedule.setVisible(on)
        self.cb_privacy.setEnabled(not on)
        if on:
            self.cb_privacy.setCurrentIndex(0)

    def _publish_at(self) -> str | None:
        """예약 공개가 켜져 있으면 RFC3339 UTC 문자열, 아니면 None."""
        if not self.cb_schedule.isChecked():
            return None
        return yt.to_rfc3339_utc(self.dt_publish.dateTime().toPython())

    # ---- 항목 편집 ----
    def _show(self, row: int):
        self._cur = -1
        if 0 <= row < len(self.items):
            it = self.items[row]
            self.ed_title.setText(it.title)
            self.ed_desc.setPlainText(it.description)
            self.ed_tags.setText(it.tags)
            self.ed_thumb.setText(it.thumbnail)
            self._cur = row

    def _set(self, attr: str, value: str):
        if 0 <= self._cur < len(self.items):
            setattr(self.items[self._cur], attr, value)

    def _pick_thumb(self):
        p, _ = QFileDialog.getOpenFileName(self, tr("썸네일"), "", tr("이미지 (*.png *.jpg *.jpeg)"))
        if p:
            self.ed_thumb.setText(p)
            self._set("thumbnail", p)

    def _load_playlists(self):
        w = _Worker(lambda c: yt.my_playlists(), self)

        def done(res, err):
            if err:
                QMessageBox.warning(self, tr("재생목록"), err)
                return
            self.cb_playlist.clear()
            self.cb_playlist.addItem(tr("(재생목록 없음)"), "")
            for pid, name in res:
                self.cb_playlist.addItem(name, pid)
        w.done.connect(done)
        w.start()
        self._pl_worker = w

    # ---- 업로드 ----
    def _precheck(self) -> bool:
        """길이·크기·쇼츠·예약 시각·할당량 검사. 올려도 되면 True."""
        from . import ffmpeg_tools
        errors, warns = [], []
        if self.cb_schedule.isChecked():
            when = self.dt_publish.dateTime().toPython()
            if when <= datetime.datetime.now() + datetime.timedelta(minutes=1):
                QMessageBox.warning(self, tr("예약 공개"), tr("예약 시각이 이미 지났습니다. 앞으로의 시각을 고르세요."))
                return False
        for it in self.items:
            if not it.title.strip():
                errors.append(tr("제목이 비어 있습니다: {0}").format(os.path.basename(it.path)))
                continue
            if not os.path.isfile(it.path):
                errors.append(tr("파일이 없습니다: {0}").format(it.path))
                continue
            try:
                dur = ffmpeg_tools.probe(it.path)["duration"]
            except Exception:
                dur = 0.0
            e, w = yt.check_upload(it.path, dur, os.path.getsize(it.path), self.cb_shorts.isChecked())
            errors += e
            warns += w
        if errors:
            QMessageBox.critical(self, tr("올릴 수 없는 파일"), "\n\n".join(errors[:8]))
            return False
        used = yt.uploads_today(self.settings)
        n = len(self.items)
        if used + n > yt.DAILY_UPLOADS:
            warns.insert(0, tr("오늘 API 할당량으로 올릴 수 있는 건수는 약 {0}개이고 이미 {1}개를 올렸습니다. 지금 {2}개를 올리면 {3}개까지만 성공하고 나머지는 '할당량 초과'로 실패할 수 있습니다. (할당량은 한국 시간 오후 4~5시쯤 초기화)").format(yt.DAILY_UPLOADS, used, n, max(0, yt.DAILY_UPLOADS - used)))
        if warns:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle(tr("올리기 전 확인"))
            box.setText("\n\n".join(warns[:8]) + tr("\n\n그래도 올릴까요?"))
            box.addButton(tr("올리기"), QMessageBox.AcceptRole)
            cancel = box.addButton(tr("취소"), QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is cancel:
                return False
        return True

    def _start(self):
        if not self._precheck():
            return
        for it in self.items:
            if self.cb_shorts.isChecked() and "#shorts" not in it.title.lower():
                it.title = (it.title + " #Shorts")[:100]
        self.settings.setValue("yt_category", self.cb_cat.currentData())
        publish_at = self._publish_at()
        if publish_at:
            self.log.appendPlainText(tr("예약 공개: {0} (UTC {1})").format(self.dt_publish.dateTime().toString("yyyy-MM-dd HH:mm"), publish_at))
        self.b_upload.setEnabled(False)
        self.list.setEnabled(False)
        self.cb_preset.setEnabled(False)
        self.worker = UploadWorker(self.items, self.cb_privacy.currentData(), self.cb_cat.currentData(),
                                   self.cb_playlist.currentData() or "", publish_at=publish_at,
                                   channel=self.channel_title, parent=self)
        self.worker.itemProgress.connect(self._on_prog)
        self.worker.itemDone.connect(self._on_item)
        self.worker.allDone.connect(self._on_all)
        self.worker.start()

    def _on_prog(self, i: int, frac: float, text: str):
        n = len(self.items)
        self.progress.setValue(int((i + frac) / n * 1000))
        self.progress.setFormat(f"[{i + 1}/{n}] {os.path.basename(self.items[i].path)}  {text}")

    def _on_item(self, i: int, vid: str, err: str):
        it = self.items[i]
        if vid:
            n = yt.record_upload(self.settings)
            self.log.appendPlainText(f"✔ {os.path.basename(it.path)} → {yt.video_url(vid)}" + (f"  ({err})" if err else "")
                                     + tr("   (오늘 {0}/{1})").format(n, yt.DAILY_UPLOADS))
            self.list.item(i).setText("✔ " + os.path.basename(it.path))
        else:
            self.log.appendPlainText(f"✖ {os.path.basename(it.path)}: {err}")
            self.list.item(i).setText("✖ " + os.path.basename(it.path))

    def _on_all(self, ok: int, fail: int):
        notifier = getattr(self.parent(), "notifier", None)
        if notifier is not None:
            notifier.notify(tr("유튜브 업로드 완료"), tr("성공 {0}, 실패 {1}").format(ok, fail))
        self.progress.setFormat(tr("완료: 성공 {0}, 실패 {1}").format(ok, fail))
        self.log.appendPlainText(tr("완료 — 성공 {0}, 실패 {1}. 공개로 바꾸려면 유튜브 스튜디오에서 공개 범위를 변경하세요.").format(ok, fail))
        self.b_links.setEnabled(ok > 0)
        self.list.setEnabled(True)
        self.cb_preset.setEnabled(fail > 0)
        self.b_upload.setEnabled(fail > 0)
        self.b_upload.setText(tr("실패한 항목 다시 올리기"))
        if fail:
            self._done_items = getattr(self, "_done_items", []) + [it for it in self.items if it.video_id]
            self.items = [it for it in self.items if not it.video_id]
            self.list.clear()
            for it in self.items:
                self.list.addItem(QListWidgetItem("✖ " + os.path.basename(it.path)))
            if self.items:
                self.list.setCurrentRow(0)

    def _copy_links(self):
        from PySide6.QtWidgets import QApplication
        links = [yt.video_url(it.video_id) for it in getattr(self, "_done_items", []) + self.items if it.video_id]
        QApplication.clipboard().setText("\n".join(links))
        self.log.appendPlainText(tr("링크 {0}개 복사").format(len(links)))

    def _close(self):
        if self.worker and self.worker.isRunning():
            if QMessageBox.question(self, tr("업로드"), tr("업로드 중입니다. 취소할까요?")) != QMessageBox.Yes:
                return
            self.worker.cancel()
            self.worker.wait(5000)
        if self._ch_worker and self._ch_worker.isRunning():
            self._ch_worker.wait(2000)
        self.accept()


def make_items(files: list[tuple[str, dict]], template: str) -> list[UploadItem]:
    """(파일 경로, 정보 dict{title, source, start, end, n}) → UploadItem 목록."""
    items = []
    for path, info in files:
        values = {"title": info.get("title", ""), "source": info.get("source", ""),
                  "start": fmt_time(info.get("start", 0.0), ms=False), "end": fmt_time(info.get("end", 0.0), ms=False),
                  "n": info.get("n", "")}
        desc = yt.fill_template(template, values)
        items.append(UploadItem(path, info.get("title") or os.path.splitext(os.path.basename(path))[0], desc, info.get("tags", ""),
                                info.get("source", ""), info.get("start", 0.0), info.get("end", 0.0), info.get("n", "")))
    return items
