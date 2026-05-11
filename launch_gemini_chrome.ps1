$ErrorActionPreference = "Stop"

$profileDir = $env:GEMINI_CHAT_USER_DATA_DIR
if ([string]::IsNullOrWhiteSpace($profileDir)) {
    $profileDir = ".state/gemini_chat_user_data"
}

$port = $env:GEMINI_CHAT_REMOTE_DEBUGGING_PORT
if ([string]::IsNullOrWhiteSpace($port)) {
    $port = "9222"
}

$url = $env:GEMINI_CHAT_WEB_URL
if ([string]::IsNullOrWhiteSpace($url)) {
    $url = "https://gemini.google.com/app/b3006ba9f325b55c"
}

$profileText = [string]$profileDir
if ([System.IO.Path]::IsPathRooted($profileText)) {
    $resolvedProfile = [System.IO.Path]::GetFullPath($profileText)
} else {
    $resolvedProfile = [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $profileText))
}
New-Item -ItemType Directory -Force -Path $resolvedProfile | Out-Null

$candidates = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "$env:ProgramFiles(x86)\Google\Chrome\Application\chrome.exe",
    "$env:LocalAppData\Google\Chrome\Application\chrome.exe"
)

$chromePath = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $chromePath) {
    throw "chrome.exe not found in standard locations."
}

$args = @(
    "--remote-debugging-port=$port",
    "--user-data-dir=$resolvedProfile",
    "--disable-blink-features=AutomationControlled",
    $url
)

Write-Host "[gemini] launching Chrome with remote debugging on port $port"
Write-Host "[gemini] profile: $resolvedProfile"
Write-Host "[gemini] url: $url"
Start-Process -FilePath $chromePath -ArgumentList $args
