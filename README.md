# ClipSlicer

[![CI](https://github.com/vtubeadmirer/clipslicer/actions/workflows/ci.yml/badge.svg)](https://github.com/vtubeadmirer/clipslicer/actions/workflows/ci.yml) [![Release](https://github.com/vtubeadmirer/clipslicer/actions/workflows/release.yml/badge.svg)](https://github.com/vtubeadmirer/clipslicer/releases)

영상을 재생하다가 멈춘 지점에 가위 표시만 찍으면, 구간별로 각각 저장해 주는 가벼운 Windows 영상 자르기 도구입니다.
ffmpeg + libmpv + PySide6 로 만들었습니다.

- **마커 하나 = 자르기 한 번.** In/Out 점 없이, 자를 지점만 찍으면 사이사이가 구간이 됩니다.
- 기본은 **재인코딩 없이 원본을 그대로 끊어 내는 빠르게 모드**. 시작점을 프레임 단위로 맞춰야 하면 스마트 / 정확하게 모드.
- **클립 모드 (I/O)**: 쓸 부분만 뽑기. 시작에서 I, 끝에서 O 면 그 사이만 켜짐
- 썸네일 띠 · 오디오 파형 · 키프레임 표시, Ctrl+휠 확대, 호버 썸네일 미리보기, 분석 결과 캐시
- 실행 취소 / 다시 실행, 작업 자동 저장 (`영상.clipslicer.json`)
- 무음 구간 · 장면 전환 자동 마커, 타임스탬프 텍스트 붙여넣기 → 마커, 챕터 목록 복사
- 켜진 구간 하나로 합치기, 오디오만 추출 (m4a / mp3), **세로 9:16 쇼츠 출력**, 현재 화면 PNG 저장
- **URL 에서 열기** (yt-dlp 내장: 유튜브 · 치지직 · 트위치 등)
- **업데이트 알림**: 새 릴리스가 있으면 버튼이 뜨고, 누르면 받아서 검증·교체·재실행까지 자동
- GPU 인코딩 (NVENC / QSV / AMF 자동 감지), 여러 영상 한 번에 처리, 파일명 규칙

자세한 사용법은 **[docs/index.html](docs/index.html)** 또는 앱 안의 도움말(F1)에 있습니다.

## 빠른 사용법

1. 영상을 창에 끌어다 놓거나 `Ctrl+O` 로 엽니다. (여러 개, 폴더도 가능)
2. 재생하다가 자를 지점에서 `S` 를 누르면 빨간 마커가 생깁니다. `←` `→` 로 한 프레임씩 다듬을 수 있습니다.
3. 필요 없는 구간은 타임라인에서 `Ctrl+클릭` 하거나 오른쪽 목록의 체크를 끕니다.
4. `Ctrl+E` → 켜진 구간이 `원본이름_01.mp4`, `_02.mp4` … 로 저장됩니다.

| 키 | 동작 |
|---|---|
| Space / K | 재생 · 정지 |
| ← → | 한 프레임 이동 |
| Shift+← → / Ctrl+← → | 1초 / 10초 이동 |
| S | 현재 위치에 자르기 마커 |
| I / O | 클립 시작 / 끝 (사이만 켜기) |
| Delete | 가까운 마커 삭제 |
| Ctrl+Z / Ctrl+Y | 실행 취소 / 다시 실행 |
| E | 현재 구간 켜기/끄기 |
| R | 현재 위치 앞뒤 2초 돌려보기 |
| L | 현재 구간 반복 재생 |
| ↑ ↓ | 이전 / 다음 구간 |
| [ ] \ | 재생 속도 |
| Ctrl+휠 / Ctrl+0 | 타임라인 확대 / 전체 보기 |
| Ctrl+Shift+M / Ctrl+Shift+S | 무음 / 장면 전환 자동 마커 |
| Ctrl+Shift+V | 타임스탬프 붙여넣기 → 마커 |
| Ctrl+L | URL 에서 열기 |
| Ctrl+P | 현재 화면 PNG 저장 |
| Ctrl+E | 모든 영상 내보내기 |
| F1 | 도움말 |

## 자르기 모드

| 모드 | 속도 | 정확도 | 설명 |
|---|---|---|---|
| 빠르게 (기본) | 즉시 | 시작점이 앞 키프레임까지 당겨짐 (보통 1~2초) | `-c copy` 무손실 복사. 원본을 그대로 끊어 냄 |
| 스마트 | 빠름 | 프레임 단위 | 시작~첫 키프레임만 재인코딩 + 나머지 복사 + 이어 붙이기 (H.264/HEVC) |
| 정확하게 | 느림 | 프레임 단위 | 전체 재인코딩 (H.264 CRF 18) |

## 개발 환경 설정

```
pip install -r requirements.txt
python tools\get_libmpv.py        # bin\libmpv-2.dll 다운로드 (7-Zip 또는 Bandizip 필요)
python tools\get_ffmpeg.py        # bin\ffmpeg\ 공유 빌드 다운로드 (버전 고정)
python tools\make_icon.py         # assets\icon.ico 생성 (선택)
```

ffmpeg 는 `tools\get_ffmpeg.py` 가 받는 공유 빌드(`bin\ffmpeg\`)를 우선 쓰고, 없으면 PATH 의 ffmpeg 를 씁니다.

실행: `python main.py` 또는 `run.bat`

## 배포용 빌드

### GitHub Actions 로 자동 빌드

`v0.2.0` 같은 태그를 push 하면 Actions 가 ffmpeg·libmpv 를 받아 exe 를 빌드하고 zip 을 [Releases](https://github.com/vtubeadmirer/clipslicer/releases) 에 올립니다.

```
git tag v0.2.0
git push origin v0.2.0
```

### 로컬 빌드

```
.\build.ps1
```

`dist\ClipSlicer\ClipSlicer.exe` 가 만들어집니다. ffmpeg(공유 빌드), libmpv 가 같이 들어가고, 빌드 끝에 번들된 ffmpeg 가 PATH 없이 뜨는지 검증합니다.
설치 없이 폴더째 복사해서 쓰는 **포터블** 구조이며, 설정은 폴더 안 `settings.ini` 에 저장됩니다.

## 문제가 생기면

- 오류는 `logs\clipslicer.log` 에 남고(프로그램 폴더, 쓸 수 없으면 `%LOCALAPPDATA%\ClipSlicer\logs`), 처리되지 않은 오류는 대화상자로 알려 줍니다. 도움말 ▸ 로그 폴더 열기.
- 화면이 검게만 나오면(원격 데스크톱·가상머신·구형 GPU) 설정 ▸ **호환 모드**를 켜고 다시 실행하세요.
- 지원 환경: Windows 10 1809 이상 64비트.

## 구조

```
main.py              진입점, 테마, 필수 파일 검사
app/mainwindow.py    메인 창 (파일 목록 · 플레이어 · 타임라인 · 구간 목록 · 내보내기)
app/player.py        libmpv 임베드 위젯
app/timeline.py      타임라인 (썸네일 · 파형 · 구간 · 마커 · 키프레임 · 확대/스크롤 · 미리보기 팝업)
app/segments.py      마커 → 구간 모델, 실행 취소, 작업 파일 저장/복원
app/ffmpeg_tools.py  ffprobe / 썸네일 / 파형 / 키프레임 / 무음 감지 / 자르기(3모드) / 합치기 / GPU 감지
app/workers.py       백그라운드 스레드 (분석 · 무음 · GPU · 내보내기 큐)
app/dialogs.py       무음·장면 마커 · 타임스탬프 · 크롭 위치 · URL 다운로드 · 파일명 규칙 대화상자
app/cache.py         썸네일·파형·키프레임 캐시
app/help.py          앱 내 도움말
app/style.py         다크 테마 QSS
app/logging_setup.py 로그 파일 · 예외 대화상자
tools/get_libmpv.py  libmpv-2.dll 다운로드
tools/get_ffmpeg.py  ffmpeg 공유 빌드 다운로드 (버전 고정)
tests/               모델 테스트 · ffmpeg 통합 테스트
tools/make_icon.py   아이콘 생성
docs/index.html      사용 설명서
```

## 라이선스

MIT. ffmpeg 와 libmpv 는 각각의 라이선스(LGPL/GPL)를 따릅니다.
