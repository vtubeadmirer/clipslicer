# ClipSlicer

영상을 재생하다가 멈춘 지점에 가위 표시만 찍으면, 구간별로 각각 저장해 주는 가벼운 Windows 영상 자르기 도구입니다.
ffmpeg + libmpv + PySide6 로 만들었습니다.

## 사용법

1. 영상을 창에 끌어다 놓거나 `Ctrl+O` 로 엽니다. (여러 개, 폴더도 가능)
2. 재생하다가 자를 지점에서 `S` 를 누르면 빨간 마커가 생깁니다.
3. 마커가 쌓이면 타임라인이 구간으로 나뉩니다. 필요 없는 구간은 `Ctrl+클릭`(또는 오른쪽 목록 체크 해제).
4. `Ctrl+E` → 켜진 구간이 `원본이름_01.mp4`, `_02.mp4` … 로 저장됩니다.

| 키 | 동작 |
|---|---|
| Space / K | 재생 · 정지 |
| ← → | 한 프레임 이동 |
| Shift+← → | 1초 이동 |
| Ctrl+← → | 10초 이동 |
| S | 현재 위치에 자르기 마커 |
| Delete | 가까운 마커 삭제 |
| L | 현재 구간 반복 재생 |
| ↑ ↓ | 이전 / 다음 구간으로 |
| Ctrl+↑ ↓ | 이전 / 다음 영상 |
| Ctrl+E | 모든 영상 내보내기 |

타임라인: 클릭=이동, 우클릭=마커 추가/삭제, 마커 드래그=이동, 더블클릭=구간 반복.

### 내보내기 모드

- **빠르게 (기본)**: `-c copy` 무손실. 거의 즉시 끝나지만 키프레임 단위로 잘립니다. 시작점은 바로 앞 키프레임까지 당겨지고(보통 1~2초, 키프레임이 드문 영상은 더 길어짐) 끝점은 정확합니다. 요청한 내용이 잘려 나가는 일은 없습니다.
- **정확하게**: libx264 CRF 18 재인코딩. 프레임 단위 정확, 대신 느림.

## 개발 환경 설정

```
pip install -r requirements.txt
python tools\get_libmpv.py        # bin\libmpv-2.dll 다운로드
```

`ffmpeg.exe`, `ffprobe.exe` 는 PATH 에 있거나 `bin\` 폴더에 두면 됩니다.
([gyan.dev 빌드](https://www.gyan.dev/ffmpeg/builds/) 권장)

실행: `python main.py` 또는 `run.bat`

## 배포용 빌드

```
.\build.ps1
```

`dist\ClipSlicer\ClipSlicer.exe` 가 만들어집니다. (bin\ 에 ffmpeg, ffprobe, libmpv 가 있어야 함)

## 구조

```
main.py              진입점, 테마, 필수 파일 검사
app/mainwindow.py    메인 창 (파일 목록 · 플레이어 · 타임라인 · 구간 목록 · 내보내기)
app/player.py        libmpv 임베드 위젯
app/timeline.py      타임라인 (썸네일 · 파형 · 구간 · 마커)
app/segments.py      마커 → 구간 모델
app/ffmpeg_tools.py  ffprobe / 썸네일 / 파형 / 자르기 명령
app/workers.py       백그라운드 분석 · 내보내기 스레드
tools/get_libmpv.py  libmpv-2.dll 다운로드
```
