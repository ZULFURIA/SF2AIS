<#
.SYNOPSIS
    Creates a Windows Task Scheduler entry for the Sf2AiS Probe desktop app.

.DESCRIPTION
    Runs the Sf2AiS Probe Electron app at Windows logon and repeats every 5
    minutes so the IP updater runs automatically in the background.

    Registering a scheduled task requires administrator rights. If this script
    is not run elevated it will re-launch itself with a UAC prompt.

.PARAMETER AppPath
    Full path to the packaged Electron executable.

.PARAMETER AppDir
    Working directory for the app (used when launching from development).

.PARAMETER ConfigDir
    Path to the probe's config/log directory.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File "Startup-win.ps1" -AppPath "C:\Program Files\Sf2AiS Probe\sf2ais-probe.exe"
#>

param(
    [string]$AppPath = "",
    [string]$AppDir = "",
    [string]$ConfigDir = "$env:USERPROFILE\.sf2ais-probe"
)

$ErrorActionPreference = "Stop"

# --- Self-elevation: re-launch as admin if not already elevated ---------------
function Test-IsAdmin {
    $id = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object System.Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-IsAdmin)) {
    Write-Output "Requesting administrator rights to register the scheduled task..."
    $args = "-ExecutionPolicy Bypass -NoProfile -File `"" + $MyInvocation.MyCommand.Path + "`""
    if ($AppPath)      { $args += " -AppPath `"" + $AppPath + "`"" }
    if ($AppDir)       { $args += " -AppDir `"" + $AppDir + "`"" }
    if ($ConfigDir)    { $args += " -ConfigDir `"" + $ConfigDir + "`"" }
    Start-Process powershell.exe -Verb RunAs -ArgumentList $args
    exit 0
}

$taskName = "Sf2AiS Probe"

# --- Resolve the executable if not supplied or not found ----------------------
function Find-ProbeExe {
    param([string]$Hint)
    if ($Hint -and (Test-Path $Hint)) { return $Hint }

    # Common packaged / build locations, in priority order
    $candidates = @(
        "$env:LOCALAPPDATA\Sf2AiS-Probe\sf2ais-probe.exe"
        "$env:LOCALAPPDATA\Programs\Sf2AiS Probe\sf2ais-probe.exe"
        "$env:ProgramFiles\Sf2AiS Probe\sf2ais-probe.exe"
        (Join-Path $PSScriptRoot "..\dist\sf2ais-probe-portable.exe")
        (Join-Path $PSScriptRoot "..\dist\Sf2AiS Probe Setup 1.0.0.exe")
    )
    foreach ($c in $candidates) {
        if ($c -and (Test-Path $c)) { return $c }
    }
    return $null
}

$resolved = Find-ProbeExe -Hint $AppPath
if (-not $resolved) {
    Write-Error "Sf2AiS Probe executable not found. Install the app first, or pass -AppPath explicitly."
    exit 1
}
Write-Output "Using executable: $resolved"

# --- Build the task -----------------------------------------------------------
if ($AppDir -and -not $resolved.EndsWith(".exe")) {
    # Development mode: Electron needs the app directory as an argument
    $action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$resolved`" `"$AppDir`""
    $workDir = $AppDir
} else {
    $action = New-ScheduledTaskAction -Execute $resolved -WorkingDirectory (Split-Path $resolved)
    $workDir = (Split-Path $resolved)
}

$logonTrigger   = New-ScheduledTaskTrigger -AtLogOn
$scheduleTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 5) `
    -RepetitionDuration (New-TimeSpan -Days 365)

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Highest

try {
    $existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($existing) {
        # Remove then recreate to guarantee a clean, consistent definition
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    }
    Register-ScheduledTask -TaskName $taskName `
        -Action $action `
        -Trigger $logonTrigger, $scheduleTrigger `
        -Settings $settings `
        -Principal $principal `
        -Force | Out-Null
    Write-Output "Scheduled task '$taskName' registered (logon + every 5 min)."
    Write-Output "Executable: $resolved"
    Write-Output "Working directory: $workDir"
    Write-Output "Config directory: $ConfigDir"
} catch {
    Write-Error "Failed to register scheduled task: $_"
    exit 1
}
