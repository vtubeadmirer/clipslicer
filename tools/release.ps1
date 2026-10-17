# 릴리즈 한 번에: 버전 올리기 → 테스트 → 커밋 → push → (커밋이 성공했을 때만) 태그 → 태그 push.
#   .\tools\release.ps1 -Version 0.9.9 -MessageFile msg.txt
# 태그가 push 되면 GitHub Actions(release.yml)가 exe 를 빌드해 Release 에 올린다.
# release.yml 도 태그와 코드 버전이 다르면 빌드를 멈추므로, 엉뚱한 커밋에 태그가 걸려도 잘못된 릴리즈는 나가지 않는다.
param(
  [Parameter(Mandatory = $true)][string]$Version,
  [Parameter(Mandatory = $true)][string]$MessageFile,
  [switch]$SkipTests
)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

if ($Version -notmatch '^\d+\.\d+\.\d+$') { throw "버전은 0.9.9 같은 형식이어야 합니다: $Version" }
if (-not (Test-Path $MessageFile)) { throw "커밋 메시지 파일이 없습니다: $MessageFile" }
$tag = "v$Version"
if (git tag --list $tag) { throw "로컬에 이미 $tag 태그가 있습니다" }
if (git ls-remote origin "refs/tags/$tag") { throw "GitHub 에 이미 $tag 태그가 있습니다" }

# 버전 두 곳 (BOM 없이, 줄바꿈은 그대로)
$utf8 = New-Object System.Text.UTF8Encoding($false)
function Set-Version($path, $pattern, $replacement) {
  $full = (Resolve-Path $path).Path
  $text = [IO.File]::ReadAllText($full, $utf8)
  $new = [regex]::Replace($text, $pattern, $replacement)
  if ($new -eq $text -and -not ($text -match [regex]::Escape($replacement))) { throw "$path 에서 버전을 찾지 못했습니다" }
  [IO.File]::WriteAllText($full, $new, $utf8)
}
Set-Version "app\__init__.py" '__version__ = "[^"]+"' "__version__ = `"$Version`""
Set-Version "assets\ClipSlicer.manifest" '(name="ClipSlicer" version=")[0-9.]+(")' "`${1}$Version.0`${2}"
Write-Host "버전 → $Version"

if (-not $SkipTests) {
  python -m pytest -q
  if ($LASTEXITCODE -ne 0) { throw "테스트 실패 — 릴리즈 중단 (버전 변경은 작업 트리에 남아 있음)" }
}

git add -A
git commit -q -F $MessageFile
if ($LASTEXITCODE -ne 0) { throw "커밋 실패 — 태그를 만들지 않고 중단" }
$sha = (git rev-parse --short HEAD)
git push -q origin main
if ($LASTEXITCODE -ne 0) { throw "push 실패 — 태그를 만들지 않고 중단" }
git tag $tag -m "ClipSlicer $Version"
git push -q origin $tag
if ($LASTEXITCODE -ne 0) { throw "태그 push 실패" }
Write-Host "완료: $sha → $tag push. GitHub Actions 가 빌드합니다."
