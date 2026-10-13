"""게시/운영 기능: 프리셋 저장소, 예약 공개, 업로드 이력, 디스코드 웹훅 (네트워크 없이)."""
import datetime
import json
import os
import re
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QDateTime  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app import youtube as yt  # noqa: E402
from app import youtube_ui as ui  # noqa: E402
from app import upload_history as hist  # noqa: E402
from app import discord  # noqa: E402


class FakeSettings(dict):
    def value(self, k, d=None):
        return self.get(k, d)

    def setValue(self, k, v):
        self[k] = v


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """어떤 테스트도 실제 HTTP 를 타지 않도록."""
    import urllib.request

    def boom(*a, **k):
        raise AssertionError("network call attempted")
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    monkeypatch.setattr(yt, "is_connected", lambda: False)


def _items():
    return ui.make_items([
        ("C:/out/game_01.mp4", {"title": "game_01", "source": "stream", "start": 10.0, "end": 70.0, "n": ""}),
        ("C:/out/game_02.mp4", {"title": "game_02", "source": "stream", "start": 70.0, "end": 130.0, "n": ""}),
    ], "{source} 클립 ({start} ~ {end})")


# --------------------------------------------------------------------------- 프리셋
def test_preset_store_roundtrip():
    s = FakeSettings()
    store = ui.PresetStore(s)
    assert store.load() == [] and store.last == ""
    store.upsert({"name": "게임", "title": "{source} — {title}", "description": "설명, 쉼표 포함", "tags": "a, b", "category": "20", "shorts": True})
    store.upsert({"name": "브이로그", "title": "", "category": ""})
    assert isinstance(s["yt_presets"], str) and json.loads(s["yt_presets"])[0]["name"] == "게임"
    assert store.names() == ["게임", "브이로그"]
    assert store.get("게임")["tags"] == "a, b" and store.get("게임")["shorts"] is True
    assert store.get("브이로그") == {"name": "브이로그", "title": "", "description": "", "tags": "", "category": "", "shorts": False}
    store.upsert({"name": "게임", "title": "바뀜"})          # 같은 이름 → 교체
    assert store.names() == ["게임", "브이로그"] and store.get("게임")["title"] == "바뀜"
    store.last = "게임"
    assert store.last == "게임" and s["yt_last_preset"] == "게임"
    assert store.delete("게임") and store.names() == ["브이로그"] and store.last == ""
    assert not store.delete("없음")
    assert store.get("x") is None


def test_preset_store_tolerates_broken_values():
    s = FakeSettings(yt_presets="not json")
    assert ui.PresetStore(s).load() == []
    s = FakeSettings(yt_presets=json.dumps([{"name": ""}, "junk", {"name": "ok"}]))
    assert ui.PresetStore(s).names() == ["ok"]
    # ini 가 쉼표로 쪼개져 리스트로 돌아와도 복구
    raw = json.dumps([{"name": "a", "tags": "x, y"}], ensure_ascii=False)
    s = FakeSettings(yt_presets=raw.split(","))
    assert ui.PresetStore(s).names() == ["a"]


def test_apply_preset_and_reset():
    items = _items()
    n = ui.apply_preset(items, {"name": "p", "title": "[{n}] {source} — {title} ({start}~{end})", "description": "원본: {source}", "tags": "t1,t2"})
    assert n == 2
    assert items[0].title == "[01] stream — game_01 (00:10~01:10)" and items[1].title.startswith("[02] ")
    assert items[0].description == "원본: stream" and items[0].tags == "t1,t2"
    # 두 번 적용해도 {title} 은 원래 제목 기준
    ui.apply_preset(items, {"name": "p", "title": "{title}!"})
    assert items[0].title == "game_01!" and items[0].description == "stream 클립 (00:10 ~ 01:10)"   # 빈 설명 템플릿 → 원래 설명
    ui.apply_preset(items, {"name": "q"})
    assert items[0].title == "game_01" and items[0].description == "stream 클립 (00:10 ~ 01:10)" and items[0].tags == ""
    ui.apply_preset(items, {"name": "r", "title": "x" * 150})
    assert len(items[0].title) == 100
    items[0].reset()
    assert items[0].title == "game_01"


def test_preset_dialog_add_validate_save(app):
    s = FakeSettings()
    store = ui.PresetStore(s)
    store.upsert({"name": "기존", "title": "{title}"})
    d = ui.PresetDialog(None, store)
    assert d.list.count() == 1 and d.ed_name.text() == "기존"
    d._add()
    assert d.list.count() == 2 and d.list.currentRow() == 1
    d.ed_name.setText("기존")
    d._on_name("기존")
    assert "겹칩" in d.validate()
    d._on_name("")
    assert "비어" in d.validate()
    d._on_name("새것")
    d.ed_tags.setText("a,b")
    d._set("tags", "a,b")
    d.cb_cat.setCurrentIndex(d.cb_cat.findData("27"))
    d.cb_shorts.setChecked(True)
    assert d.validate() == ""
    d._save()
    assert store.names() == ["기존", "새것"]
    p = store.get("새것")
    assert p["tags"] == "a,b" and p["category"] == "27" and p["shorts"] is True
    d2 = ui.PresetDialog(None, store)
    d2.presets.pop(0)
    d2.list.takeItem(0)
    d2.reject()
    assert store.names() == ["기존", "새것"]   # 취소하면 안 바뀜


# --------------------------------------------------------------------------- 업로드 대화상자
def test_upload_dialog_presets_and_schedule(app):
    s = FakeSettings()
    ui.PresetStore(s).upsert({"name": "게임", "title": "{source} | {title}", "description": "D", "tags": "g", "category": "20", "shorts": False})
    s["yt_last_preset"] = "게임"
    items = _items()
    d = ui.UploadDialog(None, items, s)
    assert d.cb_preset.currentData() == "게임"
    assert items[0].title == "stream | game_01" and items[0].description == "D" and d.ed_title.text() == "stream | game_01"
    assert "게임" in d.log.toPlainText()
    d.cb_preset.setCurrentIndex(0)
    assert items[0].title == "game_01" and d.ed_title.text() == "game_01" and s["yt_last_preset"] == ""
    d.cb_preset.setCurrentIndex(d.cb_preset.findData("게임"))
    assert items[1].title == "stream | game_02" and s["yt_last_preset"] == "게임"
    # 예약 공개
    assert d._publish_at() is None and d.cb_privacy.isEnabled()
    d.dt_publish.setDateTime(QDateTime(2030, 6, 15, 12, 0, 0))
    d.cb_schedule.setChecked(True)
    assert not d.cb_privacy.isEnabled() and d.cb_privacy.currentData() == "private" and not d.lbl_schedule.isHidden()
    pa = d._publish_at()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", pa)
    back = datetime.datetime.strptime(pa, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc).astimezone().replace(tzinfo=None)
    assert back == datetime.datetime(2030, 6, 15, 12, 0)
    d.cb_schedule.setChecked(False)
    assert d._publish_at() is None and d.cb_privacy.isEnabled()
    assert d.channel_title == "" and d.b_history.isEnabled()
    d._close()


def test_upload_worker_records_history(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(hist, "history_path", lambda: str(tmp_path / "h.jsonl"))
    monkeypatch.setattr(yt, "upload_video", lambda path, meta, on_progress=None, cancel=None: (calls.append(meta), "vid123")[1])
    items = _items()
    w = ui.UploadWorker(items, "public", "20", "", publish_at="2030-01-01T00:00:00Z", channel="내 채널")
    done = []
    w.itemDone.connect(lambda i, v, e: done.append((i, v, e)))
    w.run()   # 같은 스레드에서 실행
    assert [v for _i, v, _e in done] == ["vid123", "vid123"]
    assert calls[0]["status"]["publishAt"] == "2030-01-01T00:00:00Z" and calls[0]["status"]["privacyStatus"] == "private"
    rows = hist.load()
    assert len(rows) == 2 and rows[0]["video_id"] == "vid123" and rows[0]["channel"] == "내 채널"
    assert rows[0]["privacy"] == "private" and rows[0]["publish_at"] == "2030-01-01T00:00:00Z"
    assert rows[1]["file"].endswith("game_02.mp4") and rows[1]["url"] == "https://youtu.be/vid123"


# --------------------------------------------------------------------------- 업로드 이력
def test_history_record_load(tmp_path):
    p = str(tmp_path / "sub" / "youtube_uploads.jsonl")
    assert hist.load(p) == []
    e = hist.record({"file": "C:/out/클립.mp4", "title": "제목", "video_id": "abc", "channel": "채널", "privacy": "private"}, p)
    assert e["url"] == "https://youtu.be/abc" and e["ts"] and len(e["ts"]) >= 19
    hist.record({"ts": "2030-01-02T03:04:05", "file": "b.mp4", "title": "둘", "video_id": "def", "url": "https://youtu.be/def",
                 "channel": "", "privacy": "public", "publish_at": "2030-02-01T00:00:00Z"}, p)
    with open(p, "a", encoding="utf-8") as f:
        f.write("{broken\n\n[1,2]\n")
    rows = hist.load(p)
    assert len(rows) == 2 and rows[0]["title"] == "제목" and rows[0]["file"] == "C:/out/클립.mp4"
    assert rows[1]["ts"] == "2030-01-02T03:04:05" and rows[1]["publish_at"] == "2030-02-01T00:00:00Z"
    with open(p, encoding="utf-8") as f:
        assert "클립" in f.read()   # ensure_ascii=False
    assert hist.normalize({})["ts"] and hist.normalize({"video_id": "x"})["url"] == "https://youtu.be/x"


def test_history_dialog(app, tmp_path):
    entries = [{"ts": "2030-01-01T10:00:00", "file": "C:/a/one.mp4", "title": "하나", "video_id": "v1", "url": "https://youtu.be/v1", "channel": "ch", "privacy": "private"},
               {"ts": "2030-01-02T10:00:00", "file": "C:/a/two.mp4", "title": "둘", "video_id": "v2", "url": "https://youtu.be/v2", "channel": "", "privacy": "public"}]
    d = hist.HistoryDialog(None, entries)
    assert d.table.rowCount() == 2 and d.table.item(0, hist.HistoryDialog.COL_TITLE).text() == "둘"   # 최신이 위
    assert d.table.item(0, hist.HistoryDialog.COL_DATE).text() == "2030-01-02 10:00"
    assert d.table.item(1, hist.HistoryDialog.COL_FILE).text() == "one.mp4" and d.table.item(1, hist.HistoryDialog.COL_LINK).text() == "https://youtu.be/v1"
    assert d.current()["video_id"] == "v2"
    d._copy_link()
    assert QApplication.clipboard().text() == "https://youtu.be/v2"
    empty = hist.HistoryDialog(None, [])
    assert empty.table.rowCount() == 0 and not empty.b_open.isEnabled() and empty.b_studio.isEnabled() and empty.current() is None


# --------------------------------------------------------------------------- 디스코드
def test_discord_url_validation():
    assert discord.is_webhook_url("https://discord.com/api/webhooks/123/abc")
    assert discord.is_webhook_url("  https://discordapp.com/api/webhooks/123/abc  ")
    assert not discord.is_webhook_url("https://discord.com/api/webhooks/")
    assert not discord.is_webhook_url("http://discord.com/api/webhooks/1/a")
    assert not discord.is_webhook_url("https://evil.com/discord.com/api/webhooks/1/a")
    assert not discord.is_webhook_url("") and not discord.is_webhook_url(None)
    with pytest.raises(discord.DiscordError):
        discord.test_webhook("https://example.com/hook")


def test_discord_multipart_body():
    body, ctype = discord.build_multipart({"payload_json": '{"content": "안녕"}'},
                                          [("files[0]", 'cl"ip\r\n.mp4', b"\x00\x01DATA", "video/mp4")], boundary="XYZ")
    assert ctype == "multipart/form-data; boundary=XYZ"
    assert body.startswith(b"--XYZ\r\nContent-Disposition: form-data; name=\"payload_json\"\r\n\r\n")
    assert '{"content": "안녕"}'.encode("utf-8") + b"\r\n--XYZ\r\n" in body
    assert b'Content-Disposition: form-data; name="files[0]"; filename="cl_ip__.mp4"\r\nContent-Type: video/mp4\r\n\r\n\x00\x01DATA\r\n' in body
    assert body.endswith(b"--XYZ--\r\n")
    body2, ctype2 = discord.build_multipart({}, [])
    assert ctype2.startswith("multipart/form-data; boundary=----ClipSlicer") and body2.endswith(b"--\r\n")


def test_discord_progress_body():
    got = []
    b = discord._ProgressBody(b"x" * 20, got.append, None)
    assert len(b) == 20
    assert b.read(8) == b"x" * 8 and b.read(8) == b"x" * 8 and b.read(8) == b"x" * 4 and b.read(8) == b""
    assert got[:3] == [0.4, 0.8, 1.0]
    c = discord._ProgressBody(b"x", None, lambda: True)
    with pytest.raises(discord.DiscordError):
        c.read(1)


def test_discord_size_check_without_network(tmp_path):
    f = tmp_path / "big.mp4"
    f.write_bytes(b"\0" * (2 * 1024 * 1024 + 1))
    url = "https://discord.com/api/webhooks/1/a"
    with pytest.raises(discord.DiscordError) as ei:
        discord.send_file(url, str(f), limit_mb=2)
    assert "2 MB" in str(ei.value)
    empty = tmp_path / "empty.mp4"
    empty.write_bytes(b"")
    with pytest.raises(discord.DiscordError):
        discord.send_file(url, str(empty), limit_mb=10)
    with pytest.raises(discord.DiscordError):
        discord.send_file("https://nope/", str(f))
    ok = tmp_path / "small.mp4"
    ok.write_bytes(b"\0" * 10)
    with pytest.raises(AssertionError):       # 크기 검사를 통과하면 네트워크(차단됨)까지 간다
        discord.send_file(url, str(ok), limit_mb=10)
    good, big = discord.split_by_limit([str(f), str(ok), str(tmp_path / "missing.mp4")], 2)
    assert good == [str(ok)] and big == [(str(f), 2 * 1024 * 1024 + 1)]


def test_discord_config_and_worker_content():
    assert discord.config(FakeSettings()) == {"webhook": "", "limit_mb": 10, "template": "{title}"}
    s = FakeSettings(discord_webhook=" https://discord.com/api/webhooks/1/a ", discord_limit_mb="50", discord_template="{title} / {source}")
    assert discord.config(s) == {"webhook": "https://discord.com/api/webhooks/1/a", "limit_mb": 50, "template": "{title} / {source}"}
    assert discord.config(FakeSettings(discord_limit_mb="junk"))["limit_mb"] == 10
    w = discord.DiscordWorker([("C:/out/clip_01.mp4", {"title": "clip_01", "source": "원본"})], "https://discord.com/api/webhooks/1/a",
                              template="📎 {title} ({source}) {nope}")
    assert w.content_for(*w.items[0]) == "📎 clip_01 (원본) {nope}"
    assert discord.DiscordWorker([], "u", template="").content_for("C:/x/stem.mp4", {}) == "stem"
    assert discord.attachment_url({"attachments": [{"url": "https://cdn/x.mp4"}]}) == "https://cdn/x.mp4"
    assert discord.attachment_url({}) == ""
    assert "한도" in discord._error_text(413, b"{}") and "삭제" in discord._error_text(404, b"{}")
    assert "한도" in discord._error_text(400, json.dumps({"code": 40005, "message": "big"}).encode())
    assert discord._error_text(500, b"oops") == "디스코드 오류 500: oops"


def test_discord_worker_runs_without_network(tmp_path, monkeypatch):
    f = tmp_path / "a.mp4"
    f.write_bytes(b"\0" * 10)
    sent = []
    w = discord.DiscordWorker([(str(f), {"title": "A", "source": "S"}), (str(tmp_path / "none.mp4"), {})],
                              "https://discord.com/api/webhooks/1/a", 10, "{title}-{source}")
    done, prog, fin = [], [], []
    w.fileDone.connect(lambda i, ok, m: done.append((i, ok, m)))
    w.fileProgress.connect(lambda i, p: prog.append((i, p)))
    w.allDone.connect(lambda ok, fail: fin.append((ok, fail)))
    monkeypatch.setattr(discord, "send_file", lambda url, path, *a, **k: (_ for _ in ()).throw(discord.DiscordError("없음")) if "none" in path
                        else (sent.append((path, a[0])), a[2](1.0), {"attachments": [{"url": "https://cdn/a.mp4"}]})[-1])
    w.run()
    assert sent == [(str(f), "A-S")] and prog == [(0, 1.0)]
    assert done == [(0, True, "https://cdn/a.mp4"), (1, False, "없음")] and fin == [(1, 1)]


def test_discord_settings_dialog(app):
    s = FakeSettings()
    d = discord.DiscordSettingsDialog(None, s)
    assert d.webhook == "" and d.limit_mb == 10 and d.template == "{title}"
    assert [d.cb_limit.itemData(i) for i in range(d.cb_limit.count())] == [10, 25, 50, 100]
    d.ed_url.setText("https://discord.com/api/webhooks/9/z")
    d.cb_limit.setCurrentIndex(2)
    d.ed_template.setPlainText("  {title} by {source}  ")
    d._save()
    assert s["discord_webhook"] == "https://discord.com/api/webhooks/9/z" and s["discord_limit_mb"] == 50 and s["discord_template"] == "{title} by {source}"
    d2 = discord.DiscordSettingsDialog(None, s)
    assert d2.webhook.endswith("/9/z") and d2.limit_mb == 50 and d2.template == "{title} by {source}"
    assert discord.DiscordSettingsDialog(None, None).limit_mb == 10
