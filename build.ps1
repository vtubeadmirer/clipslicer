# PyInstaller 로 dist\ClipSlicer\ 폴더 빌드.
# 실행 전: pip install -r requirements.txt, bin\ 에 libmpv-2.dll 준비 (ffmpeg/ffprobe 는 PATH 에 있으면 자동 복사).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

foreach ($f in @("bin\libmpv-2.dll", "bin\ffmpeg.exe", "bin\ffprobe.exe")) {
  if (-not (Test-Path $f)) {
    if ($f -like "*ffmpeg*" -or $f -like "*ffprobe*") {
      $name = Split-Path $f -Leaf
      $src = (Get-Command $name -ErrorAction SilentlyContinue).Source
      if ($src) { Copy-Item $src $f; Write-Host "PATH 에서 복사: $src"; continue }
    }
    throw "$f 가 없습니다. README 의 '개발 환경 설정' 을 참고하세요."
  }
}

# pyinstaller 는 진행 로그를 stderr 로 찍으므로 PowerShell 이 오류로 오해하지 않게 한다
$ErrorActionPreference = "Continue"
& pyinstaller --noconfirm --clean --windowed --name ClipSlicer `
  --icon assets\icon.ico `
  --add-data "assets;assets" `
  --add-binary "bin\libmpv-2.dll;." `
  --add-binary "bin\ffmpeg.exe;." `
  --add-binary "bin\ffprobe.exe;." `
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
$size = (Get-ChildItem dist\ClipSlicer -Recurse -File | Measure-Object Length -Sum).Sum / 1MB
Write-Host ("완료: dist\ClipSlicer\ClipSlicer.exe  ({0:N0} MB)" -f $size)
