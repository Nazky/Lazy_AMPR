param(
    [string]$OutputDirectory = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$parentDir = Split-Path -Parent $projectDir
$python = Join-Path $projectDir ".venv312\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Python build environment not found at $python"
}
$version = (& $python -c "from version import VERSION; print(VERSION)").Trim()
if ($version -notmatch '^\d+\.\d+\.\d+(-rc\d+)?$') {
    throw "Invalid application version: $version"
}
$releaseBase = [System.IO.Path]::GetFullPath((Join-Path $parentDir "release"))
$releaseRoot = if ($OutputDirectory) {
    [System.IO.Path]::GetFullPath((Join-Path $projectDir $OutputDirectory))
} else {
    [System.IO.Path]::GetFullPath((Join-Path $releaseBase $version))
}
if ((Split-Path -Parent $releaseRoot).TrimEnd('\') -ne $releaseBase.TrimEnd('\') -or
    -not (Split-Path -Leaf $releaseRoot)) {
    throw "Refusing to clean unexpected release path: $releaseRoot"
}
$work = Join-Path $releaseRoot "work"
$dist = Join-Path $releaseRoot "dist"
$archive = Join-Path $releaseRoot "Lazy_AMPR-$version-Windows.zip"

$oldPath = $env:Path
$pushed = $false
try {
    # A minimal PATH prevents unrelated developer-tool DLLs from being copied
    # into the Qt bundle by PyInstaller.
    $env:Path = "$(Split-Path -Parent $python);$env:SystemRoot\System32;$env:SystemRoot"
    if (Test-Path -LiteralPath $releaseRoot) {
        Remove-Item -LiteralPath $releaseRoot -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $work, $dist | Out-Null
    Push-Location $projectDir
    $pushed = $true
    & $python -m PyInstaller --noconfirm --clean --workpath $work --distpath $dist Lazy_AMPR.spec
    & $python -m PyInstaller --noconfirm --clean --workpath $work --distpath $dist ampr_pack.spec
    & $python -m PyInstaller --noconfirm --clean --workpath $work --distpath $dist ampr_pack_profile.spec

    $workers = Join-Path $dist "Lazy_AMPR\workers"
    New-Item -ItemType Directory -Force -Path $workers | Out-Null
    Copy-Item -Recurse -Force -LiteralPath (Join-Path $dist "ampr_pack") -Destination $workers
    Copy-Item -Recurse -Force -LiteralPath (Join-Path $dist "ampr_pack_profile") -Destination $workers

    Compress-Archive -Path (Join-Path $dist "Lazy_AMPR\*") -DestinationPath $archive -Force
    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash
    Set-Content -LiteralPath (Join-Path $releaseRoot "SHA256SUMS.txt") `
        -Value "$hash *$(Split-Path -Leaf $archive)" -Encoding ascii
    Write-Host "Built $archive"
    Write-Host "SHA-256 $hash"
}
finally {
    if ($pushed) { Pop-Location }
    $env:Path = $oldPath
}
