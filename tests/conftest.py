"""테스트 공통 설정."""
import os

import pytest


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
