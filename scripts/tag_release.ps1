Param(
  [string]$VersionFile = "build/VERSION"
)

$ErrorActionPreference = "Stop"
Set-Location (Resolve-Path (Join-Path $PSScriptRoot ".."))

if (-not (Test-Path $VersionFile)) { throw "VERSION file missing" }
$v = Get-Content $VersionFile -TotalCount 1
if (-not $v) { throw "VERSION empty" }
$tag = "v" + $v.Trim()

git add .
try { git commit -m "chore: prepare release $tag" } catch {}
git push

git tag $tag -f
git push origin $tag -f

