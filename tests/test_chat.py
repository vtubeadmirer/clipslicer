"""채팅 반응 그래프·키워드 마커: 버킷, 피크, JSON 저장/복원, 주소 판별, 치지직/유튜브 파서, 대화상자, 타임라인 그리기."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import chat as ch  # noqa: E402
from app.chat import ChatData, ChatError  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def msgs(*times, text="hi", user="u"):
    return [(float(t), text, user) for t in times]


# ---- 버킷 ----
def test_build_buckets():
    c = ChatData(messages=msgs(1, 2, 12, 25, 25.5))
    assert c.build_buckets(30.0, 10.0) == [2, 1, 2]
    assert c.duration == 30.0 and c.bucket_sec == 10.0
    # 길이를 모르면 마지막 메시지까지, 범위 밖/음수는 양 끝 버킷으로
    c = ChatData(messages=msgs(-3, 0, 9.99, 10, 35))
    assert c.build_buckets(30.0, 10.0) == [3, 1, 1]  # 30초 길이: 35초 메시지는 마지막 버킷, 음수는 첫 버킷
    c = ChatData(messages=msgs(5, 33))
    assert c.build_buckets(bucket_sec=10.0) == [1, 0, 0, 1]
    assert ChatData().build_buckets(0.0, 10.0) == [0]
    assert c.bucket_at(33) == 1 and c.bucket_at(15) == 0 and c.bucket_at(999) == 0
    assert c.max_bucket == 1 and c.count == 2


def test_peaks_respect_gap_and_top_n():
    c = ChatData(buckets=[0, 5, 1, 9, 2, 8, 0, 0, 7], bucket_sec=10.0)
    assert c.peaks(top_n=3, min_gap=15.0) == [30.0, 50.0, 80.0]
    assert c.peaks(top_n=3, min_gap=25.0) == [30.0, 80.0]
    assert c.peaks(top_n=1, min_gap=60.0) == [30.0]
    assert c.peaks(top_n=0) == [] and ChatData().peaks() == []
    assert ChatData(buckets=[0, 0, 0], bucket_sec=10.0).peaks() == []
    # 동점이면 앞선 시각 먼저
    assert ChatData(buckets=[4, 4, 4], bucket_sec=10.0).peaks(top_n=2, min_gap=5.0) == [0.0, 10.0]
    # buckets 가 비어 있으면 messages 로 자동 계산
    c = ChatData(messages=msgs(1, 2, 3, 41, 42))
    assert c.peaks(top_n=5, min_gap=10.0) == [0.0, 40.0]


def test_keyword_peaks_case_insensitive_and_emoji():
    m = msgs(100, 101, 102, 105, text="ㅋㅋㅋㅋㅋㅋ") + msgs(300, 302, text="아 미쳤다 진짜") + msgs(300, text="GG")
    m += msgs(500, 501, 502, 503, text="😂😂😂") + msgs(700, 701, 702, 703, 704, 705, text="평범한 채팅")
    c = ChatData(messages=m)
    c.build_buckets(800.0, 10.0)
    assert c.keyword_peaks(["ㅋㅋㅋ", "미쳤다"], top_n=5, min_gap=60.0) == [100.0, 300.0]
    assert c.keyword_peaks(["gg"], top_n=5) == [300.0]
    assert c.keyword_peaks(["😂"], top_n=5) == [500.0]
    assert c.keyword_peaks(["없는말"]) == [] and c.keyword_peaks([]) == [] and c.keyword_peaks(["", "  "]) == []
    # 다른 버킷 크기로 세기 (30초 버킷이면 100~102·105 가 90초 버킷에)
    assert c.keyword_peaks(["ㅋㅋㅋ"], top_n=5, bucket_sec=30.0) == [90.0]
    assert c.peaks(top_n=1) == [700.0]  # 전체 반응은 평범한 채팅이 가장 많음


def test_parse_keywords_and_cap():
    assert ch.parse_keywords("ㅋㅋㅋ, 미쳤다,, 클립 ,레전드\nㄷㄷ, ㅋㅋㅋ") == ["ㅋㅋㅋ", "미쳤다", "클립", "레전드", "ㄷㄷ"]
    assert ch.parse_keywords("") == []
    m = msgs(*range(100))
    capped = ch._cap_messages(m, 10)
    assert len(capped) == 10 and capped[0][0] == 0.0 and capped[-1][0] == 90.0
    assert ch._cap_messages(m, 1000) == m


# ---- 저장 / 복원 ----
def test_json_roundtrip_and_save_load(tmp_path):
    c = ChatData(messages=msgs(1, 2, 12, text="ㅋㅋ", user="닉"), source="chzzk")
    c.build_buckets(30.0, 10.0)
    d = c.to_json()
    assert d["buckets"] == [2, 1, 0] and d["bucket_sec"] == 10.0 and d["messages"][0] == [1.0, "ㅋㅋ", "닉"]
    assert json.loads(json.dumps(d, ensure_ascii=False)) == d
    q = ChatData.from_json(d)
    assert q.messages == c.messages and q.buckets == c.buckets and q.duration == 30.0 and q.source == "chzzk"
    # buckets 없이 들어오면 다시 센다, 깨진 메시지는 건너뜀
    q = ChatData.from_json({"messages": [[5, "a", "b"], ["x", "bad"], [15, "c"]], "bucket_sec": 10})
    assert q.messages == [(5.0, "a", "b"), (15.0, "c", "")] and q.buckets == [1, 1]
    video = str(tmp_path / "v.mp4")
    assert ChatData.load(video) is None
    assert c.save(video)
    assert os.path.isfile(video + ch.CHAT_SUFFIX)
    q = ChatData.load(video)
    assert q is not None and q.messages == c.messages and q.buckets == [2, 1, 0]
    with open(video + ch.CHAT_SUFFIX, "w", encoding="utf-8") as f:
        f.write("{broken")
    assert ChatData.load(video) is None


def test_save_caps_messages(tmp_path, monkeypatch):
    monkeypatch.setattr(ch, "MAX_MESSAGES", 50)
    c = ChatData(messages=msgs(*range(200)))
    c.build_buckets(200.0, 10.0)
    video = str(tmp_path / "v.mp4")
    assert c.save(video)
    q = ChatData.load(video)
    assert len(q.messages) == 50 and q.buckets == c.buckets  # 버킷은 전체 기준 그대로


# ---- 주소 판별 ----
def test_detect_source_and_video_no():
    assert ch.detect_source("https://chzzk.naver.com/video/15632692") == "chzzk"
    assert ch.detect_source("chzzk.naver.com/video/1?x=1") == "chzzk"
    assert ch.detect_source("https://www.youtube.com/watch?v=abc") == "youtube"
    assert ch.detect_source("https://youtu.be/abc") == "youtube"
    assert ch.detect_source("https://m.youtube.com/live/abc") == "youtube"
    assert ch.detect_source("https://chzzk.naver.com/live/abc") is None
    assert ch.detect_source("https://twitch.tv/videos/1") is None
    assert ch.detect_source("") is None and ch.detect_source("15632692") is None
    assert ch.chzzk_video_no("https://chzzk.naver.com/video/15632692") == "15632692"
    assert ch.chzzk_video_no("https://chzzk.naver.com/ko/video/77?t=1") == "77"
    assert ch.chzzk_video_no(" 123 ") == "123" and ch.chzzk_video_no("https://youtu.be/x") is None


# ---- 치지직 파서 ----
def test_parse_chzzk_page():
    page = {"code": 200, "message": None, "content": {
        "previousVideoChats": [], "nextPlayerMessageTime": 353246,
        "videoChats": [
            {"playerMessageTime": 7516, "content": "ㅋㅋㅋ", "messageTypeCode": 1,
             "profile": json.dumps({"userIdHash": "x", "nickname": "닉네임", "userRoleCode": "common_user"})},
            {"playerMessageTime": 9123, "content": "{:niniaoPuck:}", "profile": {"nickname": "딕트"}},
            {"playerMessageTime": "14454", "content": "문자열 ms", "profile": "not json"},
            {"content": "시각 없음"},
            "garbage",
        ]}}
    out, nxt = ch._parse_chzzk_page(page)
    assert out == [(7.516, "ㅋㅋㅋ", "닉네임"), (9.123, "{:niniaoPuck:}", "딕트"), (14.454, "문자열 ms", "")]
    assert nxt == 353246
    # 필드 변형: videoChatMessages / message, next 없음, content 가 바로 최상위
    out, nxt = ch._parse_chzzk_page({"videoChatMessages": [{"playerMessageTime": 1000, "message": "m"}]})
    assert out == [(1.0, "m", "")] and nxt is None
    assert ch._parse_chzzk_page({"content": {"videoChats": [], "nextPlayerMessageTime": None}}) == ([], None)
    assert ch._parse_chzzk_page({}) == ([], None)


def test_fetch_chzzk_paginates_and_dedupes(monkeypatch):
    pages = {
        0: {"content": {"videoChats": [{"playerMessageTime": 1000, "content": "a"}, {"playerMessageTime": 2000, "content": "b"}],
                        "nextPlayerMessageTime": 2000}},
        2000: {"content": {"videoChats": [{"playerMessageTime": 2000, "content": "b"}, {"playerMessageTime": 3000, "content": "c"}],
                           "nextPlayerMessageTime": 3000}},
        3000: {"content": {"videoChats": [{"playerMessageTime": 3000, "content": "c"}], "nextPlayerMessageTime": 3000}},
    }
    calls = []

    def fake(url, timeout=20.0, retries=3, cancel=None):
        calls.append(url)
        cursor = int(url.split("playerMessageTime=")[1].split("&")[0])
        return pages[cursor]

    monkeypatch.setattr(ch, "_http_json", fake)
    prog = []
    c = ch.fetch_chzzk("https://chzzk.naver.com/video/15632692", 100.0, lambda f, t: prog.append((f, t)))
    assert [m[0] for m in c.messages] == [1.0, 2.0, 3.0] and c.source == "chzzk"
    assert len(c.buckets) == 10 and c.buckets[0] == 3
    assert "15632692/chats?playerMessageTime=0&previousVideoChatSize=50" in calls[0]
    assert len(calls) == 3 and prog and prog[-1][0] <= 0.99
    calls.clear()
    assert ch.fetch_chzzk("15632692", 100.0, max_pages=1).count == 2 and len(calls) == 1
    # 영상 길이를 넘는 커서는 더 받지 않음
    calls.clear()
    assert ch.fetch_chzzk("15632692", 1.5).count == 2 and len(calls) == 1
    with pytest.raises(ChatError):
        ch.fetch_chzzk("https://youtu.be/x", 10.0)
    with pytest.raises(ChatError):
        ch.fetch_chzzk("15632692", 100.0, cancel=lambda: True)


def test_http_json_retries(monkeypatch):
    import urllib.error
    attempts = []

    def fail(req, timeout=0):
        attempts.append(req.get_header("User-agent"))
        raise urllib.error.URLError("down")

    monkeypatch.setattr(ch.urllib.request, "urlopen", fail)
    monkeypatch.setattr(ch.time, "sleep", lambda s: None)
    with pytest.raises(ChatError):
        ch._http_json("https://example.invalid/x")
    assert len(attempts) == 3 and attempts[0] == "Mozilla/5.0"


# ---- 유튜브 파서 ----
def _yt_line(offset_ms, runs, author="작성자", renderer="liveChatTextMessageRenderer", top_offset=True):
    item = {renderer: {"message": {"runs": runs}, "authorName": {"simpleText": author}, "id": "x"}}
    line = {"replayChatItemAction": {"actions": [{"addChatItemAction": {"item": item}}],
                                     "videoOffsetTimeMsec": str(offset_ms)}, "isLive": False}
    if top_offset:
        line["videoOffsetTimeMsec"] = str(offset_ms)
    return line


def test_parse_live_chat_line():
    runs = [{"text": "레전드 "}, {"emoji": {"emojiId": "😂", "shortcuts": [":joy:"], "isCustomEmoji": False}},
            {"emoji": {"emojiId": "UC/abc", "shortcuts": [":_yt:"], "isCustomEmoji": True}}]
    assert ch._parse_live_chat_line(_yt_line(12345, runs)) == (12.345, "레전드 😂:_yt:", "작성자")
    assert ch._parse_live_chat_line(_yt_line(500, [{"text": "paid"}], renderer="liveChatPaidMessageRenderer")) == (0.5, "paid", "작성자")
    assert ch._parse_live_chat_line(_yt_line(700, [{"text": "inner"}], top_offset=False)) == (0.7, "inner", "작성자")
    # 오프셋 없음 / 메시지 없는 액션 / 쓰레기
    assert ch._parse_live_chat_line({"replayChatItemAction": {"actions": []}}) is None
    assert ch._parse_live_chat_line({"videoOffsetTimeMsec": "100", "replayChatItemAction": {"actions": [{"addChatItemAction": {"item": {"liveChatMembershipItemRenderer": {}}}}]}}) is None
    assert ch._parse_live_chat_line("nope") is None


def test_parse_live_chat_file(tmp_path):
    p = tmp_path / "x.live_chat.json"
    lines = [json.dumps(_yt_line(1000, [{"text": "a"}]), ensure_ascii=False), "", "not json",
             json.dumps(_yt_line(2000, [{"text": "b"}]), ensure_ascii=False)]
    p.write_text("\n".join(lines), encoding="utf-8")
    assert [m[:2] for m in ch._parse_live_chat_file(str(p))] == [(1.0, "a"), (2.0, "b")]


def test_fetch_youtube_without_chat_raises(monkeypatch, tmp_path):
    yt_dlp = pytest.importorskip("yt_dlp")

    class FakeYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download=True):
            assert self.opts["skip_download"] and self.opts["subtitleslangs"] == ["live_chat"]
            return {"id": "vid", "duration": 42}

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL)
    with pytest.raises(ChatError) as ei:
        ch.fetch_youtube("https://www.youtube.com/watch?v=vid")
    assert "채팅" in str(ei.value)

    class FakeYDL2(FakeYDL):
        def extract_info(self, url, download=True):
            path = os.path.join(os.path.dirname(self.opts["outtmpl"]), "vid.live_chat.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write(json.dumps(_yt_line(3000, [{"text": "ㅋㅋㅋ"}])) + "\n")
            return {"id": "vid", "duration": 42}

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL2)
    c = ch.fetch_youtube("https://www.youtube.com/watch?v=vid")
    assert c.messages == [(3.0, "ㅋㅋㅋ", "작성자")] and c.source == "youtube" and len(c.buckets) == 5
    assert ch.detect_source("https://www.youtube.com/watch?v=vid") == "youtube"


# ---- 네트워크 (실패하면 건너뜀) ----
@pytest.mark.skipif(os.environ.get("CLIPSLICER_OFFLINE") == "1", reason="오프라인")
def test_fetch_chzzk_network_first_pages():
    prog = []
    try:
        c = ch.fetch_chzzk("https://chzzk.naver.com/video/15632692", 36670.0, lambda f, t: prog.append(f), max_pages=2)
    except (ChatError, OSError) as ex:
        pytest.skip(f"네트워크 없음: {ex}")
    assert 0 < c.count <= 1000 and c.source == "chzzk"
    assert all(a[0] <= b[0] for a, b in zip(c.messages, c.messages[1:]))
    assert len(c.buckets) == 3667 and sum(c.buckets) == c.count
    assert prog and all(0.0 <= f <= 0.99 for f in prog)
    assert c.peaks(top_n=3, min_gap=60.0)


# ---- Qt ----
def test_chat_dialog_offscreen(qapp):
    from PySide6.QtWidgets import QDialogButtonBox
    c = ChatData(messages=msgs(1, 2, 3, 100, 101, text="ㅋㅋㅋ") + msgs(300, 301, 302, 303, text="zzz"))
    c.build_buckets(400.0, 10.0)
    d = ch.ChatDialog(None, url="https://chzzk.naver.com/video/1", duration=400.0, chat=c, top_n=2, min_gap=60.0)
    assert d.url == "https://chzzk.naver.com/video/1" and d.chat is c
    assert d.use_peaks and not d.use_keywords and d.top_n == 2 and d.min_gap == 60.0
    assert d.keywords == ch.DEFAULT_KEYWORDS
    assert d.peak_times == [0.0, 300.0] and d.keyword_times == [] and d.marker_times == [0.0, 300.0]
    assert d.bb.button(QDialogButtonBox.Ok).isEnabled()
    assert "9" in d.lbl_status.text()  # 채팅 9개
    d.grp_kw.setChecked(True)
    assert d.keyword_times == [0.0, 100.0] and d.marker_times == [0.0, 100.0, 300.0]
    d.grp_peaks.setChecked(False)
    d.sp_top.setValue(1)
    assert d.marker_times == [0.0]
    d._update_preview()
    assert "1" in d.lbl_preview.text()
    # 채팅 없으면 확인 버튼 비활성
    e = ch.ChatDialog(None, url="", duration=10.0)
    assert e.chat is None and e.marker_times == [] and not e.bb.button(QDialogButtonBox.Ok).isEnabled()
    assert e.worker is None
    e.done(0)
    d.done(0)


def test_chat_worker_instantiates(qapp):
    w = ch.ChatWorker("https://chzzk.naver.com/video/1", 10.0)
    assert w.url and w.duration == 10.0
    w.cancel()
    assert w._cancel


def test_timeline_draws_chat_graph(qapp):
    from PySide6.QtGui import QImage
    from app.segments import ClipProject
    from app.timeline import TimelineCanvas, THUMB_H

    def orange_pixels(canvas) -> int:
        img = canvas.grab().toImage().convertToFormat(QImage.Format_RGB32)
        n = 0
        for y in range(int(THUMB_H * 0.5), THUMB_H - 4):
            for x in range(img.width()):
                c = img.pixelColor(x, y)
                if c.red() > 150 and c.red() > c.green() + 20 and c.green() > c.blue() + 20:
                    n += 1
        return n

    proj = ClipProject(path="C:/video/sample.mp4", duration=100.0)
    proj.rebuild_segments()
    canvas = TimelineCanvas()
    canvas.resize(400, THUMB_H + 30)
    canvas.set_project(proj)
    assert canvas._chat_buckets() == ([], 0.0)
    assert orange_pixels(canvas) == 0
    chat = ChatData(buckets=[0, 1, 5, 20, 2, 0, 0, 0, 0, 3], bucket_sec=10.0, duration=100.0)
    proj.chat = chat
    assert canvas._chat_buckets() == (chat.buckets, 10.0)
    assert orange_pixels(canvas) > 50
    # 확대·스크롤해도 그려지고 x_to_t 범위를 벗어나지 않음
    canvas.zoom(4.0, 35.0)
    assert canvas.view_len < 100.0
    assert orange_pixels(canvas) > 50
    proj.chat = ChatData(buckets=[0, 0, 0], bucket_sec=10.0)
    assert orange_pixels(canvas) == 0
    proj.chat = "garbage"
    assert canvas._chat_buckets() == ([], 0.0) and orange_pixels(canvas) == 0
    canvas.popup.hide()
