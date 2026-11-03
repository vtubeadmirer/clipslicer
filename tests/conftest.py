"""테스트 공통 설정."""
import gc
import os

import pytest


@pytest.fixture(autouse=True)
def _collect_on_main_thread():
    """테스트가 남긴 Qt 객체를 메인 스레드에서 치운다. 다음 테스트의 HTTP 서버 스레드에서 GC 가 돌면 Qt 가 비정상 종료한다."""
    yield
    gc.collect()


@pytest.fixture(autouse=True, scope="session")
def _isolated_appdata(tmp_path_factory):
    """분석 캐시 · 작업 파일 백업은 %LOCALAPPDATA%\\ClipSlicer 에 쌓인다 → 테스트는 임시 폴더로 (사용자 데이터와 섞이지 않게)."""
    old = os.environ.get("LOCALAPPDATA")
    os.environ["LOCALAPPDATA"] = str(tmp_path_factory.mktemp("localappdata"))
    yield
    if old is None:
        os.environ.pop("LOCALAPPDATA", None)
    else:
        os.environ["LOCALAPPDATA"] = old
