<#
.SYNOPSIS
    SF2AIS server startup helper (Windows).

.DESCRIPTION
    Starts the SF2AIS gateway server (uvicorn) in the background and,
    optionally, registers the desktop probe as a Windows scheduled task so the
    IP updater runs automatically.

    This is the recommended way to launch SF2AIS on Windows. It is idempotent:
    re-running it will not spawn duplicate server processes.

.PARAMETER NoProbe
    Skip registering the probe scheduled task.

.PARAMETER Port
    Port the gateway listens on (default 8000).

.EXAMPLE
    pwsh -ExecutionPolicy Bypass -File Scripts\Startup.ps1
#>

param(
    [switch]$NoProbe,
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

# --- 1. Start the gateway server (uvicorn) if not already running ----------
$already = Get-Process -Name python*, pythonw* -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*uvicorn main:app*" }

if ($already) {
    Write-Output "SF2AIS server already running (PID $($already[0].Id))."
} else {
    if (-not (Test-Path (Join-Path $RepoRoot "main.py"))) {
        Write-Error "main.py not found in $RepoRoot. Run this from the SF2AIS repo root."
        exit 1
    }
    # Prefer the repo venv if present, else system python
    $python = "python"
    $venvPy = Join-Path $RepoRoot "venv" "Scripts" "python.exe"
    if (Test-Path $venvPy) { $python = $venvPy }

    $job = Start-Process -FilePath $python `
        -ArgumentList "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", $Port `
        -WorkingDirectory $RepoRoot `
        -WindowStyle Hidden `
        -PassThru
    Write-Output "SF2AIS server starting (PID $($job.Id)) on port $Port..."
    Start-Sleep -Seconds 2
}

# --- 2. Open the dashboard in the default browser ---------------------------
Start-Process "http://localhost:$Port/dashboard"

# --- 3. Register the probe scheduled task (self-elevating) ------------------
if (-not $NoProbe) {
    $probeScript = Join-Path $PSScriptRoot "Startup-win.ps1"
    if (Test-Path $probeScript) {
        Write-Output "Registering the desktop probe scheduled task..."
        & $probeScript
    } else {
        Write-Warning "Startup-win.ps1 not found — skipping probe task registration."
    }
}

Write-Output "SF2AIS is up. Open http://localhost:$Port/dashboard to configure."
