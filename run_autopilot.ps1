param(
    [string]$Config = "sample_web_auto_solver.yaml",
    [switch]$NoExecute,
    [switch]$NoWhatsapp,
    [switch]$NoDiscord,
    [switch]$HeadlessCollectors,
    [switch]$AutoRestartSolver,
    [int]$SolverMaxRestarts = 20,
    [int]$SolverRestartDelaySec = 10,
    [int]$CollectorRestartDelaySec = 8
)

$ErrorActionPreference = "Stop"

$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$supervisorLog = "outputs\supervisor_live_$ts.log"
$supervisorErrLog = "outputs\supervisor_live_$ts.err.log"
$incidentLog = "outputs\ops_incidents_$ts.jsonl"
$actionLog = "outputs\ops_actions_$ts.jsonl"

$args = @(
    "atlas_training_supervisor.py",
    "--config", $Config,
    "--collector-restart-delay-sec", "$CollectorRestartDelaySec",
    "--incident-log", $incidentLog,
    "--action-log", $actionLog
)

if (-not $NoExecute) { $args += "--execute" }
if (-not $NoWhatsapp) { $args += "--with-whatsapp" }
if (-not $NoDiscord) { $args += "--with-discord" }
if ($HeadlessCollectors) { $args += "--headless-collectors" }
if ($AutoRestartSolver) {
    $args += "--auto-restart-solver"
    $args += "--solver-max-restarts"; $args += "$SolverMaxRestarts"
    $args += "--solver-restart-delay-sec"; $args += "$SolverRestartDelaySec"
}

$p = Start-Process python `
    -ArgumentList $args `
    -RedirectStandardOutput $supervisorLog `
    -RedirectStandardError $supervisorErrLog `
    -PassThru

Write-Host "[autopilot] started supervisor pid=$($p.Id)"
Write-Host "[autopilot] supervisor log: $supervisorLog"
Write-Host "[autopilot] supervisor err: $supervisorErrLog"
Write-Host "[autopilot] incident log:   $incidentLog"
Write-Host "[autopilot] action log:     $actionLog"
Write-Host "[autopilot] stop command:   Stop-Process -Id $($p.Id) -Force"

while (-not (Test-Path $supervisorLog)) { Start-Sleep -Seconds 1 }
Get-Content $supervisorLog -Tail 200 -Wait
