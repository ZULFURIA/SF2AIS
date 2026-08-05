<#
.SYNOPSIS
    Creates a Windows Task Scheduler entry for the Sf2AiS Probe desktop app.
.DESCRIPTION
    This script creates a scheduled task that launches the Sf2AiS Probe Electron app
    at Windows logon and repeats every 5 minutes (matching the documented probe schedule),
    so the IP updater runs automatically in the background.
    The task is configured to run with the highest privileges and to restart
    on failure.
.PARAMETER AppPath
    Full path to the Electron executable or packaged app.
.PARAMETER AppDir
    Working directory for the app (used when launching from development).
.PARAMETER ConfigDir
    Path to the probe's config/log directory (e.g. %USERPROFILE%\.sf2ais-probe).
.EXAMPLE
    powershell -ExecutionPolicy Bypass -NoProfile -File "create-task.ps1" -AppPath "C:\Program Files\sf2ais-probe\sf2ais-probe.exe"
#>

param(
    [Parameter(Mandatory=$true)]
    [string]$AppPath,

    [string]$AppDir = "",

    [string]$ConfigDir = "$env:USERPROFILE\.sf2ais-probe"
)

$ErrorActionPreference = "Stop"

$taskName = "Sf2AiS Probe"

# Validate the app path
if (-not (Test-Path $AppPath)) {
    Write-Error "App not found at: $AppPath"
    exit 1
}

# Build the action — if AppDir is provided and the appPath doesn't look like a packaged exe,
# use "executable, workingdir" format for development mode
if ($AppDir -and -not $AppPath.EndsWith(".exe")) {
    # Development mode: Electron needs the app directory as an argument
    $action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$AppPath`" `"$AppDir`""
} else {
    # Packaged mode: just run the exe
    $action = New-ScheduledTaskAction -Execute $AppPath -WorkingDirectory (Split-Path $AppPath)
}

# Two triggers:
# 1. At log on (so it starts when Windows starts)
# 2. Every 5 minutes (matching the documented probe check schedule)
$logonTrigger = New-ScheduledTaskTrigger -AtLogOn
$scheduleTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 365)

# Allow task to be run on demand
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleTasks = $true

$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Highest

# Register or update the task
try {
    $existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($existing) {
        Set-ScheduledTask -TaskName $taskName -Action $action -Trigger $logonTrigger,$scheduleTrigger -Settings $settings -Principal $principal
        Write-Output "Updated existing task '$taskName'"
    } else {
        Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $logonTrigger,$scheduleTrigger -Settings $settings -Principal $principal
        Write-Output "Created new scheduled task '$taskName'"
    }
    Write-Output "Task '$taskName' is configured to run at logon and every 5 minutes."
    Write-Output "Config directory: $ConfigDir"
} catch {
    Write-Error "Failed to register scheduled task: $_"
    exit 1
}
