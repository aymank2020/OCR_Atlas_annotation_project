# ═══════════════════════════════════════════════════════════════════
# Atlas Scribe — Auto-Start Setup
# Registers a Windows Task Scheduler task to run Scribe at logon
# Usage: Run this once as Administrator
# ═══════════════════════════════════════════════════════════════════

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$batPath = Join-Path $scriptDir "Run_Atlas_Scribe.bat"
$taskName = "Atlas Scribe Auto-Start"

Write-Host ""
Write-Host "╔════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║      🎙️  Atlas Scribe — Auto-Start Setup              ║" -ForegroundColor Cyan
Write-Host "╚════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# Check if bat exists
if (-not (Test-Path $batPath)) {
    Write-Host "❌ ERROR: Run_Atlas_Scribe.bat not found at: $batPath" -ForegroundColor Red
    exit 1
}

# Check existing task
$existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existingTask) {
    Write-Host "⚠️  Task '$taskName' already exists." -ForegroundColor Yellow
    $choice = Read-Host "Overwrite? (y/n)"
    if ($choice -ne 'y') {
        Write-Host "Cancelled." -ForegroundColor Gray
        exit 0
    }
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "   Old task removed." -ForegroundColor Gray
}

# Create the task
Write-Host "📝 Creating scheduled task..." -ForegroundColor White

$action = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"$batPath`"" `
    -WorkingDirectory $scriptDir

$trigger = New-ScheduledTaskTrigger -AtLogOn

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 365)

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -RunLevel Limited

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Atlas Scribe — Real-Time Audio Intelligence. Dashboard at http://localhost:8501/" `
    -Force

Write-Host ""
Write-Host "✅ Task '$taskName' created successfully!" -ForegroundColor Green
Write-Host ""
Write-Host "   📌 Scribe will auto-start at every Windows logon" -ForegroundColor White
Write-Host "   📌 Dashboard: http://localhost:8501/" -ForegroundColor White
Write-Host "   📌 To remove: Unregister-ScheduledTask -TaskName '$taskName'" -ForegroundColor Gray
Write-Host ""

# Offer to start now
$startNow = Read-Host "Start Scribe now? (y/n)"
if ($startNow -eq 'y') {
    Write-Host "🚀 Starting Atlas Scribe..." -ForegroundColor Cyan
    Start-Process -FilePath "cmd.exe" -ArgumentList "/c `"$batPath`"" -WorkingDirectory $scriptDir
    Start-Sleep -Seconds 3
    Write-Host "✅ Scribe is running! Open http://localhost:8501/" -ForegroundColor Green
}

Write-Host ""
Write-Host "Done!" -ForegroundColor Green
