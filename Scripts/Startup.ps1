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
$pidFile = Join-Path $RepoRoot ".sf2ais-server.pid"
function Test-LocalGatewayPort {
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $pending = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        if (-not $pending.AsyncWaitHandle.WaitOne(1500)) { return $false }
        $client.EndConnect($pending)
        return $true
    } catch {
        return $false
    } finally {
        $client.Dispose()
    }
}
$already = $null
if (Test-Path $pidFile) {
    $savedPid = 0
    if ([int]::TryParse((Get-Content $pidFile -Raw).Trim(), [ref]$savedPid)) {
        $candidate = Get-CimInstance Win32_Process -Filter "ProcessId = $savedPid" -ErrorAction SilentlyContinue
        if ($candidate -and $candidate.CommandLine -match "uvicorn\s+main:app" -and $candidate.CommandLine -match "--port\s+$Port(\s|$)") {
            $already = $candidate
        }
    }
}
if (-not $already -and (Test-LocalGatewayPort)) {
    Write-Error "Port $Port is already accepting connections, but the process does not match the SF2AIS PID record. Refusing to start a duplicate server."
    exit 1
}

if ($already) {
    Write-Output "SF2AIS server already running (PID $($already.ProcessId))."
} else {
    if (-not (Test-Path (Join-Path $RepoRoot "main.py"))) {
        Write-Error "main.py not found in $RepoRoot. Run this from the SF2AIS repo root."
        exit 1
    }
    # Prefer the project's CUA-enabled venv, then the standard venv, then system Python.
    $python = "python"
    $venvCandidates = @(
        (Join-Path $RepoRoot ".venv-cua\Scripts\python.exe"),
        (Join-Path $RepoRoot ".venv\Scripts\python.exe"),
        (Join-Path $RepoRoot "venv\Scripts\python.exe")
    )
    foreach ($candidate in $venvCandidates) {
        if (Test-Path $candidate) { $python = $candidate; break }
    }

    $stdoutLog = Join-Path $RepoRoot "logs\sf2ais-server.log"
    $stderrLog = Join-Path $RepoRoot "logs\sf2ais-server-error.log"
    $job = Start-Process -FilePath $python `
        -ArgumentList "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", $Port, "--proxy-headers", "--forwarded-allow-ips", "127.0.0.1" `
        -WorkingDirectory $RepoRoot `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog `
        -WindowStyle Hidden `
        -PassThru
    Set-Content -Path $pidFile -Value $job.Id
    $running = $null
    $listener = $false
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        $running = Get-CimInstance Win32_Process -Filter "ProcessId = $($job.Id)" -ErrorAction SilentlyContinue
        $listener = Test-LocalGatewayPort
        if ($running -and $listener) { break }
        Start-Sleep -Seconds 1
    }
    if (-not $running -or -not $listener) {
        Write-Error "SF2AIS failed to start. Inspect logs\sf2ais-server-error.log."
        exit 1
    }
    Write-Output "SF2AIS server running (PID $($job.Id)) on 127.0.0.1:$Port using $python."
}

# --- 2. Open the dashboard in the default browser ---------------------------
Start-Process "http://localhost:$Port/workspace"

# --- 3. Register the probe scheduled task (self-elevating) ------------------
if (-not $NoProbe) {
    $probeScript = Join-Path $PSScriptRoot "Startup-win.ps1"
    if (Test-Path $probeScript) {
        Write-Output "Registering the desktop probe scheduled task..."
        & $probeScript
    } else {
        Write-Warning 'Startup-win.ps1 not found; skipping probe task registration.'
    }
}

Write-Output 'SF2AiS is up. Shared workspace: http://localhost:8000/workspace'
