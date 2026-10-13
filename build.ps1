# PyInstaller 로 dist\ClipSlicer\ 폴더 빌드.
# 실행 전: pip install -r requirements.txt, bin\ 에 libmpv-2.dll 준비 (ffmpeg/ffprobe 는 PATH 에 있으면 자동 복사).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path "bin\libmpv-2.dll")) { throw "bin\libmpv-2.dll 이 없습니다: python tools\get_libmpv.py" }
if (-not (Test-Path "bin\ffmpeg\ffmpeg.exe")) {
  Write-Host "bin\ffmpeg\ 가 없어 공유 빌드를 받습니다 (python tools\get_ffmpeg.py)"
  python tools\get_ffmpeg.py
  if ($LASTEXITCODE -ne 0) { throw "ffmpeg 다운로드 실패" }
}

# pyinstaller 는 진행 로그를 stderr 로 찍으므로 PowerShell 이 오류로 오해하지 않게 한다
$ErrorActionPreference = "Continue"
& pyinstaller --noconfirm --clean --windowed --name ClipSlicer `
  --icon assets\icon.ico `
  --add-data "assets;assets" `
  --manifest assets\ClipSlicer.manifest `
  --add-binary "bin\libmpv-2.dll;." `
  --add-data "bin\ffmpeg;ffmpeg" `
  --collect-submodules yt_dlp `
  --exclude-module PIL --exclude-module numpy --exclude-module tkinter `
  --exclude-module yaml --exclude-module psutil `
  --exclude-module PySide6.QtQuick --exclude-module PySide6.QtQml --exclude-module PySide6.QtPdf `
  --exclude-module PySide6.QtNetwork --exclude-module PySide6.QtOpenGL `
  main.py 2>&1 | ForEach-Object { "$_" }
if ($LASTEXITCODE -ne 0) { throw "pyinstaller 실패 (exit $LASTEXITCODE)" }
$ErrorActionPreference = "Stop"

# 쓰지 않는 구성 요소 정리 (용량 줄이기)
$internal = Join-Path $PSScriptRoot "dist\ClipSlicer\_internal"
$qt = Join-Path $internal "PySide6"
$dllPatterns = @("opengl32sw.dll", "Qt6Quick*.dll", "Qt6Qml*.dll", "Qt6Pdf*.dll", "Qt6Network.dll", "Qt6OpenGL.dll",
                 "Qt6VirtualKeyboard.dll", "Qt6Svg.dll", "QtNetwork.pyd", "QtOpenGL.pyd")
foreach ($pat in $dllPatterns) {
  Get-ChildItem $qt -Filter $pat -ErrorAction SilentlyContinue | Remove-Item -Force
}
$dirs = @("PySide6/qml", "PySide6/translations", "PySide6/plugins/virtualkeyboard", "PySide6/plugins/networkinformation",
          "PySide6/plugins/tls", "PySide6/plugins/qmltooling", "numpy", "numpy.libs", "PIL", "yaml", "psutil")
foreach ($d in $dirs) {
  $full = Join-Path $internal $d
  if (Test-Path -LiteralPath $full) { Remove-Item -LiteralPath $full -Recurse -Force }
}
# PyInstaller 가 ffmpeg 의 DLL 을 의존성으로 보고 _internal 루트에 한 번 더 복사한다 → 중복 제거 (ffmpeg\ 안의 것만 쓴다)
foreach ($pat in @("avcodec-*.dll", "avformat-*.dll", "avfilter-*.dll", "avdevice-*.dll", "avutil-*.dll",
                   "swscale-*.dll", "swresample-*.dll", "postproc-*.dll")) {
  Get-ChildItem $internal -Filter $pat -ErrorAction SilentlyContinue | Remove-Item -Force
}

# 번들 ffmpeg/libmpv 버전 기록 → _internal\deps.txt. 앱이 릴리스의 deps.txt 와 비교해 같으면 경량 업데이트 zip 만 받는다
# (app/updater.py choose_asset). release.yml 도 같은 내용을 릴리스 자산 deps.txt 로 올린다. PATH 를 비우기 전에 실행.
$deps = Join-Path $internal "deps.txt"
& python -c "import sys; sys.path.insert(0, 'tools'); import get_ffmpeg, get_libmpv; open(sys.argv[1], 'w', newline='\n').write(f'ffmpeg={get_ffmpeg.TAG}\nlibmpv={get_libmpv.TAG}\n')" $deps
if ($LASTEXITCODE -ne 0) { throw "deps.txt 생성 실패" }
Write-Host ("deps.txt: " + ((Get-Content $deps) -join ", "))

# 검증: PATH 를 비운 상태에서 번들된 ffmpeg/ffprobe 가 자기 DLL 만으로 뜨는지
$env:PATH = "$env:SystemRoot\System32"
foreach ($exe in @("ffmpeg.exe", "ffprobe.exe")) {
  $p = Join-Path $internal "ffmpeg\$exe"
  $out = & $p -version 2>&1
  $code = $LASTEXITCODE
  $first = ($out | Select-Object -First 1)
  if ($code -ne 0) { throw "번들 $exe 실행 실패 (DLL 누락?): $first" }
  Write-Host "검증 OK: $first"
}
$size = (Get-ChildItem dist\ClipSlicer -Recurse -File | Measure-Object Length -Sum).Sum / 1MB
Write-Host ("완료: dist\ClipSlicer\ClipSlicer.exe  ({0:N0} MB)" -f $size)
