"""yt-dlp 런타임 패치.

1) 치지직(네이버 VOD) 의 DASH 매니페스트는 yt-dlp 가 못 읽는 형식(Initialization range, 이슈 #8269)이라
   `KeyError: 'sourceURL'` 로 실패한다. 같은 매니페스트 안에 HLS 마스터 주소(nvod:m3u 속성)가 있으므로,
   그 오류가 나면 매니페스트를 다시 읽어 HLS 포맷으로 대신한다. 다른 사이트에는 영향 없음.
"""
from __future__ import annotations

from .i18n import tr
import logging
import urllib.parse

LOG = logging.getLogger("clipslicer")
_applied = False


def find_m3u_url(mpd_doc) -> str | None:
    """MPD 트리에서 이름이 'm3u' 로 끝나는 속성 값(HLS 주소)을 찾는다."""
    if mpd_doc is None:
        return None
    for el in mpd_doc.iter():
        for key, val in el.attrib.items():
            if key.endswith("m3u") and isinstance(val, str) and val.startswith("http"):
                return val
    return None


def _is_source_url_error(ex: BaseException) -> bool:
    seen = set()
    while ex is not None and id(ex) not in seen:
        seen.add(id(ex))
        if isinstance(ex, KeyError) and str(ex) == "'sourceURL'":
            return True
        ex = getattr(ex, "cause", None) or ex.__cause__ or ex.__context__
    return False


def apply():
    global _applied
    if _applied:
        return
    try:
        from yt_dlp.extractor.common import InfoExtractor
    except ImportError:
        return

    orig_extract = InfoExtractor._extract_mpd_formats_and_subtitles
    orig_parse = InfoExtractor._parse_mpd_formats_and_subtitles

    def hls_from_doc(self, mpd_doc, video_id):
        m3u = find_m3u_url(mpd_doc)
        if not m3u:
            return None
        LOG.info("DASH 매니페스트 해석 실패 → HLS 로 우회: %s", m3u[:90])
        fmts, subs = self._extract_m3u8_formats_and_subtitles(m3u, video_id, "mp4", m3u8_id="hls", fatal=False)
        if not fmts:
            return None
        # 네이버 VOD 는 서명 토큰(?_lsu_sa_=…)이 붙은 주소만 응답한다.
        # 마스터 주소의 쿼리를 하위 재생 목록과 모든 세그먼트 주소에 이어 붙인다.
        query = urllib.parse.urlparse(m3u).query
        if query:
            for f in fmts:
                url = f.get("url") or ""
                if url and query not in url:
                    f["url"] = url + ("&" if "?" in url else "?") + query
                f["extra_param_to_segment_url"] = query
        return fmts, subs

    def patched_extract(self, mpd_url, video_id, mpd_id=None, note=None, errnote=None,
                        fatal=True, data=None, headers={}, query={}):
        try:
            return orig_extract(self, mpd_url, video_id, mpd_id=mpd_id, note=note, errnote=errnote,
                                fatal=fatal, data=data, headers=headers, query=query)
        except Exception as ex:
            if not _is_source_url_error(ex):
                raise
            doc = self._download_xml(mpd_url, video_id, note=tr("HLS 주소 찾는 중"), fatal=False,
                                     data=data, headers=headers, query=query)
            res = hls_from_doc(self, doc, video_id)
            if res is None:
                raise
            return res

    def patched_parse(self, mpd_doc, mpd_id=None, mpd_base_url="", mpd_url=None):
        try:
            return orig_parse(self, mpd_doc, mpd_id, mpd_base_url, mpd_url)
        except Exception as ex:
            if not _is_source_url_error(ex):
                raise
            res = hls_from_doc(self, mpd_doc, mpd_id or "hls")
            if res is None:
                raise
            return res

    InfoExtractor._extract_mpd_formats_and_subtitles = patched_extract
    InfoExtractor._parse_mpd_formats_and_subtitles = patched_parse
    _applied = True
