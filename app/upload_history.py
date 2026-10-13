"""유튜브 업로드 이력: <config_dir>/youtube_uploads.jsonl 에 한 줄씩 기록하고, 표로 보여 주는 대화상자."""
from __future__ import annotations

from .i18n import tr
import datetime
import json
import logging
import os
import webbrowser

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget, QTableWidgetItem, QHeaderView, QLabel,
    QAbstractItemView, QApplication,
)

from . import youtube as yt

LOG = logging.getLogger("clipslicer")
HISTORY_FILE = "youtube_uploads.jsonl"
FIELDS = ("ts", "file", "title", "video_id", "url", "channel", "privacy")


def history_path() -> str:
    return os.path.join(yt.config_dir(), HISTORY_FILE)


def _now_iso() -> str:
    return datetime.datetime.now().replace(microsecond=0).isoformat()


def normalize(entry: dict) -> dict:
    """필수 키를 채운 새 dict. ts 가 없으면 지금, url 이 없으면 video_id 로 만든다."""
    out = {k: str(entry.get(k) or "") for k in FIELDS}
    out["ts"] = out["ts"] or _now_iso()
    if not out["url"] and out["video_id"]:
        out["url"] = yt.video_url(out["video_id"])
    for k, v in entry.items():  # 추가 정보(publish_at 등)는 그대로 둔다
        if k not in out and v not in (None, ""):
            out[k] = v
    return out


def record(entry: dict, path: str | None = None) -> dict:
    """업로드 한 건을 JSONL 로 덧붙인다. 기록된(정규화된) dict 를 돌려준다. 파일 오류는 로그만 남긴다."""
    e = normalize(entry)
    p = path or history_path()
    try:
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    except OSError:
        LOG.warning("업로드 이력 기록 실패: %s", p, exc_info=True)
    return e


def load(path: str | None = None) -> list[dict]:
    """기록된 순서(오래된 것부터)로 돌려준다. 깨진 줄은 건너뛴다."""
    p = path or history_path()
    if not os.path.isfile(p):
        return []
    out = []
    try:
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if isinstance(d, dict):
                    out.append(normalize(d))
    except OSError:
        LOG.warning("업로드 이력 읽기 실패: %s", p, exc_info=True)
    return out


def _fmt_ts(ts: str) -> str:
    try:
        return datetime.datetime.fromisoformat(ts).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return ts


class HistoryDialog(QDialog):
    """파일 ▸ 업로드 이력. entries 를 주면 파일 대신 그것을 보여 준다 (테스트용)."""
    COL_DATE, COL_TITLE, COL_FILE, COL_LINK = range(4)

    def __init__(self, parent=None, entries: list[dict] | None = None):
        super().__init__(parent)
        self.setWindowTitle(tr("유튜브 업로드 이력"))
        self.resize(860, 480)
        self.entries = list(reversed(entries if entries is not None else load()))  # 최신이 위
        lay = QVBoxLayout(self)
        self.table = QTableWidget(len(self.entries), 4)
        self.table.setHorizontalHeaderLabels([tr("날짜"), tr("제목"), tr("파일"), tr("링크")])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(self.COL_DATE, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(self.COL_TITLE, QHeaderView.Stretch)
        hh.setSectionResizeMode(self.COL_FILE, QHeaderView.Stretch)
        hh.setSectionResizeMode(self.COL_LINK, QHeaderView.ResizeToContents)
        for r, e in enumerate(self.entries):
            cells = [_fmt_ts(e["ts"]), e["title"], os.path.basename(e["file"]), e["url"]]
            for c, text in enumerate(cells):
                it = QTableWidgetItem(text)
                if c == self.COL_FILE:
                    it.setToolTip(e["file"])
                elif c == self.COL_TITLE:
                    tip = []
                    if e.get("channel"):
                        tip.append(tr("채널: {0}").format(e["channel"]))
                    if e.get("privacy"):
                        tip.append(tr("공개 범위: {0}").format(e["privacy"]))
                    if e.get("publish_at"):
                        tip.append(tr("예약 공개: {0}").format(e["publish_at"]))
                    it.setToolTip("\n".join(tip))
                self.table.setItem(r, c, it)
        self.table.doubleClicked.connect(lambda _i: self._open_link())
        lay.addWidget(self.table, 1)
        self.lbl = QLabel(tr("{0}건 · {1}").format(len(self.entries), history_path() if entries is None else ""))
        self.lbl.setStyleSheet("color:#9aa0a6")
        lay.addWidget(self.lbl)
        row = QHBoxLayout()
        self.b_open = QPushButton(tr("링크 열기"))
        self.b_open.clicked.connect(self._open_link)
        self.b_copy = QPushButton(tr("링크 복사"))
        self.b_copy.clicked.connect(self._copy_link)
        self.b_studio = QPushButton(tr("스튜디오 열기"))
        self.b_studio.setToolTip(tr("선택한 영상의 유튜브 스튜디오 편집 페이지 (선택 없으면 스튜디오 홈)"))
        self.b_studio.clicked.connect(self._open_studio)
        for b in (self.b_open, self.b_copy, self.b_studio):
            b.setEnabled(bool(self.entries) or b is self.b_studio)
            row.addWidget(b)
        row.addStretch(1)
        b_close = QPushButton(tr("닫기"))
        b_close.clicked.connect(self.accept)
        row.addWidget(b_close)
        lay.addLayout(row)
        if self.entries:
            self.table.selectRow(0)

    def current(self) -> dict | None:
        r = self.table.currentRow()
        return self.entries[r] if 0 <= r < len(self.entries) else None

    def _open_link(self):
        e = self.current()
        if e and e["url"]:
            webbrowser.open(e["url"])

    def _copy_link(self):
        e = self.current()
        if e and e["url"]:
            QApplication.clipboard().setText(e["url"])
            self.lbl.setText(tr("링크 복사됨: {0}").format(e["url"]))

    def _open_studio(self):
        e = self.current()
        webbrowser.open(yt.studio_url(e["video_id"]) if e and e["video_id"] else "https://studio.youtube.com/")
