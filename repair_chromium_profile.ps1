param(
    [string]$ProfilePath = ".state/gemini_chat_user_data",
    [switch]$Apply,
    [switch]$IncludeSessionState
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$scriptRoot = if ($PSScriptRoot) {
    $PSScriptRoot
}
else {
    Split-Path -Parent $MyInvocation.MyCommand.Path
}

function Resolve-FullPath {
    param(
        [Parameter(Mandatory = $true)][string]$PathValue,
        [string]$BasePath = $scriptRoot
    )

    if ([System.IO.Path]::IsPathRooted($PathValue)) {
        return [System.IO.Path]::GetFullPath($PathValue)
    }

    return [System.IO.Path]::GetFullPath((Join-Path $BasePath $PathValue))
}

function Test-IsWithinPath {
    param(
        [Parameter(Mandatory = $true)][string]$BasePath,
        [Parameter(Mandatory = $true)][string]$CandidatePath
    )

    $normalizedBase = $BasePath.TrimEnd('\') + '\'
    return $CandidatePath.StartsWith($normalizedBase, [System.StringComparison]::OrdinalIgnoreCase)
}

function Get-TrackedItemSize {
    param([Parameter(Mandatory = $true)][System.IO.FileSystemInfo]$Item)

    if (-not $Item.Exists) {
        return 0L
    }

    if (-not $Item.PSIsContainer) {
        return [int64]$Item.Length
    }

    $measure = Get-ChildItem -LiteralPath $Item.FullName -Force -Recurse -File -ErrorAction SilentlyContinue |
        Measure-Object -Property Length -Sum
    if ($null -eq $measure.Sum) {
        return 0L
    }
    return [int64]$measure.Sum
}

function Format-Bytes {
    param([Parameter(Mandatory = $true)][int64]$Bytes)

    $units = @("B", "KB", "MB", "GB", "TB")
    $value = [double]$Bytes
    $unitIndex = 0
    while ($value -ge 1024 -and $unitIndex -lt ($units.Length - 1)) {
        $value /= 1024
        $unitIndex += 1
    }
    return "{0:N2} {1}" -f $value, $units[$unitIndex]
}

$workspaceRoot = Resolve-FullPath "."
$stateRoot = Resolve-FullPath ".state"
$resolvedProfile = Resolve-FullPath $ProfilePath

if (-not (Test-Path -LiteralPath $stateRoot -PathType Container)) {
    throw "State directory not found: $stateRoot"
}

if (-not (Test-Path -LiteralPath $resolvedProfile -PathType Container)) {
    throw "Profile directory not found: $resolvedProfile"
}

if (-not (Test-IsWithinPath -BasePath $stateRoot -CandidatePath $resolvedProfile)) {
    throw "Profile must be inside $stateRoot"
}

$anyBrowserProcesses = Get-Process chrome, msedge -ErrorAction SilentlyContinue

$browserProcesses = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
        $_.Name -in @("chrome.exe", "msedge.exe") -and
        $_.CommandLine -and
        $_.CommandLine.IndexOf($resolvedProfile, [System.StringComparison]::OrdinalIgnoreCase) -ge 0
    } |
    Select-Object ProcessId, Name, CommandLine

if ($browserProcesses) {
    Write-Host "Profile appears to be open in a running browser. Close it before repair."
    $browserProcesses | ForEach-Object {
        Write-Host (" - {0} (PID {1})" -f $_.Name, $_.ProcessId)
    }
    exit 2
}

if ($Apply -and $anyBrowserProcesses) {
    Write-Host "Warning: other Chrome/Edge processes are still running."
    Write-Host "Continuing because none of them appears to own the selected profile."
}

$relativeTargets = [System.Collections.Generic.List[string]]::new()
@(
    "component_crx_cache",
    "extensions_crx_cache",
    "GraphiteDawnCache",
    "GrShaderCache",
    "ShaderCache",
    "Default\\AutofillAiModelCache",
    "Default\\Cache",
    "Default\\Code Cache",
    "Default\\DawnGraphiteCache",
    "Default\\DawnWebGPUCache",
    "Default\\GPUCache",
    "Default\\Service Worker\\CacheStorage",
    "Default\\Service Worker\\ScriptCache",
    "Default\\Shared Dictionary\\cache",
    "Default\\optimization_guide_hint_cache_store",
    "Default\\optimization_guide_model_metadata_store"
) | ForEach-Object {
    [void]$relativeTargets.Add($_)
}

if ($IncludeSessionState) {
    @(
        "Default\\Network\\Network Persistent State",
        "Default\\Session Storage",
        "Default\\Sessions"
    ) | ForEach-Object {
        [void]$relativeTargets.Add($_)
    }
}

$trackedItems = [System.Collections.Generic.List[System.IO.FileSystemInfo]]::new()
foreach ($relativeTarget in $relativeTargets) {
    $candidatePath = Join-Path $resolvedProfile $relativeTarget
    if (-not (Test-Path -LiteralPath $candidatePath)) {
        continue
    }

    $item = Get-Item -LiteralPath $candidatePath -Force
    if (-not (Test-IsWithinPath -BasePath $resolvedProfile -CandidatePath $item.FullName) -and
        $item.FullName -ne $resolvedProfile) {
        throw "Refusing to touch path outside the selected profile: $($item.FullName)"
    }
    [void]$trackedItems.Add($item)
}

$lockNames = @("LOCK", "SingletonCookie", "SingletonLock", "SingletonSocket")
$lockItems = Get-ChildItem -LiteralPath $resolvedProfile -Force -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object { $lockNames -contains $_.Name }

foreach ($lockItem in $lockItems) {
    if (-not (Test-IsWithinPath -BasePath $resolvedProfile -CandidatePath $lockItem.FullName)) {
        throw "Refusing to touch lock path outside the selected profile: $($lockItem.FullName)"
    }
    [void]$trackedItems.Add($lockItem)
}

$dedupedItems = $trackedItems |
    Sort-Object -Property FullName -Unique

$filteredItems = [System.Collections.Generic.List[System.IO.FileSystemInfo]]::new()
foreach ($item in ($dedupedItems | Sort-Object -Property FullName.Length)) {
    $coveredByParent = $false
    foreach ($acceptedItem in $filteredItems) {
        if (-not $acceptedItem.PSIsContainer) {
            continue
        }
        $acceptedRoot = $acceptedItem.FullName.TrimEnd('\') + '\'
        if ($item.FullName.StartsWith($acceptedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
            $coveredByParent = $true
            break
        }
    }

    if (-not $coveredByParent) {
        [void]$filteredItems.Add($item)
    }
}

$totalBytes = 0L
foreach ($item in $filteredItems) {
    $totalBytes += Get-TrackedItemSize -Item $item
}

$mode = if ($Apply) { "apply" } else { "preview" }
Write-Host ("[repair] mode: {0}" -f $mode)
Write-Host ("[repair] workspace: {0}" -f $workspaceRoot)
Write-Host ("[repair] profile: {0}" -f $resolvedProfile)
Write-Host ("[repair] include session state: {0}" -f $IncludeSessionState.IsPresent)
Write-Host ("[repair] matched items: {0}" -f $filteredItems.Count)
Write-Host ("[repair] estimated cleanup size: {0}" -f (Format-Bytes -Bytes $totalBytes))

if (-not $filteredItems) {
    Write-Host "[repair] nothing to remove."
    exit 0
}

Write-Host "[repair] planned removals:"
$filteredItems | ForEach-Object {
    $kind = if ($_.PSIsContainer) { "dir " } else { "file" }
    Write-Host (" - [{0}] {1}" -f $kind, $_.FullName)
}

if (-not $Apply) {
    Write-Host ""
    Write-Host "Preview only. Re-run with -Apply to perform the cleanup."
    exit 0
}

foreach ($item in $filteredItems) {
    if (-not (Test-Path -LiteralPath $item.FullName)) {
        continue
    }
    if ($item.PSIsContainer) {
        Remove-Item -LiteralPath $item.FullName -Recurse -Force
    }
    else {
        Remove-Item -LiteralPath $item.FullName -Force
    }
}

Write-Host ""
Write-Host "[repair] cleanup finished."
Write-Host "[repair] preserved files include Local State, Preferences, Secure Preferences,"
Write-Host "[repair] storage_state JSON files, and auth JSON files under .state."
