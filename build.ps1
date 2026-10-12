# PyInstaller 로 dist\ClipSlicer\ 폴더 빌드.
# 실행 전: pip install -r requirements.txt, bin\ 에 ffmpeg.exe / ffprobe.exe / libmpv-2.dll 준비.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

pyinstaller --noconfirm --clean --windowed --name ClipSlicer `
  --add-binary "bin\libmpv-2.dll;." `
  --add-binary "bin\ffmpeg.exe;." `
  --add-binary "bin\ffprobe.exe;." `
  main.py

Write-Host "완료: dist\ClipSlicer\ClipSlicer.exe"
