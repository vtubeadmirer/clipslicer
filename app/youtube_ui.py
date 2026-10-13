"""유튜브 계정 연결 대화상자, 업로드 대화상자(메타데이터 카드 + 큐)."""
from __future__ import annotations

import os
import webbrowser

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QPlainTextEdit, QComboBox,
    QListWidget, QListWidgetItem, QProgressBar, QFileDialog, QMessageBox, QGroupBox, QFormLayout,
    QCheckBox, QSplitter, QWidget, QTextBrowser,
)

from . import youtube as yt
from .segments import fmt_time

SETUP_HTML = """
<style>body{font-family:'Malgun Gothic',sans-serif;font-size:12.5px;color:#e4e4e8} ol li{margin:4px 0} code{color:#9fe3c9}</style>
<p><b>한 번만 하면 되는 준비 (약 10분)</b> — 유튜브 API 는 구글이 발급한 "OAuth 클라이언트"가 있어야 쓸 수 있습니다.</p>
<ol>
 <li><a href="https://console.cloud.google.com/projectcreate">Google Cloud 콘솔 ▸ 새 프로젝트</a> — 이름 아무거나 (예: ClipSlicer)</li>
 <li><a href="https://console.cloud.google.com/apis/library/youtube.googleapis.com">YouTube Data API v3</a> 페이지에서 <b>사용 설정</b></li>
 <li><a href="https://console.cloud.google.com/apis/credentials/consent">OAuth 동의 화면</a> — 외부(External), 앱 이름·이메일 입력, 범위는 건너뛰고,
     <b>테스트 사용자</b>에 본인 구글 계정 추가 (심사 없이 쓰려면 필수)</li>
 <li><a href="https://console.cloud.google.com/apis/credentials">사용자 인증 정보 ▸ 사용자 인증 정보 만들기 ▸ OAuth 클라이언트 ID</a> —
     유형 <b>데스크톱 앱</b> → 만들기 → <b>JSON 다운로드</b></li>
 <li>아래 <b>client_secret.json 등록</b> 으로 그 파일을 고른 뒤 <b>계정 연결</b> → 브라우저에서 로그인·허용</li>
</ol>
<p style="color:#9aa0a6">심사(앱 검증)를 받지 않은 프로젝트로 올린 영상은 <b>비공개로 고정</b>됩니다. 제목·설명·썸네일·재생목록까지 다 채워 올린 뒤,
유튜브 스튜디오에서 공개 버튼만 누르면 됩니다. 하루 업로드 한도는 약 6개(API 할당량)입니다.</p>
"""


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
        self.setWindowTitle("유튜브 계정 연결")
        self.resize(680, 560)
        self.worker = None
        lay = QVBoxLayout(self)
        tb = QTextBrowser()
        tb.setOpenExternalLinks(True)
        tb.setHtml(SETUP_HTML)
        lay.addWidget(tb, 1)
        row = QHBoxLayout()
        self.b_file = QPushButton("client_secret.json 등록…")
        self.b_file.clicked.connect(self._pick_file)
        row.addWidget(self.b_file)
        self.lbl_file = QLabel("")
        self.lbl_file.setStyleSheet("color:#9aa0a6")
        row.addWidget(self.lbl_file, 1)
        lay.addLayout(row)
        row2 = QHBoxLayout()
        self.b_connect = QPushButton("계정 연결 (브라우저 열림)")
        self.b_connect.setObjectName("exportBtn")
        self.b_connect.clicked.connect(self._connect)
        row2.addWidget(self.b_connect)
        self.b_disconnect = QPushButton("연결 해제")
        self.b_disconnect.clicked.connect(self._disconnect)
        row2.addWidget(self.b_disconnect)
        row2.addStretch(1)
        self.lbl_status = QLabel("")
        row2.addWidget(self.lbl_status)
        lay.addLayout(row2)
        b_close = QPushButton("닫기")
        b_close.clicked.connect(self.accept)
        lay.addWidget(b_close, 0, Qt.AlignRight)
        self._refresh()

    def _refresh(self):
        has_client = os.path.isfile(yt.client_path())
        self.lbl_file.setText(("등록됨: " + yt.client_path()) if has_client else "아직 없음")
        self.b_connect.setEnabled(has_client)
        connected = yt.is_connected()
        self.b_disconnect.setEnabled(connected)
        if connected:
            self.lbl_status.setText("연결됨 — 채널 확인 중…")
            self.worker = _Worker(lambda c: yt.my_channel(), self)
            self.worker.done.connect(lambda ch, err: self.lbl_status.setText(
                f"연결됨: {ch['title']}" if ch else f"연결됨 (확인 실패: {err[:60]})"))
            self.worker.start()
        else:
            self.lbl_status.setText("연결 안 됨")

    def _pick_file(self):
        p, _ = QFileDialog.getOpenFileName(self, "client_secret.json 선택", "", "JSON (*.json)")
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
        self.lbl_status.setText("브라우저에서 로그인하고 허용을 누르세요…")
        self.worker = _Worker(lambda c: yt.authorize(cancel=c), self)
        self.worker.done.connect(self._on_connected)
        self.worker.start()

    def _on_connected(self, tok, err):
        self.b_connect.setEnabled(True)
        if err:
            QMessageBox.warning(self, "계정 연결", err)
            self.lbl_status.setText("연결 실패")
            return
        self._refresh()

    def _disconnect(self):
        if QMessageBox.question(self, "연결 해제", "저장된 로그인 정보를 지울까요?") == QMessageBox.Yes:
            yt.disconnect()
            self._refresh()

    def closeEvent(self, e):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
        super().closeEvent(e)


class UploadItem:
    def __init__(self, path: str, title: str, description: str, tags: str, source: str = "", start: float = 0.0, end: float = 0.0):
        self.path = path
        self.title = title
        self.description = description
        self.tags = tags
        self.thumbnail = ""
        self.source = source
        self.start, self.end = start, end
        self.video_id = ""
        self.error = ""


class UploadWorker(QThread):
    itemProgress = Signal(int, float, str)
    itemDone = Signal(int, str, str)   # idx, video_id, error
    allDone = Signal(int, int)

    def __init__(self, items: list[UploadItem], privacy: str, category: str, playlist_id: str, parent=None):
        super().__init__(parent)
        self.items, self.privacy, self.category, self.playlist_id = items, privacy, category, playlist_id
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        ok = fail = 0
        for i, it in enumerate(self.items):
            if self._cancel:
                break
            try:
                meta = yt.build_metadata(it.title, it.description, [t for t in it.tags.replace("，", ",").split(",")],
                                         self.privacy, self.category)
                vid = yt.upload_video(it.path, meta, lambda f, t: self.itemProgress.emit(i, f, t), lambda: self._cancel)
                it.video_id = vid
                extra = []
                if self.playlist_id:
                    try:
                        yt.add_to_playlist(self.playlist_id, vid)
                    except Exception as ex:
                        extra.append(f"재생목록 추가 실패: {ex}")
                if it.thumbnail and os.path.isfile(it.thumbnail):
                    try:
                        yt.set_thumbnail(vid, it.thumbnail)
                    except Exception as ex:
                        extra.append(f"썸네일 실패: {ex}")
                ok += 1
                self.itemDone.emit(i, vid, "; ".join(extra))
            except Exception as ex:
                fail += 1
                it.error = str(ex)
                self.itemDone.emit(i, "", str(ex))
                if "취소" in str(ex):
                    break
        self.allDone.emit(ok, fail)


class UploadDialog(QDialog):
    """잘린 파일들을 유튜브에 올리기 (비공개)."""

    def __init__(self, parent, items: list[UploadItem], settings):
        super().__init__(parent)
        self.setWindowTitle("유튜브에 올리기")
        self.resize(900, 620)
        self.items = items
        self.settings = settings
        self.worker = None
        self._cur = -1
        lay = QVBoxLayout(self)

        if not yt.is_connected():
            warn = QLabel("유튜브 계정이 연결되어 있지 않습니다. 설정 ▸ 유튜브 계정 연결을 먼저 하세요.")
            warn.setStyleSheet("color:#ffa726; font-weight:bold")
            lay.addWidget(warn)

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
        form.addRow("제목", self.ed_title)
        self.ed_desc = QPlainTextEdit()
        self.ed_desc.setMaximumHeight(120)
        self.ed_desc.textChanged.connect(lambda: self._set("description", self.ed_desc.toPlainText()))
        form.addRow("설명", self.ed_desc)
        self.ed_tags = QLineEdit()
        self.ed_tags.setPlaceholderText("쉼표로 구분")
        self.ed_tags.textEdited.connect(lambda t: self._set("tags", t))
        form.addRow("태그", self.ed_tags)
        trow = QHBoxLayout()
        self.ed_thumb = QLineEdit()
        self.ed_thumb.setPlaceholderText("선택 사항 (PNG/JPG, Ctrl+P 로 저장한 화면)")
        self.ed_thumb.textEdited.connect(lambda t: self._set("thumbnail", t))
        b_thumb = QPushButton("…")
        b_thumb.clicked.connect(self._pick_thumb)
        trow.addWidget(self.ed_thumb, 1)
        trow.addWidget(b_thumb)
        form.addRow("썸네일", trow)
        rv.addLayout(form)

        grp = QGroupBox("공통 설정")
        gf = QFormLayout(grp)
        self.cb_privacy = QComboBox()
        self.cb_privacy.addItem("비공개 (심사 전 프로젝트는 이것만 됨)", "private")
        self.cb_privacy.addItem("일부공개", "unlisted")
        self.cb_privacy.addItem("공개", "public")
        gf.addRow("공개 범위", self.cb_privacy)
        self.cb_cat = QComboBox()
        for cid, name in yt.CATEGORIES:
            self.cb_cat.addItem(name, cid)
        i = self.cb_cat.findData(settings.value("yt_category", "20"))
        self.cb_cat.setCurrentIndex(i if i >= 0 else 0)
        gf.addRow("카테고리", self.cb_cat)
        prow = QHBoxLayout()
        self.cb_playlist = QComboBox()
        self.cb_playlist.addItem("(재생목록 없음)", "")
        b_pl = QPushButton("불러오기")
        b_pl.clicked.connect(self._load_playlists)
        prow.addWidget(self.cb_playlist, 1)
        prow.addWidget(b_pl)
        gf.addRow("재생목록", prow)
        self.cb_shorts = QCheckBox("제목에 #Shorts 붙이기 (세로 영상일 때)")
        gf.addRow("", self.cb_shorts)
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
        self.b_links = QPushButton("링크 복사")
        self.b_links.setEnabled(False)
        self.b_links.clicked.connect(self._copy_links)
        brow.addWidget(self.b_links)
        self.b_studio = QPushButton("유튜브 스튜디오 열기")
        self.b_studio.clicked.connect(lambda: webbrowser.open("https://studio.youtube.com/"))
        brow.addWidget(self.b_studio)
        brow.addStretch(1)
        self.b_cancel = QPushButton("닫기")
        self.b_cancel.clicked.connect(self._close)
        brow.addWidget(self.b_cancel)
        self.b_upload = QPushButton(f"올리기 ({len(items)}개)")
        self.b_upload.setObjectName("exportBtn")
        self.b_upload.setEnabled(yt.is_connected() and bool(items))
        self.b_upload.clicked.connect(self._start)
        brow.addWidget(self.b_upload)
        lay.addLayout(brow)
        if items:
            self.list.setCurrentRow(0)

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
        p, _ = QFileDialog.getOpenFileName(self, "썸네일", "", "이미지 (*.png *.jpg *.jpeg)")
        if p:
            self.ed_thumb.setText(p)
            self._set("thumbnail", p)

    def _load_playlists(self):
        w = _Worker(lambda c: yt.my_playlists(), self)

        def done(res, err):
            if err:
                QMessageBox.warning(self, "재생목록", err)
                return
            self.cb_playlist.clear()
            self.cb_playlist.addItem("(재생목록 없음)", "")
            for pid, name in res:
                self.cb_playlist.addItem(name, pid)
        w.done.connect(done)
        w.start()
        self._pl_worker = w

    # ---- 업로드 ----
    def _precheck(self) -> bool:
        """길이·크기·쇼츠·할당량 검사. 올려도 되면 True."""
        from . import ffmpeg_tools
        errors, warns = [], []
        for it in self.items:
            if not it.title.strip():
                errors.append(f"제목이 비어 있습니다: {os.path.basename(it.path)}")
                continue
            if not os.path.isfile(it.path):
                errors.append(f"파일이 없습니다: {it.path}")
                continue
            try:
                dur = ffmpeg_tools.probe(it.path)["duration"]
            except Exception:
                dur = 0.0
            e, w = yt.check_upload(it.path, dur, os.path.getsize(it.path), self.cb_shorts.isChecked())
            errors += e
            warns += w
        if errors:
            QMessageBox.critical(self, "올릴 수 없는 파일", "\n\n".join(errors[:8]))
            return False
        used = yt.uploads_today(self.settings)
        n = len(self.items)
        if used + n > yt.DAILY_UPLOADS:
            warns.insert(0, f"오늘 API 할당량으로 올릴 수 있는 건수는 약 {yt.DAILY_UPLOADS}개이고 이미 {used}개를 올렸습니다. "
                            f"지금 {n}개를 올리면 {max(0, yt.DAILY_UPLOADS - used)}개까지만 성공하고 나머지는 '할당량 초과'로 실패할 수 있습니다. "
                            "(할당량은 한국 시간 오후 4~5시쯤 초기화)")
        if warns:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle("올리기 전 확인")
            box.setText("\n\n".join(warns[:8]) + "\n\n그래도 올릴까요?")
            box.addButton("올리기", QMessageBox.AcceptRole)
            cancel = box.addButton("취소", QMessageBox.RejectRole)
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
        self.b_upload.setEnabled(False)
        self.list.setEnabled(False)
        self.worker = UploadWorker(self.items, self.cb_privacy.currentData(), self.cb_cat.currentData(),
                                   self.cb_playlist.currentData() or "", self)
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
                                     + f"   (오늘 {n}/{yt.DAILY_UPLOADS})")
            self.list.item(i).setText("✔ " + os.path.basename(it.path))
        else:
            self.log.appendPlainText(f"✖ {os.path.basename(it.path)}: {err}")
            self.list.item(i).setText("✖ " + os.path.basename(it.path))

    def _on_all(self, ok: int, fail: int):
        self.progress.setFormat(f"완료: 성공 {ok}, 실패 {fail}")
        self.log.appendPlainText(f"완료 — 성공 {ok}, 실패 {fail}. 공개로 바꾸려면 유튜브 스튜디오에서 공개 범위를 변경하세요.")
        self.b_links.setEnabled(ok > 0)
        self.list.setEnabled(True)
        self.b_upload.setEnabled(fail > 0)
        self.b_upload.setText("실패한 항목 다시 올리기")
        self.items = [it for it in self.items if not it.video_id] if fail else self.items

    def _copy_links(self):
        from PySide6.QtWidgets import QApplication
        links = [yt.video_url(it.video_id) for it in self.items if it.video_id]
        QApplication.clipboard().setText("\n".join(links))
        self.log.appendPlainText(f"링크 {len(links)}개 복사")

    def _close(self):
        if self.worker and self.worker.isRunning():
            if QMessageBox.question(self, "업로드", "업로드 중입니다. 취소할까요?") != QMessageBox.Yes:
                return
            self.worker.cancel()
            self.worker.wait(5000)
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
                                info.get("source", ""), info.get("start", 0.0), info.get("end", 0.0)))
    return items
