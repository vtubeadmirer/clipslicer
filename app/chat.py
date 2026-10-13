"""채팅 반응 그래프 · 키워드 마커.

치지직 다시보기 / 유튜브 라이브 다시보기의 채팅을 받아 시간대별(기본 10초) 반응량을 세고,
반응이 몰린 곳이나 특정 키워드(ㅋㅋㅋ, 레전드 …)가 쏟아진 곳을 마커 후보로 돌려준다.

- ChatData: 메시지 목록 + 버킷(시간대별 개수). <영상>.clipslicer.chat.json 으로 저장/복원.
- fetch_chzzk / fetch_youtube: 네트워크로 채팅 받기 (순수 함수, Qt 불필요).
- ChatWorker / ChatDialog: 백그라운드 받기 + 마커 옵션 대화상자. 대화상자는 ClipProject 를 건드리지 않는다.
"""
from __future__ import annotations

from .i18n import tr
import json
import logging
import math
import os
import re
import shutil
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable

from PySide6.QtCore import QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit, QPushButton, QProgressBar,
    QGroupBox, QSpinBox, QDoubleSpinBox, QDialogButtonBox, QMessageBox,
)

from .segments import fmt_time

LOG = logging.getLogger("clipslicer")

CHAT_SUFFIX = ".clipslicer.chat.json"
MAX_MESSAGES = 200_000
DEFAULT_BUCKET_SEC = 10.0
DEFAULT_KEYWORDS = "ㅋㅋㅋ, 미쳤다, 클립, 레전드, ㄷㄷ"
USER_AGENT = "Mozilla/5.0"
CHZZK_API = "https://api.chzzk.naver.com/service/v1/videos/{video_no}/chats"
CHZZK_PAGE_SIZE = 50
HTTP_RETRIES = 3

ProgressCb = Callable[[float, str], None]
CancelCb = Callable[[], bool]
Message = tuple[float, str, str]  # (t_sec, text, user)

_CHZZK_RE = re.compile(r"chzzk\.naver\.com/(?:[a-z]{2}/)?video/(\d+)", re.IGNORECASE)
_YT_HOST_RE = re.compile(r"^(?:www\.|m\.|music\.)?(?:youtube\.com|youtu\.be|youtube-nocookie\.com)$", re.IGNORECASE)


class ChatError(Exception):
    """채팅을 받을 수 없을 때 (사용자에게 보여 줄 메시지)."""


# --------------------------------------------------------------------------- 데이터
def parse_keywords(text: str) -> list[str]:
    """'ㅋㅋㅋ, 미쳤다' 같은 쉼표/줄바꿈 구분 문자열 → 키워드 목록 (빈 항목·중복 제거, 원래 순서)."""
    out: list[str] = []
    for part in re.split(r"[,\n]", text or ""):
        k = part.strip()
        if k and k not in out:
            out.append(k)
    return out


def _cap_messages(messages: list[Message], limit: int = MAX_MESSAGES) -> list[Message]:
    """limit 개를 넘으면 전체 길이에 걸쳐 고르게 솎아낸다 (앞부분만 남기면 뒷부분 키워드 반응이 사라짐)."""
    n = len(messages)
    if n <= limit or limit <= 0:
        return list(messages)
    step = n / limit
    return [messages[min(n - 1, int(i * step))] for i in range(limit)]


def _select_peaks(buckets: list[int], bucket_sec: float, top_n: int, min_gap: float) -> list[float]:
    """가장 바쁜 버킷부터 고르되 이미 고른 시각과 min_gap 이내면 건너뛴다. 시각 오름차순 반환."""
    if not buckets or bucket_sec <= 0 or top_n <= 0:
        return []
    order = sorted((i for i, c in enumerate(buckets) if c > 0), key=lambda i: (-buckets[i], i))
    chosen: list[float] = []
    for i in order:
        t = i * bucket_sec
        if all(abs(t - c) >= min_gap for c in chosen):
            chosen.append(t)
            if len(chosen) >= top_n:
                break
    return sorted(chosen)


@dataclass
class ChatData:
    """채팅 메시지와 시간대별 개수.

    messages: (초, 내용, 닉네임). buckets[i] = [i*bucket_sec, (i+1)*bucket_sec) 사이 메시지 수.
    """
    messages: list[Message] = field(default_factory=list)
    bucket_sec: float = DEFAULT_BUCKET_SEC
    buckets: list[int] = field(default_factory=list)
    duration: float = 0.0
    source: str = ""

    @property
    def count(self) -> int:
        return len(self.messages)

    @property
    def max_bucket(self) -> int:
        return max(self.buckets) if self.buckets else 0

    def _bucket_count(self, duration: float, bucket_sec: float) -> int:
        """영상 길이를 알면 그만큼, 모르면 마지막 메시지까지. 길이 밖의 메시지는 마지막 버킷으로 몰린다."""
        if duration > 0:
            span = duration
        else:
            span = max((m[0] for m in self.messages), default=0.0) + 1e-6
        return max(1, int(math.ceil(max(span, bucket_sec) / bucket_sec)))

    def _count_into(self, msgs, duration: float, bucket_sec: float) -> list[int]:
        n = self._bucket_count(duration, bucket_sec)
        counts = [0] * n
        for t, _text, _user in msgs:
            i = int(t // bucket_sec) if t > 0 else 0
            counts[min(n - 1, max(0, i))] += 1
        return counts

    def build_buckets(self, duration: float | None = None, bucket_sec: float | None = None) -> list[int]:
        """messages 로 buckets 를 다시 센다. duration 을 주면 그 길이만큼(최소) 버킷을 만든다."""
        if duration is not None and duration > 0:
            self.duration = float(duration)
        if bucket_sec is not None and bucket_sec > 0:
            self.bucket_sec = float(bucket_sec)
        self.buckets = self._count_into(self.messages, self.duration, self.bucket_sec)
        return self.buckets

    def bucket_at(self, t: float) -> int:
        """t 초가 속한 버킷의 메시지 수 (범위 밖이면 0)."""
        if not self.buckets or self.bucket_sec <= 0:
            return 0
        i = int(t // self.bucket_sec)
        return self.buckets[i] if 0 <= i < len(self.buckets) else 0

    def peaks(self, top_n: int = 20, min_gap: float = 60.0) -> list[float]:
        """반응이 가장 많은 버킷 top_n 개의 시작 시각 (서로 min_gap 초 이상 떨어진 것만), 시각순."""
        if not self.buckets and self.messages:
            self.build_buckets()
        return _select_peaks(self.buckets, self.bucket_sec, top_n, min_gap)

    def keyword_peaks(self, keywords: list[str], top_n: int = 20, min_gap: float = 60.0,
                      bucket_sec: float | None = None) -> list[float]:
        """키워드(대소문자 무시, 이모지 가능)가 들어간 메시지만 세서 가장 많은 버킷의 시작 시각."""
        keys = [k.casefold() for k in keywords if k and k.strip()]
        if not keys:
            return []
        bsec = float(bucket_sec) if bucket_sec and bucket_sec > 0 else self.bucket_sec
        hits = [m for m in self.messages if any(k in m[1].casefold() for k in keys)]
        if not hits:
            return []
        return _select_peaks(self._count_into(hits, self.duration, bsec), bsec, top_n, min_gap)

    # ---- 저장 / 복원 ----
    def to_json(self) -> dict:
        return {
            "version": 1,
            "source": self.source,
            "duration": self.duration,
            "bucket_sec": self.bucket_sec,
            "buckets": list(self.buckets),
            "messages": [[round(t, 3), text, user] for t, text, user in _cap_messages(self.messages, MAX_MESSAGES)],
        }

    @classmethod
    def from_json(cls, data: dict) -> "ChatData":
        msgs: list[Message] = []
        for m in data.get("messages", []) or []:
            try:
                msgs.append((float(m[0]), str(m[1]), str(m[2]) if len(m) > 2 else ""))
            except (TypeError, ValueError, IndexError):
                continue
        bsec = float(data.get("bucket_sec", DEFAULT_BUCKET_SEC) or DEFAULT_BUCKET_SEC)
        chat = cls(messages=msgs, bucket_sec=bsec,
                   buckets=[int(c) for c in data.get("buckets", []) or []],
                   duration=float(data.get("duration", 0.0) or 0.0), source=str(data.get("source", "") or ""))
        if not chat.buckets and chat.messages:
            chat.build_buckets()
        return chat

    @staticmethod
    def chat_file(video_path: str) -> str:
        return video_path + CHAT_SUFFIX

    def save(self, video_path: str) -> bool:
        try:
            with open(self.chat_file(video_path), "w", encoding="utf-8") as f:
                json.dump(self.to_json(), f, ensure_ascii=False, separators=(",", ":"))
            return True
        except OSError:
            LOG.exception("채팅 저장 실패: %s", video_path)
            return False

    @classmethod
    def load(cls, video_path: str) -> "ChatData | None":
        """<영상>.clipslicer.chat.json 이 있으면 읽고, 없거나 깨졌으면 None."""
        path = cls.chat_file(video_path)
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            LOG.warning("채팅 캐시 읽기 실패: %s", path)
            return None
        if not isinstance(data, dict):
            return None
        return cls.from_json(data)


# --------------------------------------------------------------------------- 주소 판별
def chzzk_video_no(text: str) -> str | None:
    """'https://chzzk.naver.com/video/15632692' 또는 '15632692' → '15632692'."""
    text = (text or "").strip()
    if text.isdigit():
        return text
    m = _CHZZK_RE.search(text)
    return m.group(1) if m else None


def detect_source(url: str) -> str | None:
    """'chzzk' | 'youtube' | None."""
    url = (url or "").strip()
    if not url:
        return None
    if chzzk_video_no(url) and "chzzk" in url.lower():
        return "chzzk"
    try:
        from urllib.parse import urlparse
        host = (urlparse(url if "://" in url else "https://" + url).hostname or "").lower()
    except ValueError:
        return None
    if _YT_HOST_RE.match(host):
        return "youtube"
    return None


# --------------------------------------------------------------------------- 치지직
def _http_json(url: str, timeout: float = 20.0, retries: int = HTTP_RETRIES, cancel: CancelCb | None = None) -> dict:
    """GET → JSON. HTTP/네트워크 오류는 1·2·4초 간격으로 다시 시도."""
    last: Exception | None = None
    for attempt in range(retries):
        if cancel and cancel():
            raise ChatError(tr("취소됨"))
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except (urllib.error.URLError, OSError, ValueError) as ex:  # HTTPError 는 URLError 의 하위
            last = ex
            LOG.warning("채팅 요청 실패 (%d/%d) %s: %s", attempt + 1, retries, url, ex)
            if attempt + 1 < retries:
                time.sleep(2 ** attempt)
    raise ChatError(tr("채팅 서버 응답 없음: {0}").format(last))


def _nickname(profile) -> str:
    if isinstance(profile, str):
        try:
            profile = json.loads(profile)
        except ValueError:
            return ""
    if isinstance(profile, dict):
        return str(profile.get("nickname") or profile.get("nickName") or "")
    return ""


def _parse_chzzk_page(obj: dict) -> tuple[list[Message], int | None]:
    """치지직 응답 JSON → ([(초, 내용, 닉네임)], 다음 playerMessageTime(ms) 또는 None). 필드 변형에 관대."""
    content = obj.get("content") if isinstance(obj, dict) else None
    if not isinstance(content, dict):
        content = obj if isinstance(obj, dict) else {}
    chats = content.get("videoChats") or content.get("videoChatMessages") or []
    out: list[Message] = []
    for ch in chats:
        if not isinstance(ch, dict):
            continue
        ms = ch.get("playerMessageTime")
        if ms is None:
            ms = ch.get("playerMessageTimeMs")
        if ms is None:
            continue
        text = ch.get("content")
        if text is None:
            text = ch.get("message") or ""
        try:
            out.append((int(ms) / 1000.0, str(text), _nickname(ch.get("profile"))))
        except (TypeError, ValueError):
            continue
    nxt = content.get("nextPlayerMessageTime")
    try:
        nxt = int(nxt) if nxt is not None else None
    except (TypeError, ValueError):
        nxt = None
    return out, nxt


def fetch_chzzk(video_no: str | int, duration: float, on_progress: ProgressCb | None = None,
                cancel: CancelCb | None = None, max_pages: int | None = None) -> ChatData:
    """치지직 다시보기 채팅 전체를 페이지 단위로 받는다. video_no 는 번호 또는 영상 주소."""
    no = chzzk_video_no(str(video_no))
    if not no:
        raise ChatError(tr("치지직 영상 번호를 찾을 수 없습니다: {0}").format(video_no))
    messages: list[Message] = []
    seen: set[tuple[float, str, str]] = set()
    cursor = 0
    pages = 0
    dur_ms = int(duration * 1000) if duration and duration > 0 else 0
    while True:
        if cancel and cancel():
            raise ChatError(tr("취소됨"))
        url = f"{CHZZK_API.format(video_no=no)}?playerMessageTime={cursor}&previousVideoChatSize={CHZZK_PAGE_SIZE}"
        obj = _http_json(url, cancel=cancel)
        code = obj.get("code") if isinstance(obj, dict) else None
        if code not in (None, 200):
            raise ChatError(tr("치지직 오류 {0}: {1}").format(code, obj.get("message") or ""))
        page, nxt = _parse_chzzk_page(obj)
        for m in page:
            if m not in seen:
                seen.add(m)
                messages.append(m)
        pages += 1
        if on_progress:
            frac = min(0.99, cursor / dur_ms) if dur_ms else 0.0
            on_progress(frac, tr("채팅 {0}개 받음 ({1})").format(len(messages), fmt_time(cursor / 1000.0, ms=False)))
        if not page or nxt is None or nxt <= cursor:
            break
        if dur_ms and nxt > dur_ms:
            break
        if max_pages is not None and pages >= max_pages:
            break
        cursor = nxt
    messages.sort(key=lambda m: m[0])
    chat = ChatData(messages=messages, source="chzzk")
    chat.build_buckets(duration if duration and duration > 0 else None)
    return chat


# --------------------------------------------------------------------------- 유튜브
def _run_text(run: dict) -> str:
    if "text" in run:
        return str(run.get("text") or "")
    emoji = run.get("emoji")
    if isinstance(emoji, dict):
        shortcuts = emoji.get("shortcuts") or []
        if emoji.get("isCustomEmoji") and shortcuts:
            return str(shortcuts[0])
        return str(emoji.get("emojiId") or (shortcuts[0] if shortcuts else ""))
    return ""


def _parse_live_chat_line(obj: dict) -> Message | None:
    """yt-dlp live_chat.json 한 줄(replayChatItemAction) → (초, 내용, 작성자) 또는 None."""
    if not isinstance(obj, dict):
        return None
    replay = obj.get("replayChatItemAction")
    if not isinstance(replay, dict):
        replay = obj
    offset = obj.get("videoOffsetTimeMsec")
    if offset is None:
        offset = replay.get("videoOffsetTimeMsec")
    if offset is None:
        return None
    try:
        t = int(float(offset)) / 1000.0
    except (TypeError, ValueError):
        return None
    for action in replay.get("actions") or []:
        item = ((action or {}).get("addChatItemAction") or {}).get("item") or {}
        renderer = item.get("liveChatTextMessageRenderer") or item.get("liveChatPaidMessageRenderer")
        if not renderer:
            continue
        msg = renderer.get("message") or {}
        if isinstance(msg, dict):
            text = "".join(_run_text(r) for r in msg.get("runs") or [] if isinstance(r, dict)) or str(msg.get("simpleText") or "")
        else:
            text = str(msg or "")
        author = renderer.get("authorName") or {}
        author = str(author.get("simpleText") or "") if isinstance(author, dict) else str(author or "")
        return (t, text, author)
    return None


def _parse_live_chat_file(path: str) -> list[Message]:
    out: list[Message] = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            m = _parse_live_chat_line(obj)
            if m is not None:
                out.append(m)
    return out


def fetch_youtube(url: str, on_progress: ProgressCb | None = None, cancel: CancelCb | None = None) -> ChatData:
    """yt-dlp 로 live_chat 자막(다시보기 채팅)만 받아 파싱한다. 채팅이 없으면 ChatError."""
    try:
        import yt_dlp
    except ImportError:
        raise ChatError(tr("yt-dlp 모듈이 없습니다 (pip install yt-dlp)"))
    try:
        from . import ytdlp_patches
        ytdlp_patches.apply()
    except Exception:  # 패치는 선택 사항
        LOG.debug("ytdlp_patches 적용 실패", exc_info=True)
    tmp = tempfile.mkdtemp(prefix="clipslicer_chat_")
    frags = {"n": 0}

    def hook(d):
        if cancel and cancel():
            raise yt_dlp.utils.DownloadCancelled()
        if d.get("status") == "downloading":
            frags["n"] += 1
            if on_progress:
                on_progress(min(0.9, 0.02 + frags["n"] * 0.005), tr("채팅 받는 중… {0}조각").format(frags["n"]))

    opts = {
        "skip_download": True,
        "writesubtitles": True,
        "subtitleslangs": ["live_chat"],
        "outtmpl": os.path.join(tmp, "%(id)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "progress_hooks": [hook],
        "retries": 3,
    }
    try:
        if on_progress:
            on_progress(0.0, tr("영상 정보 읽는 중…"))
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True) or {}
        if info.get("_type") == "playlist":
            info = (info.get("entries") or [None])[0] or info
        path = os.path.join(tmp, f"{info.get('id', '')}.live_chat.json")
        if not os.path.isfile(path):
            found = [n for n in os.listdir(tmp) if n.endswith(".live_chat.json")]
            path = os.path.join(tmp, found[0]) if found else ""
        if not path or not os.path.isfile(path):
            raise ChatError(tr("이 영상에는 다시보기 채팅이 없습니다 (라이브 방송 다시보기만 지원)"))
        if on_progress:
            on_progress(0.92, tr("채팅 정리 중…"))
        messages = _parse_live_chat_file(path)
        messages.sort(key=lambda m: m[0])
        chat = ChatData(messages=messages, source="youtube")
        chat.build_buckets(float(info.get("duration") or 0) or None)
        return chat
    except ChatError:
        raise
    except Exception as ex:
        if cancel and cancel():
            raise ChatError(tr("취소됨"))
        msg = str(ex)
        if "ERROR:" in msg:
            msg = msg.split("ERROR:", 1)[1].strip()
        raise ChatError(tr("유튜브 채팅 받기 실패: {0}").format(msg[:300]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def fetch(url: str, duration: float, on_progress: ProgressCb | None = None, cancel: CancelCb | None = None) -> ChatData:
    """주소 종류를 판별해 받는다. 영상 길이는 duration 으로 맞춘다."""
    source = detect_source(url)
    if source == "chzzk":
        chat = fetch_chzzk(url, duration, on_progress, cancel)
    elif source == "youtube":
        chat = fetch_youtube(url, on_progress, cancel)
    else:
        raise ChatError(tr("지원하지 않는 주소입니다 (치지직 다시보기 · 유튜브 라이브 다시보기만)"))
    if duration and duration > 0:
        chat.build_buckets(duration)
    return chat


# --------------------------------------------------------------------------- Qt
class ChatWorker(QThread):
    """URL + 영상 길이로 채팅을 받는다. progress(0~1, 상태글), done(ChatData 또는 None, 오류)."""
    progress = Signal(float, str)
    done = Signal(object, str)

    def __init__(self, url: str, duration: float, parent=None):
        super().__init__(parent)
        self.url, self.duration = url, duration
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            chat = fetch(self.url, self.duration, self.progress.emit, lambda: self._cancel)
        except ChatError as ex:
            self.done.emit(None, str(ex))
            return
        except Exception as ex:
            LOG.exception("채팅 받기 실패: %s", self.url)
            self.done.emit(None, str(ex)[:400])
            return
        if self._cancel:
            self.done.emit(None, tr("취소됨"))
            return
        LOG.info("채팅 %d개 (%s) %s", chat.count, chat.source, self.url)
        self.progress.emit(1.0, tr("완료"))
        self.done.emit(chat, "")


class ChatDialog(QDialog):
    """채팅 받기 + 마커 옵션. 결과는 .chat, .marker_times (ClipProject 는 바깥에서 적용)."""

    def __init__(self, parent=None, url: str = "", duration: float = 0.0, chat: ChatData | None = None,
                 top_n: int = 20, min_gap: float = 60.0, keywords: str = DEFAULT_KEYWORDS,
                 use_peaks: bool = True, use_keywords: bool = False):
        super().__init__(parent)
        self.setWindowTitle(tr("채팅 반응 그래프·마커"))
        self.resize(560, 420)
        self.duration = duration
        self.chat: ChatData | None = chat
        self.worker: ChatWorker | None = None
        lay = QVBoxLayout(self)
        intro = QLabel(tr("치지직 다시보기 또는 유튜브 라이브 다시보기 주소를 넣으면 채팅을 받아 타임라인에 반응 그래프를 그리고,\n"
                          "반응이 몰린 곳에 마커를 넣습니다. 채팅은 <영상>.clipslicer.chat.json 에 저장돼 다음에 바로 씁니다."))
        intro.setWordWrap(True)
        lay.addWidget(intro)
        row = QHBoxLayout()
        self.ed_url = QLineEdit(url)
        self.ed_url.setPlaceholderText("https://chzzk.naver.com/video/… · https://www.youtube.com/watch?v=…")
        row.addWidget(self.ed_url, 1)
        self.b_fetch = QPushButton(tr("채팅 가져오기"))
        self.b_fetch.clicked.connect(self._start)
        row.addWidget(self.b_fetch)
        self.b_stop = QPushButton(tr("중지"))
        self.b_stop.setEnabled(False)
        self.b_stop.clicked.connect(self._cancel)
        row.addWidget(self.b_stop)
        lay.addLayout(row)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setFormat(tr("대기 중"))
        lay.addWidget(self.progress)
        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        lay.addWidget(self.lbl_status)

        self.grp_peaks = QGroupBox(tr("반응 많은 곳에 마커"))
        self.grp_peaks.setCheckable(True)
        self.grp_peaks.setChecked(use_peaks)
        form = QFormLayout(self.grp_peaks)
        self.sp_top = QSpinBox()
        self.sp_top.setRange(1, 500)
        self.sp_top.setValue(max(1, int(top_n)))
        self.sp_top.setToolTip(tr("채팅이 가장 많이 쏟아진 시간대를 몇 곳 고를지"))
        form.addRow(tr("최대 개수"), self.sp_top)
        self.sp_gap = QDoubleSpinBox()
        self.sp_gap.setRange(5.0, 3600.0)
        self.sp_gap.setSingleStep(10.0)
        self.sp_gap.setDecimals(0)
        self.sp_gap.setSuffix(tr(" 초"))
        self.sp_gap.setValue(max(5.0, float(min_gap)))
        self.sp_gap.setToolTip(tr("이 간격보다 가까운 반응은 하나로 칩니다."))
        form.addRow(tr("마커 최소 간격"), self.sp_gap)
        lay.addWidget(self.grp_peaks)

        self.grp_kw = QGroupBox(tr("키워드 반응 마커"))
        self.grp_kw.setCheckable(True)
        self.grp_kw.setChecked(use_keywords)
        kform = QFormLayout(self.grp_kw)
        self.ed_kw = QLineEdit(keywords or DEFAULT_KEYWORDS)
        self.ed_kw.setToolTip(tr("쉼표로 구분. 대소문자 구분 없음, 이모지도 됩니다. 이 말이 들어간 채팅만 세서 가장 많은 곳에 마커"))
        kform.addRow(tr("키워드"), self.ed_kw)
        lay.addWidget(self.grp_kw)

        self.lbl_preview = QLabel("")
        self.lbl_preview.setStyleSheet("color: #8ab;")
        self.lbl_preview.setWordWrap(True)
        lay.addWidget(self.lbl_preview)
        lay.addStretch(1)

        self.bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.bb.button(QDialogButtonBox.Ok).setText(tr("마커 추가"))
        self.bb.button(QDialogButtonBox.Cancel).setText(tr("취소"))
        self.bb.accepted.connect(self.accept)
        self.bb.rejected.connect(self.reject)
        lay.addWidget(self.bb)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._update_preview)
        # 람다로 감싼다: valueChanged(int)/toggled(bool) 을 start 에 바로 이으면 start(msec) 로 풀려 간격이 바뀐다
        restart = lambda *_a: self._timer.start()  # noqa: E731
        for w in (self.sp_top, self.sp_gap):
            w.valueChanged.connect(restart)
        self.ed_kw.textChanged.connect(restart)
        self.grp_peaks.toggled.connect(restart)
        self.grp_kw.toggled.connect(restart)
        self.ed_url.returnPressed.connect(self._start)
        self._show_count()
        self._update_preview()

    # ---- 받기 ----
    def _start(self):
        if self.worker and self.worker.isRunning():
            return
        url = self.url
        if not detect_source(url):
            QMessageBox.warning(self, "URL", tr("치지직 다시보기(chzzk.naver.com/video/…) 또는 유튜브 주소를 넣어 주세요."))
            return
        self.b_fetch.setEnabled(False)
        self.b_stop.setEnabled(True)
        self.ed_url.setEnabled(False)
        self.lbl_status.setText("")
        self.progress.setValue(0)
        self.worker = ChatWorker(url, self.duration, self)
        self.worker.progress.connect(self._on_progress)
        self.worker.done.connect(self._on_done)
        self.worker.start()

    def _cancel(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.lbl_status.setText(tr("중지하는 중…"))

    def _on_progress(self, frac: float, text: str):
        self.progress.setValue(int(frac * 1000))
        self.progress.setFormat(f"%p%  {text}")

    def _on_done(self, chat, error: str):
        self.b_fetch.setEnabled(True)
        self.b_stop.setEnabled(False)
        self.ed_url.setEnabled(True)
        if chat is not None:
            if self.duration > 0:
                chat.build_buckets(self.duration)
            self.chat = chat
            self.progress.setFormat(tr("완료"))
            self._show_count()
        else:
            self.lbl_status.setText(tr("실패: ") + error)
            self.progress.setFormat(tr("실패"))
        self._update_preview()

    def _show_count(self):
        if self.chat is None:
            self.lbl_status.setText(tr("아직 받은 채팅이 없습니다."))
            return
        src = {"chzzk": tr("치지직"), "youtube": tr("유튜브")}.get(self.chat.source, self.chat.source or "-")
        self.lbl_status.setText(tr("채팅 {0}개 ({1}) · {2}초 단위 최대 {3}개").format(
            self.chat.count, src, int(self.chat.bucket_sec), self.chat.max_bucket))

    # ---- 결과 ----
    @property
    def url(self) -> str:
        return self.ed_url.text().strip()

    @property
    def top_n(self) -> int:
        return self.sp_top.value()

    @property
    def min_gap(self) -> float:
        return self.sp_gap.value()

    @property
    def keywords(self) -> str:
        return self.ed_kw.text().strip()

    @property
    def use_peaks(self) -> bool:
        return self.grp_peaks.isChecked()

    @property
    def use_keywords(self) -> bool:
        return self.grp_kw.isChecked()

    @property
    def peak_times(self) -> list[float]:
        if self.chat is None or not self.use_peaks:
            return []
        return self.chat.peaks(self.top_n, self.min_gap)

    @property
    def keyword_times(self) -> list[float]:
        if self.chat is None or not self.use_keywords:
            return []
        return self.chat.keyword_peaks(parse_keywords(self.keywords), self.top_n, self.min_gap)

    @property
    def marker_times(self) -> list[float]:
        """두 옵션의 합집합 (1초 안쪽 중복 제거, 시각순)."""
        out: list[float] = []
        for t in sorted(self.peak_times + self.keyword_times):
            if not out or t - out[-1] >= 1.0:
                out.append(t)
        return out

    def _update_preview(self):
        ok = self.chat is not None
        self.bb.button(QDialogButtonBox.Ok).setEnabled(ok)
        if not ok:
            self.lbl_preview.setText("")
            return
        np_, nk = len(self.peak_times), len(self.keyword_times)
        self.lbl_preview.setText(tr("예상 마커: 반응 {0}개 · 키워드 {1}개 → 합쳐서 {2}개").format(np_, nk, len(self.marker_times)))

    def done(self, result: int):
        w = self.worker
        if w and w.isRunning():
            w.cancel()
            if not w.wait(3000):
                # 아직 네트워크 대기 중이면 대화상자와 함께 지워지지 않게 떼어 두고 스스로 끝나게 둔다
                w.progress.disconnect(self._on_progress)
                w.done.disconnect(self._on_done)
                w.setParent(None)
                w.finished.connect(w.deleteLater)
            self.worker = None
        super().done(result)
