$ErrorActionPreference = "Stop"
$Version = "0.46.1"
$Tag = "cua-driver-rs-v$Version"
$Name = "cua-driver-rs-$Version-windows-x86_64-binary.zip"
$ExpectedSha256 = "ec49cca509f25f65db2fa917718215f55f959d5ef650bf8ab2238a201d5666ac"
$Root = Split-Path -Parent $PSScriptRoot
$Destination = Join-Path $Root "resources\cua-driver"
$Archive = Join-Path $env:TEMP $Name
$Url = "https://github.com/trycua/cua/releases/download/$Tag/$Name"
Invoke-WebRequest -Uri $Url -OutFile $Archive
$ActualSha256 = (certutil -hashfile $Archive SHA256 | Select-Object -Skip 1 -First 1).Trim().ToLowerInvariant()
if ($ActualSha256 -ne $ExpectedSha256) { throw "Cua Driver archive checksum mismatch." }
New-Item -ItemType Directory -Force -Path $Destination | Out-Null
Expand-Archive -Path $Archive -DestinationPath $Destination -Force
if (-not (Test-Path (Join-Path $Destination "cua-driver.exe"))) { throw "cua-driver.exe is missing from the verified release archive." }
$env:CUA_DRIVER_RS_HOME = Join-Path $Root "data\cua-driver\runtime-home"
New-Item -ItemType Directory -Force -Path $env:CUA_DRIVER_RS_HOME | Out-Null
& (Join-Path $Destination "cua-driver.exe") telemetry disable
if ($LASTEXITCODE -ne 0) { throw "Could not disable Cua Driver telemetry." }
Write-Host "Installed verified Cua Driver $Version into $Destination"
