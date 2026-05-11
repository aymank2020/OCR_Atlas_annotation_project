param(
    [string]$ServerHost = "root@167.235.253.229",
    [string]$LocalEnvPath = ".env",
    [string]$RemoteEnvPath = "/srv/atlas/OCR_annotation_Atlas/.env",
    [switch]$RestartServices
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $LocalEnvPath)) {
    throw "Local env file not found: $LocalEnvPath"
}

Write-Host "[secrets] Uploading $LocalEnvPath to $ServerHost`:$RemoteEnvPath"
scp $LocalEnvPath "${ServerHost}:$RemoteEnvPath"
if ($LASTEXITCODE -ne 0) {
    throw "scp upload failed."
}

ssh $ServerHost "chmod 600 $RemoteEnvPath"
if ($LASTEXITCODE -ne 0) {
    throw "remote chmod failed."
}

if ($RestartServices) {
    Write-Host "[secrets] Restarting Atlas services on server..."
    ssh $ServerHost "systemctl restart atlas-solver.service atlas-discord-bot.service atlas-feedback-collector.timer atlas-episode-review-refresh.timer"
    if ($LASTEXITCODE -ne 0) {
        throw "service restart failed."
    }
}

Write-Host "[secrets] Done. .env stayed outside Git and was transferred only over SSH."
