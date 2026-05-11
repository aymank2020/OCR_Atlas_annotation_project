param(
    [string]$RemoteName = "gdrive",
    [string]$ExpectedEmail = "aymanibrahim200500@gmail.com",
    [string]$ExpectedRootFolderId = "1kLe9Ai7swxh9Nx2NifD9Fcodf85AfyAG",
    [string]$ServerHost = "root@167.235.253.229",
    [switch]$SkipServerSync
)

$ErrorActionPreference = "Stop"

Write-Host "[drive] Current rclone config file:"
rclone config file

Write-Host ""
Write-Host "[drive] Current quota snapshot before reconnect:"
try {
    rclone about "${RemoteName}:"
} catch {
    Write-Warning "Could not read current quota snapshot."
}

Write-Host ""
Write-Host "[drive] Reconnecting remote '$RemoteName'."
Write-Host "[drive] In the browser, sign in with: $ExpectedEmail"
Write-Host "[drive] Keep the destination folder id as: $ExpectedRootFolderId"
rclone config reconnect "${RemoteName}:"

Write-Host ""
Write-Host "[drive] Quota snapshot after reconnect:"
rclone about "${RemoteName}:"

Write-Host ""
Write-Host "[drive] Checking target folder visibility through the new remote:"
rclone lsd "${RemoteName}:" --drive-root-folder-id "$ExpectedRootFolderId"

if (-not $SkipServerSync) {
    $configPath = Join-Path $env:APPDATA "rclone\rclone.conf"
    if (-not (Test-Path $configPath)) {
        throw "rclone.conf not found at $configPath"
    }
    Write-Host ""
    Write-Host "[drive] Syncing rclone.conf to Hetzner server..."
    ssh $ServerHost "mkdir -p /root/.config/rclone"
    scp $configPath "${ServerHost}:/root/.config/rclone/rclone.conf"
    Write-Host "[drive] Remote quota snapshot on server:"
    ssh $ServerHost "rclone about ${RemoteName}: || true"
}

Write-Host ""
Write-Host "[drive] Done. If the quota still looks like 15 GiB, the reconnect used the old account again."
