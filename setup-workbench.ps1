param([switch]$SkipBrainCo, [switch]$SkipOmni)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw 'Install uv before setup.' }
$syncArgs = @('sync', '--locked', '--python', '3.12', '--extra', 'desktop')
if (-not $SkipBrainCo) { $syncArgs += @('--extra', 'brainco') }
if (-not $SkipOmni) {
    $sdkDir = Join-Path $PSScriptRoot 'vendor_sdk/omnibci'
    $sdkWheel = Join-Path $sdkDir 'omnibci-0.2.0.dev0-cp311-abi3-win_amd64.whl'
    $expected = ((Get-Content -LiteralPath (Join-Path $sdkDir 'SHA256SUMS.txt') -First 1) -split '\s+')[0]
    if ((Get-FileHash -LiteralPath $sdkWheel -Algorithm SHA256).Hash -ine $expected) { throw 'SDK checksum mismatch.' }
    $syncArgs += @('--extra', 'omni')
}
& uv @syncArgs
if ($LASTEXITCODE -ne 0) { throw 'Locked environment sync failed.' }
& uv pip check --python .venv/Scripts/python.exe
if ($LASTEXITCODE -ne 0) { throw 'Dependency check failed.' }
Write-Host 'Ready. Run start-neuroscope-desktop.bat. Existing .venv312 is not used or deleted.'
