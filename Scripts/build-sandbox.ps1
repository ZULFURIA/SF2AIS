$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Docker = (Get-Command docker -ErrorAction SilentlyContinue).Source
if (-not $Docker) {
    $Candidate = Join-Path $env:ProgramFiles "Docker\Docker\resources\bin\docker.exe"
    if (Test-Path $Candidate) { $Docker = $Candidate }
}
if (-not $Docker) { throw "Docker CLI was not found. Install Docker Desktop or set SF2AIS_DOCKER_BINARY." }
& $Docker info | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Docker Engine is not running." }
& $Docker build --pull -t sf2ais-workbench:latest -f (Join-Path $Root "sandbox\Dockerfile") $Root
if ($LASTEXITCODE -ne 0) { throw "Sf2AiS sandbox image build failed." }
Write-Host "Sf2AiS sandbox image is ready: sf2ais-workbench:latest"
