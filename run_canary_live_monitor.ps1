param(
    [string]$Config = "config_account_danatimer_canary_v2.yaml",
    [switch]$Execute,
    [string]$OutputDir = "outputs/danatimer_canary_v2",
    [string]$LogPath = "",
    [string]$ServerHost = "root@167.235.253.229",
    [string]$ServerRepo = "/srv/atlas/OCR_annotation_Atlas",
    [string]$ServerGeneratedConfig = ".state/generated_configs/danatimer.generated.yaml",
    [switch]$SkipServerPreflight,
    [switch]$PreflightOnly
)

$ErrorActionPreference = "Continue"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

function Get-FileSha256OrEmpty {
    param([string]$PathValue)
    if ([string]::IsNullOrWhiteSpace($PathValue)) {
        return ""
    }
    $resolved = [System.IO.Path]::GetFullPath((Join-Path $root $PathValue))
    if (-not (Test-Path $resolved)) {
        return ""
    }
    $text = Get-Content $resolved -Raw
    $normalized = $text.Replace("`r`n", "`n").Replace("`r", "`n")
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($normalized)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $hashBytes = $sha.ComputeHash($bytes)
    } finally {
        $sha.Dispose()
    }
    return ([System.BitConverter]::ToString($hashBytes)).Replace("-", "").ToLowerInvariant()
}

function Get-BuildMarkerOrEmpty {
    param([string]$SolverPath)
    if (-not (Test-Path $SolverPath)) {
        return ""
    }
    $content = Get-Content $SolverPath -Raw
    $match = [regex]::Match($content, '_SCRIPT_BUILD\s*=\s*"([^"]+)"')
    if ($match.Success) {
        return $match.Groups[1].Value.Trim()
    }
    return ""
}

function Get-ServerCommandOutput {
    param([string]$RemoteCommand)
    if ([string]::IsNullOrWhiteSpace($ServerHost) -or [string]::IsNullOrWhiteSpace($RemoteCommand)) {
        return ""
    }
    try {
        return (ssh $ServerHost $RemoteCommand 2>$null | Out-String).Trim()
    } catch {
        return ""
    }
}

if ([string]::IsNullOrWhiteSpace($LogPath)) {
    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $logPath = Join-Path $root (Join-Path $OutputDir "canary_live_${timestamp}.log")
} else {
    $logPath = [System.IO.Path]::GetFullPath((Join-Path $root $LogPath))
    New-Item -ItemType Directory -Force -Path ([System.IO.Path]::GetDirectoryName($logPath)) | Out-Null
}

$localConfigHash = Get-FileSha256OrEmpty -PathValue $Config
$localGeneratedConfigName = [System.IO.Path]::GetFileNameWithoutExtension($Config) -replace '\.canary_v2$', ''
$localGeneratedConfigPath = Join-Path ".state/generated_configs" "$localGeneratedConfigName.generated.yaml"
$localGeneratedConfigHash = Get-FileSha256OrEmpty -PathValue $localGeneratedConfigPath
$solverPath = Join-Path $root "atlas_web_auto_solver.py"
$localBuildMarker = Get-BuildMarkerOrEmpty -SolverPath $solverPath
$localCommit = (git rev-parse HEAD 2>$null | Out-String).Trim()

Write-Host "[preflight] local_commit=$localCommit"
Write-Host "[preflight] local_build=$localBuildMarker"
Write-Host "[preflight] local_config_sha256=$localConfigHash"
if (-not [string]::IsNullOrWhiteSpace($localGeneratedConfigHash)) {
    Write-Host "[preflight] local_generated_config=$localGeneratedConfigPath"
    Write-Host "[preflight] local_generated_config_sha256=$localGeneratedConfigHash"
}

if (-not $SkipServerPreflight.IsPresent -and -not [string]::IsNullOrWhiteSpace($ServerHost)) {
    $serverCommit = Get-ServerCommandOutput -RemoteCommand "cd $ServerRepo && git rev-parse HEAD"
    $serverConfigHash = Get-ServerCommandOutput -RemoteCommand "cd $ServerRepo && if [ -f '$Config' ]; then tr -d '\r' < '$Config' | sha256sum | cut -d' ' -f1; fi"
    $serverGeneratedHash = Get-ServerCommandOutput -RemoteCommand "cd $ServerRepo && if [ -f '$ServerGeneratedConfig' ]; then tr -d '\r' < '$ServerGeneratedConfig' | sha256sum | cut -d' ' -f1; fi"

    Write-Host "[preflight] server_host=$ServerHost"
    Write-Host "[preflight] server_commit=$serverCommit"
    if (-not [string]::IsNullOrWhiteSpace($serverConfigHash)) {
        Write-Host "[preflight] server_config_sha256=$serverConfigHash"
    }
    if (-not [string]::IsNullOrWhiteSpace($serverGeneratedHash)) {
        Write-Host "[preflight] server_generated_config=$ServerGeneratedConfig"
        Write-Host "[preflight] server_generated_config_sha256=$serverGeneratedHash"
    }
    if (-not [string]::IsNullOrWhiteSpace($serverCommit)) {
        Write-Host "[preflight] commit_match=$([bool]($serverCommit -eq $localCommit))"
    }
    if (-not [string]::IsNullOrWhiteSpace($serverConfigHash) -and -not [string]::IsNullOrWhiteSpace($localConfigHash)) {
        Write-Host "[preflight] config_match=$([bool]($serverConfigHash -eq $localConfigHash))"
    }
}

if ($PreflightOnly) {
    Write-Host "[monitor] preflight only mode; skipping canary run."
    exit 0
}

$env:PYTHONPATH = $root
$args = @("-u", "atlas_web_auto_solver.py", "--config", $Config)
if ($Execute) {
    $args += "--execute"
}

Write-Host "[monitor] config=$Config"
Write-Host "[monitor] execute=$($Execute.IsPresent)"
Write-Host "[monitor] log=$logPath"
Write-Host "[monitor] starting live canary..."

& python @args 2>&1 | Tee-Object -FilePath $logPath

Write-Host "[monitor] canary finished. log=$logPath"
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
