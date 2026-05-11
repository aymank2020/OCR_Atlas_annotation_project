param(
    [Parameter(Mandatory = $true)]
    [Alias("Host", "HostName", "TargetHost")]
    [string]$VpsHost,

    [Parameter(Mandatory = $true)]
    [string]$User,

    [string]$RemoteDir = "/srv/atlas/OCR_annotation_Atlas",
    [string]$SourceDir = (Get-Location).Path,
    [int]$Port = 22,
    [string]$KeyPath = "",
    [string]$HostKeySha256 = "",
    [string]$HostPublicKey = "",
    [int]$ChunkSizeMB = 32,
    [int]$MaxUploadRetries = 5,

    [switch]$IncludeOutputs,
    [switch]$IncludeState,
    [switch]$NoChunking,
    [switch]$SkipVerify,
    [switch]$DryRun,
    [switch]$KeepStage
)

$ErrorActionPreference = "Stop"

function Invoke-RobocopySafe {
    param(
        [Parameter(Mandatory = $true)][string[]]$Args
    )
    & robocopy @Args | Out-Null
    $code = $LASTEXITCODE
    if ($code -ge 8) {
        throw "robocopy failed with exit code $code"
    }
}

function Quote-Bash {
    param(
        [Parameter(Mandatory = $true)][string]$Value
    )
    return "'" + $Value.Replace("'", "'""'""'") + "'"
}

function Require-Command {
    param(
        [Parameter(Mandatory = $true)][string]$Name
    )
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command not found: $Name"
    }
}

function Get-RemoteFileSize {
    param(
        [Parameter(Mandatory = $true)][string[]]$SshArgs,
        [Parameter(Mandatory = $true)][string]$Target,
        [Parameter(Mandatory = $true)][string]$RemotePath
    )
    $rpQ = Quote-Bash $RemotePath
    $cmd = "if [ -f $rpQ ]; then wc -c < $rpQ; else echo 0; fi"
    $raw = (& ssh @SshArgs $Target $cmd 2>$null | Select-Object -Last 1)
    if ($null -eq $raw) { return 0L }
    $txt = $raw.ToString().Trim()
    $size = 0L
    if ([long]::TryParse($txt, [ref]$size)) {
        return $size
    }
    return 0L
}

function Upload-WithRetry {
    param(
        [Parameter(Mandatory = $true)][string[]]$ScpArgs,
        [Parameter(Mandatory = $true)][string]$LocalPath,
        [Parameter(Mandatory = $true)][string]$Target,
        [Parameter(Mandatory = $true)][string]$RemotePath,
        [Parameter(Mandatory = $true)][int]$Retries
    )
    for ($attempt = 1; $attempt -le $Retries; $attempt++) {
        & scp @ScpArgs $LocalPath "$Target`:$RemotePath"
        if ($LASTEXITCODE -eq 0) {
            return
        }
        if ($attempt -ge $Retries) {
            throw "SCP upload failed after $Retries attempts: $LocalPath"
        }
        $sleepSec = [math]::Min(30, [math]::Pow(2, $attempt))
        Write-Host "[migrate] upload retry $attempt/$Retries failed, sleeping ${sleepSec}s..."
        Start-Sleep -Seconds $sleepSec
    }
}

function Split-Archive {
    param(
        [Parameter(Mandatory = $true)][string]$ArchivePath,
        [Parameter(Mandatory = $true)][int]$ChunkBytes,
        [Parameter(Mandatory = $true)][switch]$DisableChunking
    )
    $archiveLen = (Get-Item $ArchivePath).Length
    if ($DisableChunking -or $archiveLen -le $ChunkBytes) {
        return @($ArchivePath)
    }

    $partsDir = Join-Path (Split-Path $ArchivePath -Parent) "parts"
    New-Item -ItemType Directory -Path $partsDir -Force | Out-Null

    $parts = New-Object System.Collections.Generic.List[string]
    $buffer = New-Object byte[] $ChunkBytes
    $src = [System.IO.File]::OpenRead($ArchivePath)
    try {
        $idx = 0
        while (($read = $src.Read($buffer, 0, $buffer.Length)) -gt 0) {
            $partPath = Join-Path $partsDir ("payload.part{0:D4}" -f $idx)
            $dst = [System.IO.File]::Open($partPath, [System.IO.FileMode]::Create, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
            try {
                $dst.Write($buffer, 0, $read)
            } finally {
                $dst.Dispose()
            }
            $parts.Add($partPath)
            $idx++
        }
    } finally {
        $src.Dispose()
    }
    return $parts.ToArray()
}

Require-Command ssh
Require-Command scp
Require-Command tar
Require-Command robocopy
Require-Command ssh-keyscan
Require-Command ssh-keygen

$sourceFull = (Resolve-Path $SourceDir).Path
$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$stageRoot = Join-Path $env:TEMP "ocr_atlas_stage_$ts"
$stageDir = Join-Path $stageRoot "payload"
$archivePath = Join-Path $stageRoot "payload.tar.gz"
$knownHostsPath = Join-Path $stageRoot "known_hosts"

New-Item -ItemType Directory -Path $stageDir -Force | Out-Null

$excludeDirs = @(
    ".git",
    ".idea",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "project_info",
    ".state",
    ".state\edge_user_data_clone",
    ".state\chrome_user_data_clone",
    ".state\whatsapp_profile",
    ".state\chrome_user_data_link"
)
if (-not $IncludeOutputs) {
    $excludeDirs += "outputs"
}

$excludeFiles = @(
    "*.mp4",
    "*.webm",
    "*.avi",
    "*.mkv",
    "*.mov",
    "*.png",
    "*.jpg",
    "*.jpeg",
    "*.log",
    "*.zip",
    "*.tar",
    "*.gz",
    "*.part",
    "*.tmp"
)

$excludeDirArgs = @()
foreach ($d in $excludeDirs) {
    $excludeDirArgs += (Join-Path $sourceFull $d)
}

$roboArgs = @(
    $sourceFull,
    $stageDir,
    "/E",
    "/R:1",
    "/W:1",
    "/XJ",
    "/NFL",
    "/NDL",
    "/NP",
    "/NJH",
    "/NJS",
    "/XD"
) + $excludeDirArgs + @("/XF") + $excludeFiles

Write-Host "[migrate] building staging payload..."
Invoke-RobocopySafe -Args $roboArgs

if ($IncludeState) {
    $stateRoot = Join-Path $sourceFull ".state"
    if (Test-Path $stateRoot) {
        $stateTargetRoot = Join-Path $stageDir ".state"
        New-Item -ItemType Directory -Path $stateTargetRoot -Force | Out-Null

        Get-ChildItem -Path $stateRoot -File -Filter "atlas_auth*.json" -ErrorAction SilentlyContinue | ForEach-Object {
            Copy-Item $_.FullName (Join-Path $stateTargetRoot $_.Name) -Force
        }

        $accountsRoot = Join-Path $stateRoot "accounts"
        if (Test-Path $accountsRoot) {
            Get-ChildItem -Path $accountsRoot -Recurse -File -Filter "*.json" -ErrorAction SilentlyContinue | ForEach-Object {
                $relative = $_.FullName.Substring($stateRoot.Length + 1)
                $targetPath = Join-Path $stateTargetRoot $relative
                New-Item -ItemType Directory -Path (Split-Path $targetPath -Parent) -Force | Out-Null
                Copy-Item $_.FullName $targetPath -Force
            }
        }
    }
}

$manifestPath = Join-Path $stageDir "deploy_manifest.sha256"
$files = Get-ChildItem -Path $stageDir -Recurse -File | Where-Object { $_.FullName -ne $manifestPath } | Sort-Object FullName
$manifestLines = @()
foreach ($f in $files) {
    $hash = (Get-FileHash -Path $f.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    $rel = $f.FullName.Substring($stageDir.Length + 1).Replace("\", "/")
    $manifestLines += "$hash *$rel"
}
$manifestContent = if ($manifestLines.Count -gt 0) { ($manifestLines -join "`n") + "`n" } else { "" }
[System.IO.File]::WriteAllText($manifestPath, $manifestContent, (New-Object System.Text.UTF8Encoding($false)))

$totalBytes = ($files | Measure-Object -Property Length -Sum).Sum
if (-not $totalBytes) { $totalBytes = 0 }
$totalMb = [math]::Round($totalBytes / 1MB, 2)
Write-Host "[migrate] staging ready: files=$($files.Count) size=${totalMb}MB"
Write-Host "[migrate] creating archive..."
& tar -C $stageDir -czf $archivePath .
if ($LASTEXITCODE -ne 0) {
    throw "tar archive creation failed."
}

$archiveMb = [math]::Round(((Get-Item $archivePath).Length / 1MB), 2)
Write-Host "[migrate] archive ready: $archivePath (${archiveMb}MB)"
$archiveHash = (Get-FileHash -Path $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Host "[migrate] archive sha256: $archiveHash"

$strictHostCheck = "accept-new"
if ($HostKeySha256 -and $HostKeySha256.Trim()) {
    $scan = @()
    if ($HostPublicKey -and $HostPublicKey.Trim()) {
        $provided = $HostPublicKey.Trim()
        $hostPrefix = if ($Port -eq 22) { $VpsHost } else { "[$VpsHost]:$Port" }
        if ($provided -match "^\S+\s+ssh-(ed25519|rsa|ecdsa|dss)\s+") {
            $scan = @($provided)
        } else {
            if ($provided -notmatch "^ssh-(ed25519|rsa|ecdsa|dss)\s+") {
                throw "Invalid HostPublicKey format. Expected 'ssh-ed25519 AAAA...'."
            }
            $scan = @("$hostPrefix $provided")
        }
    } else {
        $nativeErrPrefVar = Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue
        $nativeErrPrefOld = $null
        if ($nativeErrPrefVar) {
            $nativeErrPrefOld = [bool]$nativeErrPrefVar.Value
            $script:PSNativeCommandUseErrorActionPreference = $false
        }
        try {
            $scanArgSets = @(
                @("-T", "10", "-p", "$Port", $VpsHost),
                @("-p", "$Port", $VpsHost),
                @($VpsHost)
            )
            foreach ($argSet in $scanArgSets) {
                try {
                    $raw = & ssh-keyscan @argSet 2>$null
                    if ($LASTEXITCODE -ne 0 -or -not $raw) {
                        continue
                    }
                    $filtered = @(
                        $raw | Where-Object {
                            $_ -and
                            ($_ -notmatch "^\s*#") -and
                            ($_ -match "\bssh-(ed25519|rsa|ecdsa|dss)\b")
                        }
                    )
                    if ($filtered.Count -gt 0) {
                        $scan = $filtered
                        break
                    }
                } catch {
                    continue
                }
            }
        } finally {
            if ($nativeErrPrefVar) {
                $script:PSNativeCommandUseErrorActionPreference = $nativeErrPrefOld
            }
        }
    }
    if (-not $scan -or $scan.Count -eq 0) {
        throw "Failed to fetch host key via ssh-keyscan."
    }
    [System.IO.File]::WriteAllText($knownHostsPath, ($scan -join "`n") + "`n")
    $fpLines = $scan | & ssh-keygen -lf - -E sha256 2>$null

    $expectedFp = $HostKeySha256.Trim()
    if ($expectedFp -notmatch "^SHA256:") {
        $expectedFp = "SHA256:$expectedFp"
    }
    $matched = $false
    foreach ($line in $fpLines) {
        if ($line -match "(SHA256:[A-Za-z0-9+/=]+)" -and $Matches[1] -eq $expectedFp) {
            $matched = $true
            break
        }
    }
    if (-not $matched) {
        throw "Host key fingerprint mismatch. Expected $expectedFp."
    }
    $strictHostCheck = "yes"
    Write-Host "[migrate] host key verified: $expectedFp"
} else {
    Write-Warning "[migrate] HostKeySha256 not provided. For strict pinning, pass -HostKeySha256."
}

if ($DryRun) {
    Write-Host "[migrate] dry-run mode: stopping before transfer."
    if (-not $KeepStage) {
        Remove-Item -Recurse -Force $stageRoot
    } else {
        Write-Host "[migrate] kept stage: $stageRoot"
    }
    return
}

$sshArgs = @(
    "-p", "$Port",
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=20",
    "-o", "ServerAliveInterval=15",
    "-o", "ServerAliveCountMax=3",
    "-o", "StrictHostKeyChecking=$strictHostCheck"
)
if ($KeyPath -and $KeyPath.Trim()) {
    $resolvedKey = (Resolve-Path $KeyPath).Path
    $sshArgs += @("-i", $resolvedKey)
}
if (Test-Path $knownHostsPath) {
    $sshArgs += @("-o", "UserKnownHostsFile=$knownHostsPath")
}

$scpArgs = @(
    "-P", "$Port",
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=20",
    "-o", "ServerAliveInterval=15",
    "-o", "ServerAliveCountMax=3",
    "-o", "StrictHostKeyChecking=$strictHostCheck"
)
if ($KeyPath -and $KeyPath.Trim()) {
    $resolvedKey = (Resolve-Path $KeyPath).Path
    $scpArgs += @("-i", $resolvedKey)
}
if (Test-Path $knownHostsPath) {
    $scpArgs += @("-o", "UserKnownHostsFile=$knownHostsPath")
}

$remoteArchive = "/tmp/ocr_atlas_payload_$ts.tar.gz"
$remoteExtract = "/tmp/ocr_atlas_extract_$ts"
$target = "$User@$VpsHost"
$remoteArchiveQ = Quote-Bash $remoteArchive
$remoteExtractQ = Quote-Bash $remoteExtract

Write-Host "[migrate] testing SSH connection..."
& ssh @sshArgs $target "echo connected"
if ($LASTEXITCODE -ne 0) {
    throw "SSH connection failed."
}

$remoteDirInput = ""
if ($null -ne $RemoteDir) {
    $remoteDirInput = [string]$RemoteDir
}
$remoteDirInput = $remoteDirInput.Trim()
if (-not $remoteDirInput) {
    $remoteDirInput = "~/OCR_annotation_Atlas"
}

if ($remoteDirInput.StartsWith("/")) {
    $remoteDirResolved = $remoteDirInput
} else {
    $remoteHomeRaw = & ssh @sshArgs $target 'printf "%s" "$HOME"'
    if ($LASTEXITCODE -ne 0 -or -not $remoteHomeRaw) {
        throw "Failed to resolve remote HOME directory."
    }
    $remoteHome = ($remoteHomeRaw | Select-Object -Last 1).ToString().Trim()
    if (-not $remoteHome) {
        throw "Failed to resolve remote HOME directory."
    }
    if ($remoteDirInput -eq "~") {
        $remoteDirResolved = $remoteHome
    } elseif ($remoteDirInput.StartsWith("~/")) {
        $remoteDirResolved = "$remoteHome/" + $remoteDirInput.Substring(2)
    } elseif ($remoteDirInput.StartsWith("~")) {
        throw "Unsupported RemoteDir format '$remoteDirInput'. Use absolute path or ~/path."
    } else {
        $remoteDirResolved = "$remoteHome/$remoteDirInput"
    }
}

$remoteDirQ = Quote-Bash $remoteDirResolved
$remoteBackup = "$remoteDirResolved.backup_$ts"
$remoteBackupQ = Quote-Bash $remoteBackup
Write-Host "[migrate] resolved remote dir: $remoteDirResolved"

$chunkBytes = [math]::Max(1MB, $ChunkSizeMB * 1MB)
$parts = Split-Archive -ArchivePath $archivePath -ChunkBytes $chunkBytes -DisableChunking:$NoChunking
$chunked = $parts.Count -gt 1

if ($chunked) {
    Write-Host "[migrate] uploading in chunks: $($parts.Count) part(s), chunk=${ChunkSizeMB}MB"
    for ($idx = 0; $idx -lt $parts.Count; $idx++) {
        $partPath = $parts[$idx]
        $remotePart = "$remoteArchive.part{0:D4}" -f $idx
        $localSize = (Get-Item $partPath).Length
        $remoteSize = Get-RemoteFileSize -SshArgs $sshArgs -Target $target -RemotePath $remotePart
        if ($remoteSize -eq $localSize) {
            Write-Host "[migrate] chunk $idx already present on VPS, skipping."
            continue
        }
        Write-Host "[migrate] uploading chunk $idx/$($parts.Count - 1)..."
        Upload-WithRetry -ScpArgs $scpArgs -LocalPath $partPath -Target $target -RemotePath $remotePart -Retries $MaxUploadRetries
        $remoteSizeAfter = Get-RemoteFileSize -SshArgs $sshArgs -Target $target -RemotePath $remotePart
        if ($remoteSizeAfter -ne $localSize) {
            throw "Chunk size mismatch after upload for $remotePart"
        }
    }

    Write-Host "[migrate] assembling archive on VPS..."
    $assembleCmd = "cat $remoteArchive.part* > $remoteArchiveQ && rm -f $remoteArchive.part*"
    & ssh @sshArgs $target $assembleCmd
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to assemble archive chunks on VPS."
    }
} else {
    Write-Host "[migrate] uploading archive to VPS..."
    Upload-WithRetry -ScpArgs $scpArgs -LocalPath $archivePath -Target $target -RemotePath $remoteArchive -Retries $MaxUploadRetries
}

Write-Host "[migrate] verifying uploaded archive hash..."
$remoteArchiveHash = (& ssh @sshArgs $target "sha256sum $remoteArchiveQ | cut -d ' ' -f1" | Select-Object -Last 1).ToString().Trim().ToLowerInvariant()
if (-not $remoteArchiveHash) {
    throw "Failed to compute remote archive hash."
}
if ($remoteArchiveHash -ne $archiveHash) {
    throw "Archive hash mismatch. local=$archiveHash remote=$remoteArchiveHash"
}

Write-Host "[migrate] extracting on VPS with backup..."
$extractCmd = @"
set -e
rm -rf $remoteExtractQ
mkdir -p $remoteExtractQ
tar -xzf $remoteArchiveQ -C $remoteExtractQ
if [ -d $remoteDirQ ]; then
  rm -rf $remoteBackupQ
  mv $remoteDirQ $remoteBackupQ
fi
mv $remoteExtractQ $remoteDirQ
rm -f $remoteArchiveQ
"@
& ssh @sshArgs $target $extractCmd
if ($LASTEXITCODE -ne 0) {
    throw "Remote extract failed."
}

if (-not $SkipVerify) {
    Write-Host "[migrate] verifying SHA256 manifest on VPS..."
    $verifyCmd = "cd $remoteDirQ && tr -d '\r' < deploy_manifest.sha256 > deploy_manifest.sha256.lf && sha256sum -c deploy_manifest.sha256.lf && rm -f deploy_manifest.sha256.lf"
    & ssh @sshArgs $target $verifyCmd
    if ($LASTEXITCODE -ne 0) {
        throw "Remote checksum verification failed."
    }
}

Write-Host "[migrate] done."
Write-Host "[migrate] remote path: $remoteDirResolved"
Write-Host "[migrate] remote backup: $remoteBackup"
if (-not $KeepStage) {
    Remove-Item -Recurse -Force $stageRoot
} else {
    Write-Host "[migrate] kept stage: $stageRoot"
}
