<#
.SYNOPSIS
  Registers Sf2AiS Probe to start at the current user's Windows logon.
.DESCRIPTION
  Per-user scheduled task; no administrator rights required. The probe owns its
  interval timer, so the task launches it once at logon.
#>
param(
  [Parameter(Mandatory=$true)][string]$AppPath,
  [string]$AppDir = "",
  [string]$ConfigDir = "$env:USERPROFILE\.sf2ais-probe"
)
$ErrorActionPreference = "Stop"
if (-not (Test-Path -LiteralPath $AppPath -PathType Leaf)) {
  throw "Sf2AiS Probe executable not found: $AppPath"
}
$taskName = "Sf2AiS Probe"
$workingDirectory = Split-Path -Parent $AppPath
$action = New-ScheduledTaskAction -Execute $AppPath -WorkingDirectory $workingDirectory
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Limited
try {
  Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
  Write-Output "Scheduled task '$taskName' registered for $currentUser at logon."
  Write-Output "Executable: $AppPath"
  Write-Output "Working directory: $workingDirectory"
  Write-Output "Config directory: $ConfigDir"
} catch {
  throw "Failed to register scheduled task '$taskName': $($_.Exception.Message)"
}
