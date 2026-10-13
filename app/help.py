"""도움말 창: 기능 설명을 탭별로 자세히."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QVBoxLayout, QTabWidget, QTextBrowser, QDialogButtonBox

from . import __version__

CSS = """
<style>
 body { font-family: 'Malgun Gothic', 'Segoe UI', sans-serif; font-size: 13px; color: #e4e4e8; }
 h2 { color: #7cc4ff; font-size: 16px; margin: 14px 0 6px 0; }
 h3 { color: #ffd54f; font-size: 13px; margin: 12px 0 4px 0; }
 p { margin: 4px 0 6px 0; line-height: 1.5; }
 li { margin: 3px 0; line-height: 1.45; }
 kbd { background: #3a3a44; border: 1px solid #666; border-radius: 3px; padding: 1px 5px;
       font-family: Consolas, monospace; font-size: 12px; color: #fff; }
 code { font-family: Consolas, monospace; color: #9fe3c9; }
 table { border-collapse: collapse; margin: 6px 0; }
 td, th { border: 1px solid #444; padding: 4px 8px; text-align: left; vertical-align: top; }
 th { background: #2e2e36; color: #cfd8dc; }
 .tip { background: #253140; border-left: 3px solid #42a5f5; padding: 6px 8px; margin: 6px 0; }
 .warn { background: #3a2a22; border-left: 3px solid #ffa726; padding: 6px 8px; margin: 6px 0; }
</style>
"""

PAGES = [
("시작하기", """
<h2>ClipSlicer 가 하는 일</h2>
<p>긴 영상을 보면서 <b>"여기서 자르자"</b> 하는 지점에 가위 표시(마커)만 찍으면,
마커 사이사이가 자동으로 구간이 되고, 각 구간을 따로 파일로 저장해 줍니다.
In 점 / Out 점을 잡는 편집기와 달리 <b>마커 하나 = 자르기 한 번</b> 이라 머릿속 모델이 단순합니다.</p>

<h2>기본 흐름 5단계</h2>
<ol>
 <li><b>영상 열기</b> — 창 아무 곳에나 끌어다 놓거나 <kbd>Ctrl+O</kbd>. 여러 개, 폴더째도 됩니다.
     왼쪽 "영상 목록"에 쌓이고, 각 영상은 자기만의 마커를 가집니다.</li>
 <li><b>재생하며 찾기</b> — <kbd>Space</kbd> 재생/정지. 멈춘 다음 <kbd>←</kbd> <kbd>→</kbd> 로 한 프레임씩 정확한 지점을 찾습니다.
     타임라인 위에 마우스를 올리면 그 위치의 썸네일이 떠서 훑어보기 편합니다.</li>
 <li><b>마커 찍기</b> — <kbd>S</kbd> 또는 <b>✂ 여기서 자르기</b>. 빨간 세로선이 생기고 타임라인이 색 구간으로 나뉩니다.</li>
 <li><b>구간 정리</b> — 필요 없는 구간은 타임라인에서 <kbd>Ctrl</kbd>+클릭하거나 오른쪽 목록의 체크를 끕니다.
     파일명 칸을 더블클릭하면 이름을 직접 정할 수 있습니다.</li>
 <li><b>내보내기</b> — <kbd>Ctrl+E</kbd>. 켜진 구간이 각각 파일로 저장됩니다.
     기본 저장 위치는 원본 옆 <code>원본이름_cuts</code> 폴더입니다.</li>
</ol>

<h2>두 가지 작업 방식</h2>
<ul>
 <li><b>자르기 모드 (S)</b> — 긴 영상을 여러 조각으로 "나눌" 때. 마커를 찍을수록 구간이 늘어나고 기본적으로 전부 켜져 있습니다.</li>
 <li><b>클립 모드 (I / O)</b> — 영상에서 쓸 부분만 "뽑을" 때. 시작에서 <kbd>I</kbd>, 끝에서 <kbd>O</kbd>. 그 사이만 켜지고 나머지는 자동으로 꺼집니다.
     여러 번 반복하면 클립이 쌓이고, <b>하나로 합치기</b>를 켜면 하이라이트 모음이 됩니다.</li>
</ul>
<div class="tip">마커와 구간 설정은 영상 옆 <code>영상이름.clipslicer.json</code> 에 <b>자동 저장</b>됩니다.
같은 영상을 다시 열면 작업하던 상태가 그대로 돌아옵니다.</div>

<h2>화면 구성</h2>
<table>
 <tr><th>왼쪽</th><td>영상 목록. 클릭해서 전환, <kbd>Ctrl+↑</kbd> <kbd>Ctrl+↓</kbd> 로도 이동.</td></tr>
 <tr><th>가운데 위</th><td>플레이어. 클릭하면 재생/정지.</td></tr>
 <tr><th>가운데 아래</th><td>타임라인(썸네일 띠 · 파형 · 구간 · 마커 · 키프레임), 재생 컨트롤, 볼륨·속도.</td></tr>
 <tr><th>오른쪽</th><td>구간 목록과 내보내기 설정·진행 상황.</td></tr>
</table>
"""),

("단축키", """
<h2>재생 · 이동</h2>
<table>
 <tr><th>키</th><th>동작</th></tr>
 <tr><td><kbd>Space</kbd> / <kbd>K</kbd></td><td>재생 · 정지</td></tr>
 <tr><td><kbd>←</kbd> <kbd>→</kbd></td><td>한 프레임 뒤로 / 앞으로 (정지 상태로)</td></tr>
 <tr><td><kbd>Shift</kbd>+<kbd>←</kbd> <kbd>→</kbd></td><td>1초 이동</td></tr>
 <tr><td><kbd>Ctrl</kbd>+<kbd>←</kbd> <kbd>→</kbd></td><td>10초 이동</td></tr>
 <tr><td><kbd>J</kbd></td><td>5초 뒤로</td></tr>
 <tr><td><kbd>Home</kbd> / <kbd>End</kbd></td><td>처음 / 끝</td></tr>
 <tr><td><kbd>↑</kbd> <kbd>↓</kbd></td><td>이전 / 다음 구간 시작으로</td></tr>
 <tr><td><kbd>[</kbd> <kbd>]</kbd></td><td>재생 속도 느리게 / 빠르게 (0.25x ~ 4x), <kbd>\\</kbd> 1배속</td></tr>
 <tr><td><kbd>M</kbd></td><td>음소거</td></tr>
 <tr><td><kbd>R</kbd></td><td>현재 위치 <b>앞뒤 2초 돌려보기</b> (다시 누르면 해제)</td></tr>
 <tr><td><kbd>L</kbd></td><td>현재 구간 반복 재생 켜기 / 끄기</td></tr>
</table>

<h2>마커 · 구간</h2>
<table>
 <tr><th>키</th><th>동작</th></tr>
 <tr><td><kbd>S</kbd></td><td>현재 위치에 자르기 마커</td></tr>
 <tr><td><kbd>Delete</kbd></td><td>현재 위치에서 가장 가까운 마커 삭제</td></tr>
 <tr><td><kbd>Ctrl+Z</kbd> / <kbd>Ctrl+Y</kbd></td><td>실행 취소 / 다시 실행 (마커·구간 변경 전부)</td></tr>
 <tr><td><kbd>E</kbd></td><td>현재 위치의 구간 켜기 / 끄기</td></tr>
 <tr><td><kbd>I</kbd> / <kbd>O</kbd></td><td><b>클립 모드</b>: 시작 / 끝. O 를 누르면 그 사이만 켜지고 나머지는 꺼짐. <kbd>Esc</kbd> 취소</td></tr>
 <tr><td><kbd>Ctrl+Shift+M</kbd></td><td>무음 구간에 자동 마커</td></tr>
 <tr><td><kbd>Ctrl+Shift+S</kbd></td><td>장면 전환에 자동 마커</td></tr>
 <tr><td><kbd>Ctrl+Shift+V</kbd></td><td>타임스탬프 텍스트 붙여넣기 → 마커</td></tr>
</table>

<h2>타임라인 (마우스)</h2>
<table>
 <tr><th>조작</th><th>동작</th></tr>
 <tr><td>클릭 · 드래그</td><td>그 위치로 이동 (드래그 중 썸네일 미리보기)</td></tr>
 <tr><td>마커 드래그</td><td>마커 위치 옮기기</td></tr>
 <tr><td>우클릭</td><td>빈 곳: 마커 추가 / 마커 위: 마커 삭제</td></tr>
 <tr><td><kbd>Ctrl</kbd>+클릭</td><td>그 구간 켜기 / 끄기</td></tr>
 <tr><td>더블클릭</td><td>그 구간 반복 재생</td></tr>
 <tr><td><kbd>Ctrl</kbd>+휠</td><td>확대 / 축소 (마우스 위치 기준)</td></tr>
 <tr><td>휠</td><td>확대된 상태에서 좌우 스크롤</td></tr>
 <tr><td><kbd>Ctrl</kbd>+<kbd>0</kbd></td><td>전체 보기로 되돌리기</td></tr>
</table>

<h2>파일 · 기타</h2>
<table>
 <tr><td><kbd>Ctrl+O</kbd></td><td>영상 열기</td></tr>
 <tr><td><kbd>Ctrl+L</kbd></td><td>URL 에서 열기 (유튜브 · 치지직 · 트위치 등)</td></tr>
 <tr><td><kbd>Ctrl+P</kbd></td><td>현재 화면을 PNG 로 저장 (영상 옆)</td></tr>
 <tr><td><kbd>Ctrl+U</kbd></td><td>유튜브에 올리기 (파일 선택)</td></tr>
 <tr><td><kbd>Ctrl+E</kbd></td><td>모든 영상 내보내기</td></tr>
 <tr><td><kbd>Ctrl+Shift+E</kbd></td><td>현재 영상만 내보내기</td></tr>
 <tr><td><kbd>Ctrl+↑</kbd> <kbd>Ctrl+↓</kbd></td><td>이전 / 다음 영상</td></tr>
 <tr><td><kbd>F1</kbd></td><td>이 도움말</td></tr>
</table>
"""),

("타임라인", """
<h2>타임라인 읽는 법</h2>
<p>위에서부터 <b>썸네일 띠</b>, 그 위에 반투명한 <b>오디오 파형</b>(청록색), 구간마다 다른 색의 <b>구간 블록</b>,
아래에 <b>시간 눈금</b>이 있습니다. 영상을 열면 썸네일·파형·키프레임을 뒤에서 조용히 만들기 때문에
처음 몇 초는 썸네일이 비어 있을 수 있습니다.</p>
<ul>
 <li><b>흰 세로선</b> — 현재 재생 위치(플레이헤드)</li>
 <li><b>빨간 세로선 + 삼각형</b> — 자르기 마커. 드래그해서 옮길 수 있습니다.</li>
 <li><b>색 블록 + 번호</b> — 구간. 꺼진 구간은 어둡게 표시되고 번호 옆에 ✕ 가 붙습니다.</li>
 <li><b>노란 테두리</b> — 지금 반복 재생 중인 구간</li>
 <li><b>눈금 아래 작은 흰 점</b> — 키프레임 위치 (아래 "자르기 모드" 참고)</li>
</ul>

<h2>확대해서 정확히 찍기</h2>
<p>한 시간짜리 영상은 타임라인 1픽셀이 3초쯤 됩니다. 정확한 지점을 마우스로 찍으려면
<kbd>Ctrl</kbd>+휠로 확대하세요. 마우스가 있는 위치를 중심으로 확대되고, 확대되면 아래에 스크롤바가 나타납니다.
재생 중에는 플레이헤드가 화면 밖으로 나가면 자동으로 따라갑니다. <kbd>Ctrl</kbd>+<kbd>0</kbd> 으로 전체 보기.</p>

<h2>썸네일 미리보기</h2>
<p>타임라인에 마우스를 올리면 그 위치의 썸네일과 시각이 팝업으로 뜹니다. 드래그 중에도 계속 보여서,
플레이어가 따라오기 전에 대략 어떤 장면인지 바로 알 수 있습니다.</p>

<h2>파형으로 조용한 곳 찾기</h2>
<p>파형이 낮게 깔리는 곳이 말이 끊기거나 조용한 부분입니다. 그 근처에서 멈춰 <kbd>←</kbd> <kbd>→</kbd> 로 다듬거나,
<b>마커 ▸ 무음 구간에 자동 마커</b>로 한 번에 찍을 수 있습니다.</p>

<h2>시간 직접 입력</h2>
<p>재생 컨트롤의 시간 표시를 클릭하면 입력란이 됩니다. <code>1:23.5</code>, <code>01:02:03</code>, <code>83.5</code>, <code>1h2m3s</code>
어느 형식이든 입력하고 <kbd>Enter</kbd> 를 누르면 그 위치로 이동합니다.</p>
"""),

("자르기 모드", """
<h2>세 가지 모드</h2>
<table>
 <tr><th>모드</th><th>속도</th><th>정확도</th><th>화질</th><th>이럴 때</th></tr>
 <tr><td><b>빠르게 (기본)</b></td><td>거의 즉시</td><td>시작점이 앞 키프레임으로 당겨질 수 있음 (보통 1~2초)</td><td>원본 그대로</td><td>대부분의 경우. 재인코딩 없이 원본을 툭 끊어 냅니다</td></tr>
 <tr><td><b>스마트</b></td><td>빠름 (파일을 한 번 더 읽음)</td><td>프레임 단위</td><td>앞 1~2초만 재인코딩, 나머지 원본</td><td>시작점이 1~2초 밀리는 게 싫을 때</td></tr>
 <tr><td><b>정확하게</b></td><td>느림 (GPU 있으면 빠름)</td><td>프레임 단위</td><td>전체 재인코딩 (CRF 18, 거의 무손실)</td><td>스마트가 실패하거나 특이한 코덱일 때</td></tr>
</table>

<h2>왜 "빠르게"는 시작점이 밀리나 — 키프레임</h2>
<p>압축된 영상은 몇 초마다 한 장씩만 완전한 그림(<b>키프레임</b>)을 저장하고, 그 사이 프레임은 "앞 그림에서 바뀐 부분"만 저장합니다.
그래서 재인코딩 없이 자르려면 <b>키프레임에서만 시작</b>할 수 있습니다. "빠르게" 모드는 요청한 지점 바로 앞 키프레임부터 복사하기 때문에,
<b>시작 부분이 최대 키프레임 간격만큼 길어집니다</b> (보통 1~2초, 화면 녹화는 5~10초까지도). 끝점은 정확합니다. 요청한 내용이 잘려 나가는 일은 없습니다.</p>
<p>타임라인 눈금 아래 흰 점이 키프레임 위치입니다. <b>설정 ▸ 마커를 키프레임에 맞추기</b>를 켜면 마커를 찍을 때 가까운 키프레임에 자동으로 붙어서,
"빠르게" 모드로도 정확하게 잘립니다.</p>

<h2>스마트 모드가 하는 일</h2>
<ol>
 <li>요청한 시작점부터 다음 키프레임까지 (보통 1~2초) 만 재인코딩</li>
 <li>그 키프레임부터 끝까지는 원본 그대로 복사</li>
 <li>두 조각을 이어 붙임</li>
</ol>
<p>그래서 빠르면서 정확하고 화질 손실도 거의 없습니다. H.264 / HEVC 영상에서 동작하며, 다른 코덱이거나 구간 안에 키프레임이 없으면
자동으로 전체 재인코딩으로 넘어갑니다. 내보내기 로그에 실제로 어떤 방식이 쓰였는지(복사 / 스마트 / 재인코딩) 표시됩니다.</p>
<div class="warn">스마트 모드로 만든 파일은 앞 조각과 뒤 조각의 인코딩 설정이 미묘하게 달라, 아주 드물게 특정 플레이어에서 이음새에서 잠깐 깨져 보일 수 있습니다.
그런 파일은 "정확하게" 모드로 다시 뽑으세요.</div>

<h2>GPU 인코딩</h2>
<p>NVIDIA(NVENC), Intel(QSV), AMD(AMF) 하드웨어 인코더를 시작할 때 자동으로 찾습니다. <b>설정 ▸ GPU 인코딩 사용</b>이 켜져 있으면
"정확하게"와 "스마트"의 재인코딩 부분이 5~10배 빨라집니다. 화질은 CPU(libx264) 쪽이 같은 용량에서 조금 더 좋습니다.</p>
"""),

("자동 마커 · 합치기 · 오디오", """
<h2>무음 구간에 자동 마커</h2>
<p><b>마커 ▸ 무음 구간에 자동 마커</b> (<kbd>Ctrl+Shift+M</kbd>). 소리가 기준 음량(기본 -35dB)보다 작은 상태가
최소 길이(기본 1초) 이상 이어지는 곳을 찾습니다.</p>
<ul>
 <li><b>가운데에 마커 1개</b> — 무음 한가운데서 깔끔하게 나눕니다. 강의를 주제별로 나눌 때.</li>
 <li><b>양쪽 끝에 마커 2개 + 무음 구간 끄기</b> — 무음 자체를 잘라냅니다. 뒤에서 "하나로 합치기"와 같이 쓰면 무음 제거 영상이 됩니다.</li>
</ul>
<p>결과가 너무 많거나 적으면 기준 음량을 조정하세요. 잡음이 있는 녹음은 -25dB 정도, 깨끗한 녹음은 -45dB 까지.
자동 마커도 실행 취소(<kbd>Ctrl+Z</kbd>)가 됩니다.</p>

<h2>장면 전환에 자동 마커</h2>
<p><b>편집 ▸ 장면 전환에 자동 마커</b> (<kbd>Ctrl+Shift+S</kbd>). 화면이 크게 바뀌는 지점(컷 편집점·화면 전환)을 찾아 마커를 넣습니다.
영상 전체를 작은 해상도로 훑기 때문에 1시간 영상에 1~3분쯤 걸리고, 진행률은 내보내기 패널에 표시됩니다.
민감도(0~1)가 낮을수록 작은 변화도 잡습니다. 0.3~0.5 가 보통입니다.</p>

<h2>타임스탬프 붙여넣기</h2>
<p><b>편집 ▸ 타임스탬프 붙여넣기</b> (<kbd>Ctrl+Shift+V</kbd>). 유튜브 챕터 목록이나 댓글의 "12:34 하이라이트" 같은 텍스트를 붙여넣으면
<code>12:34</code>, <code>1:02:03</code>, <code>0:45.5</code> 형식의 시각을 전부 찾아 마커로 만듭니다. 클립보드 내용이 자동으로 채워집니다.</p>

<h2>챕터 복사</h2>
<p>구간 목록 위 <b>챕터 복사</b> 버튼은 켜진 구간을 <code>00:00 이름</code> 형식으로 클립보드에 복사합니다. 유튜브 설명란에 붙이면 챕터가 됩니다.</p>

<h2>켜진 구간을 하나로 합치기</h2>
<p>내보내기 패널의 <b>하나로 합치기</b>를 켜면, 켜진 구간들을 각각 저장하는 대신 순서대로 이어 붙여 영상 하나로 만듭니다.
파일명은 <code>원본이름_merged</code>. "광고·잡담 빼고 한 편으로" 용도입니다. 자르기 모드는 그대로 적용됩니다.</p>

<h2>오디오만 추출</h2>
<p><b>출력</b>을 "오디오만 (m4a)" 또는 "오디오만 (mp3)" 로 바꾸면 영상 없이 소리만 저장합니다.
m4a 는 원본이 AAC 면 무손실 복사, 아니면 AAC 192k 로 변환합니다. mp3 는 항상 변환합니다(고음질 VBR).</p>

<h2>세로 9:16 쇼츠 출력</h2>
<p><b>출력</b>을 "세로 9:16 쇼츠" 로 바꾸면 각 구간을 1080×1920 세로 영상으로 재인코딩합니다 (유튜브 쇼츠·릴스·틱톡용).
<b>크롭 위치…</b> 버튼을 누르면 현재 화면 위에서 노란 창을 드래그해 어느 부분을 남길지 정합니다. 위치는 영상마다 기억됩니다.
항상 재인코딩이므로 자르기 방식 선택은 무시되고, GPU 인코더가 있으면 사용합니다.</p>

<h2>URL 에서 열기</h2>
<p><b>파일 ▸ URL 에서 열기</b> (<kbd>Ctrl+L</kbd>). 유튜브·치지직·트위치 VOD 등 yt-dlp 가 지원하는 주소를 넣으면 받아서 바로 목록에 추가합니다.
화질(최고 / 1080p / 720p / 480p)과 저장 폴더를 고를 수 있고, 기본 폴더는 <code>내 비디오\\ClipSlicer</code> 입니다.
받은 파일은 지우지 않으니 다 쓴 뒤 직접 정리하세요. 로그인이 필요한 영상이나 회원 전용 다시보기는 받을 수 없습니다.</p>
<div class="tip"><b>구간만 받기</b>: 몇 시간짜리 다시보기는 전체를 받으면 수십 GB 입니다. 대화상자에서 "구간만 받기"를 켜고
<code>1:02:00 ~ 1:15:30</code> 처럼 넣으면 그 부분만 받습니다 (앞뒤가 몇 초 여유 있게 잘림). 치지직 다시보기는 이 방식으로 받는 것을 권합니다.</div>

<h2>파일명 규칙</h2>
<p><b>설정 ▸ 파일명 규칙</b>. <code>{name}</code> 원본 이름, <code>{n}</code> 번호, <code>{start}</code> <code>{end}</code> <code>{dur}</code> 시각.
예: <code>{name}_{start}-{end}</code> → <code>방송_12m05s-15m40s.mp4</code>. 구간 목록에서 직접 입력한 이름이 항상 우선합니다.</p>

<h2>같은 이름의 파일이 있으면</h2>
<p>내보내기 전에 알려 주고 <b>덮어쓰기 / 번호 붙여 저장 / 취소</b> 중 고를 수 있습니다.</p>
"""),

("유튜브 올리기", """
<h2>잘라낸 영상을 유튜브에 바로 올리기</h2>
<p>내보내기 패널의 <b>완료 후 유튜브에 올리기</b>를 켜 두면, 내보내기가 끝날 때 올리기 창이 열립니다.
파일마다 제목(구간 이름)·설명(템플릿)·태그·썸네일을 채우고, 공개 범위·카테고리·재생목록을 고른 뒤 <b>올리기</b>.
이미 잘라 둔 파일은 <b>파일 ▸ 유튜브에 올리기</b> (<kbd>Ctrl+U</kbd>) 로 골라서 올립니다.</p>

<h3>처음 한 번: 계정 연결</h3>
<p><b>설정 ▸ 유튜브 계정 연결</b>. 유튜브 API 는 구글이 발급한 OAuth 클라이언트가 있어야 쓸 수 있어서, 창 안의 안내대로
Google Cloud 콘솔에서 프로젝트를 만들고 <code>client_secret.json</code> 을 받아 등록한 뒤 "계정 연결"을 누릅니다 (약 10분, 무료).
브라우저가 열려 로그인·허용을 하면 끝이고, 로그인 정보는 Windows 가 암호화해 프로그램 폴더에 보관합니다 (settings.ini 에는 안 들어감).</p>

<div class="warn"><b>비공개로만 올라갑니다.</b> 구글 심사(앱 검증)를 받지 않은 프로젝트로 올린 영상은 비공개로 고정됩니다.
제목·설명·썸네일·재생목록까지 다 채워서 올린 뒤, <b>유튜브 스튜디오에서 공개 범위만 바꾸면</b> 됩니다 (올리기 창의 "유튜브 스튜디오 열기").
심사를 통과하면 공개·일부공개로 바로 올릴 수 있습니다.</div>

<h3>한도</h3>
<p>API 할당량이 하루 10,000 단위이고 업로드 1건이 1,600 단위라 <b>하루 약 6개</b>입니다. 넘으면 "할당량" 오류가 나고 다음 날(태평양 시간 자정) 풀립니다.
더 필요하면 Google Cloud 콘솔에서 할당량 증설을 신청할 수 있습니다. 썸네일 설정은 채널이 전화 인증된 경우에만 됩니다.</p>

<h3>설명 템플릿</h3>
<p><b>설정 ▸ 유튜브 설명 템플릿</b>. <code>{title}</code> 제목, <code>{source}</code> 원본 이름, <code>{start}</code> <code>{end}</code> 구간 시각. 기본값: <code>{source} 에서 잘라낸 클립 ({start} ~ {end})</code></p>

<h3>쇼츠</h3>
<p>세로 9:16 으로 내보낸 영상은 "제목에 #Shorts 붙이기"를 켜면 쇼츠로 분류됩니다 (60초 이하).</p>

<h3>업로드가 끊기면</h3>
<p>이어 올리기 방식이라 네트워크가 잠깐 끊겨도 같은 자리부터 다시 보냅니다. 완전히 실패하면 창의 "실패한 항목 다시 올리기"로 재시도.</p>
"""),

("설정 · 파일", """
<h2>설정 메뉴</h2>
<table>
 <tr><th>항목</th><th>설명</th></tr>
 <tr><td>마커를 키프레임에 맞추기</td><td>마커를 찍거나 옮길 때 0.5초 안에 키프레임이 있으면 거기에 붙입니다. "빠르게" 모드로 정확히 자르고 싶을 때.</td></tr>
 <tr><td>GPU 인코딩 사용</td><td>하드웨어 인코더가 발견되면 재인코딩에 사용합니다. 메뉴에 발견된 인코더 이름이 표시됩니다.</td></tr>
 <tr><td>작업 자동 저장</td><td>마커·구간 변경을 영상 옆 <code>.clipslicer.json</code> 에 저장합니다. 끄면 창을 닫을 때 작업이 사라집니다.</td></tr>
 <tr><td>키프레임 표시</td><td>타임라인의 흰 점을 끄거나 켭니다.</td></tr>
 <tr><td>시작할 때 새 버전 확인</td><td>시작할 때(1시간에 한 번까지) GitHub 릴리스를 조회해 새 버전이 있으면 오른쪽 아래에 초록 버튼이 뜹니다. 외부로 보내는 정보는 없습니다(릴리스 목록 조회뿐). 도움말 ▸ 업데이트 확인으로 수동 확인.</td></tr>
 <tr><td>분석 결과 캐시 저장</td><td>썸네일·파형·키프레임을 영상 옆 <code>.clipslicer.cache</code> 에 저장해 다음에 열 때 즉시 씁니다. 영상이 바뀌면 자동으로 다시 만듭니다.</td></tr>
 <tr><td>호환 모드</td><td>GPU 가속 없이 재생 화면을 그립니다. 화면이 검게만 나올 때. 다시 실행해야 적용됩니다.</td></tr>
 <tr><td>유튜브 계정 연결…</td><td>OAuth 클라이언트 등록과 로그인. "유튜브 올리기" 탭 참고.</td></tr>
 <tr><td>유튜브 설명 템플릿…</td><td>올릴 때 설명란에 미리 채울 내용.</td></tr>
 <tr><td>파일명 규칙…</td><td>출력 파일 이름 패턴.</td></tr>
</table>

<h2>작업 파일 (.clipslicer.json)</h2>
<p>영상과 같은 폴더에 <code>영상이름.mp4.clipslicer.json</code> 으로 저장됩니다. 마커 위치, 구간 켜짐 여부, 직접 정한 파일명, 마지막 재생 위치가 들어 있습니다.
영상을 다른 PC 로 옮길 때 이 파일도 같이 옮기면 작업이 그대로 복원됩니다. 텍스트 파일이라 메모장으로 열어 볼 수도 있습니다.</p>

<h2>업데이트</h2>
<p>새 버전이 있으면 오른쪽 아래에 <b>⬆ 새 버전</b> 버튼이 뜹니다. 누르면 변경 내용을 보여 주고 <b>지금 업데이트 / 나중에 / 이 버전 건너뛰기</b> 를 고릅니다.
지금 업데이트를 누르면 zip 을 받아 체크섬을 검증한 뒤, 프로그램을 닫고 파일을 교체하고 다시 엽니다. <code>settings.ini</code>, 로그, 작업 파일은 그대로이고
이전 버전은 프로그램 폴더의 <code>_backup</code> 에 남습니다 (문제가 없으면 지워도 됩니다). 읽기 전용 위치에 있으면 자동 교체 대신 다운로드 페이지를 안내합니다.</p>

<h2>포터블</h2>
<p>설치 과정이 없고, 설정은 프로그램 옆 <code>settings.ini</code> 에 저장됩니다. 레지스트리나 사용자 폴더에 아무것도 남기지 않으므로
<b>폴더째 USB 에 복사해서</b> 어느 PC 에서나 쓸 수 있습니다. (프로그램 폴더에 쓰기 권한이 없을 때만 레지스트리를 씁니다.)</p>

<h2>출력 폴더</h2>
<p>비워 두면 각 원본 옆에 <code>원본이름_cuts</code> 폴더를 만듭니다. 폴더를 지정하면 모든 영상의 결과가 그 한 곳에 모입니다.
완료 후 폴더를 자동으로 열어 주는 옵션이 있습니다.</p>

<h2>명령줄 · 파일 연결</h2>
<p><code>ClipSlicer.exe 영상1.mp4 영상2.mkv</code> 처럼 인자로 넘기면 바로 열립니다.
탐색기에서 mp4 를 우클릭 → "연결 프로그램 ▸ 다른 앱 선택" 에서 ClipSlicer.exe 를 고르면 더블클릭으로 열 수 있습니다.</p>

<h2>최근 파일</h2>
<p><b>파일 ▸ 최근 파일</b> 에 마지막 10개가 남습니다.</p>
"""),

("문제 해결", """
<h2>자주 묻는 것</h2>
<h3>영상이 안 열리거나 화면이 까맣다</h3>
<p>libmpv 는 거의 모든 포맷을 재생하지만, 손상된 파일이나 DRM 이 걸린 파일은 안 됩니다. 다른 플레이어(mpv, VLC)로도 안 열리면 파일 문제입니다.
그래픽 드라이버가 오래되면 화면이 까말 수 있습니다. 드라이버를 갱신해 보세요.</p>

<h3>"빠르게"로 잘랐더니 앞부분이 길다</h3>
<p>정상입니다. 키프레임 때문입니다 ("자르기 모드" 탭). <b>스마트</b> 모드를 쓰거나 <b>마커를 키프레임에 맞추기</b>를 켜세요.</p>

<h3>잘린 파일의 처음 몇 초가 깨져 보인다</h3>
<p>스마트 모드 이음새 문제이거나 플레이어 문제입니다. "정확하게" 모드로 다시 뽑으세요.</p>

<h3>내보내기가 실패한다</h3>
<p>오른쪽 아래 로그에 ffmpeg 오류가 표시됩니다. 흔한 원인: 출력 폴더에 쓰기 권한이 없음, 디스크 공간 부족,
MKV 의 자막·첨부 스트림을 MP4 로 복사하려 함 (이때는 "정확하게" 모드 사용).</p>

<h3>썸네일·파형이 안 생긴다</h3>
<p>아주 긴 영상(수 시간)은 몇십 초 걸립니다. 오디오가 없는 영상은 파형이 없습니다. ffmpeg 가 PATH 나 bin 폴더에 있어야 합니다.</p>

<h3>단축키가 안 먹는다</h3>
<p>구간 목록의 파일명을 편집 중이면 키 입력이 그쪽으로 갑니다. <kbd>Esc</kbd> 로 편집을 끝내거나 플레이어를 한 번 클릭하세요.</p>

<h3>필요한 파일이 없다는 창이 뜬다</h3>
<p><code>ffmpeg.exe</code>, <code>ffprobe.exe</code>, <code>libmpv-2.dll</code> 이 프로그램 폴더(또는 그 안의 <code>bin</code>)에 있어야 합니다.
개발 환경에서는 <code>python tools\\get_libmpv.py</code> 로 libmpv 를 받을 수 있습니다.</p>

<h3>오류가 났을 때</h3>
<p>처리되지 않은 오류는 대화상자로 알려 주고, 모든 오류는 <code>logs\\clipslicer.log</code> 에 남습니다 (<b>도움말 ▸ 로그 폴더 열기</b>).
문제를 보고할 때 이 파일을 같이 보내 주시면 원인을 찾기 쉽습니다. 로그에는 열었던 파일 경로가 들어 있습니다.</p>
<h3>화면이 검게만 나온다 (원격 데스크톱 · 가상머신 · 구형 GPU)</h3>
<p><b>설정 ▸ 호환 모드</b>를 켜고 프로그램을 다시 실행하세요. GPU 가속 없이 그립니다.</p>

<h2>정보</h2>
<p>ClipSlicer """ + __version__ + """ — Python · PySide6 · libmpv · ffmpeg.<br>
소스: <a href="https://github.com/vtubeadmirer/clipslicer">github.com/vtubeadmirer/clipslicer</a></p>
"""),
]


class HelpDialog(QDialog):
    def __init__(self, parent=None, page: int = 0):
        super().__init__(parent)
        self.setWindowTitle("ClipSlicer 도움말")
        self.resize(760, 620)
        lay = QVBoxLayout(self)
        self.tabs = QTabWidget()
        for title, html in PAGES:
            tb = QTextBrowser()
            tb.setOpenExternalLinks(True)
            tb.setHtml(CSS + "<body>" + html + "</body>")
            self.tabs.addTab(tb, title)
        self.tabs.setCurrentIndex(page)
        lay.addWidget(self.tabs, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.button(QDialogButtonBox.Close).setText("닫기")
        bb.rejected.connect(self.reject)
        bb.clicked.connect(self.accept)
        lay.addWidget(bb)
