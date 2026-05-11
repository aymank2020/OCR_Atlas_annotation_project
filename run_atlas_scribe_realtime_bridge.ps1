param(
    [string]$Host = "127.0.0.1",
    [int]$Port = 8765
)

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython = Join-Path $ProjectRoot ".venv\\Scripts\\python.exe"

if (Test-Path $VenvPython) {
    $PythonExe = $VenvPython
    $Args = @("-m", "uvicorn", "atlas_scribe_realtime_api:app", "--host", $Host, "--port", "$Port")
} else {
    $PythonExe = "py"
    $Args = @("-3.11", "-m", "uvicorn", "atlas_scribe_realtime_api:app", "--host", $Host, "--port", "$Port")
}

Push-Location $ProjectRoot
try {
    & $PythonExe @Args
} finally {
    Pop-Location
}
