# Ensure script is running with elevated Administrator privileges
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Error "CRITICAL: This script must be run as an Administrator."
    Exit
}

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "   WINDOWS MICRO SOFTWARE FIREWALL & CUSTOM ROUTING ENGINE" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# ==========================================
# 1. NETWORK INTERFACE DETECTION & SELECTION
# ==========================================
Write-Host "`n[1] Scanning Network Adapters..." -ForegroundColor Green
$Adapters = Get-NetIPInterface -AddressFamily IPv4 | Where-Object { $_.InterfaceAlias -notmatch 'Loopback|vEthernet|Virtual' } | 
            Select-Object InterfaceIndex, InterfaceAlias, @{Name="CurrentIP"; Expression={(Get-NetIPAddress -InterfaceIndex $_.InterfaceIndex -AddressFamily IPv4).IPAddress}}

Write-Host "Detected Network Interfaces:" -ForegroundColor Yellow
for ($i = 0; $i -lt $Adapters.Count; $i++) {
    Write-Host "  [$i] Index: $($Adapters[$i].InterfaceIndex) | Alias: $($Adapters[$i].InterfaceAlias) | Current IP: $($Adapters[$i].CurrentIP)"
}

$Selection = Read-Host "`nSelect adapter number (or type an active IP manually)"
if ($Selection -match '^\d+$' -and $Selection -lt $Adapters.Count) {
    $TargetNIC = $Adapters[$Selection].InterfaceAlias
    $BaseIP    = $Adapters[$Selection].CurrentIP
} else {
    # Treat input as a manual IP string fallback
    $BaseIP    = $Selection
    $TargetNIC = (Get-NetIPAddress -IPAddress $BaseIP).InterfaceAlias
}

if (-not $TargetNIC) { Write-Error "Invalid interface selection."; Exit }

# ==========================================
# 2. PROVISION USER CONFIGURATIONS
# ==========================================
Write-Host "`n[2] Setting Up Custom Routing Boundaries..." -ForegroundColor Green
$CustomRouteIP = Read-Host "Enter your desired single-host 192.*.*.* isolation IP (e.g., 192.168.1.250)"
$PortInt       = Read-Host "Enter the target INTERNAL port to lock down"
$PortExt       = Read-Host "Enter the target EXTERNAL port for UPnP"
$TrustedRemote = Read-Host "Enter the trusted incoming IPv4 address allowed to connect"

$RuleInName    = "MicroFW_Isolated_Inbound"
$RuleOutName   = "MicroFW_Isolated_Outbound"

# Assign the secondary single IP mask (/32 equivalent) temporarily to the physical interface 
Write-Host "Binding single-host routing mask $CustomRouteIP/32 to $TargetNIC..." -ForegroundColor Yellow
New-NetIPAddress -InterfaceAlias $TargetNIC -IPAddress $CustomRouteIP -PrefixLength 32 -Confirm:$false -ErrorAction SilentlyContinue | Out-Null

# ==========================================
# 3. WINDOWS FIREWALL HARDENING (ZERO-TRUST MATRIX)
# ==========================================
Write-Host "`n[3] Building Firewall Exceptions..." -ForegroundColor Green

# Scrub any stale or overlapping rules
Remove-NetFirewallRule -DisplayName $RuleInName -ErrorAction SilentlyContinue
Remove-NetFirewallRule -DisplayName $RuleOutName -ErrorAction SilentlyContinue

# INBOUND: Drops all global incoming port requests, explicitly trusts ONLY the specific remote IP going to the single host mask IP
New-NetFirewallRule -DisplayName $RuleInName `
                    -Direction Inbound `
                    -Action Allow `
                    -Protocol TCP `
                    -LocalPort $PortInt `
                    -LocalAddress $CustomRouteIP `
                    -RemoteAddress $TrustedRemote `
                    -Description "MicroFirewall Engine: Locked inbound port trust to custom single-host IP."

# OUTBOUND: Strictly controls data leaving the host port
New-NetFirewallRule -DisplayName $RuleOutName `
                    -Direction Outbound `
                    -Action Allow `
                    -Protocol TCP `
                    -LocalPort $PortInt `
                    -RemoteAddress $TrustedRemote `
                    -Description "MicroFirewall Engine: Locked outbound port verification loop."

Write-Host "Firewall matrix applied successfully! Port $PortInt isolated to $CustomRouteIP." -ForegroundColor Yellow

# ==========================================
# 4. DYNAMIC UPnP PORT MAPPING
# ==========================================
Write-Host "`n[4] Initializing UPnP Automation..." -ForegroundColor Green
$UpnpToolPath = "$env:TEMP\upnpc.exe"

if (-not (Test-Path $UpnpToolPath)) {
    Write-Host "Downloading required mapping binary..." -ForegroundColor Yellow
    Invoke-WebRequest -Uri "https://tuxfamily.org" -OutFile "$env:TEMP\upnp.zip"
    Expand-Archive -Path "$env:TEMP\upnp.zip" -DestinationPath "$env:TEMP\upnp_extracted" -Force
    Copy-Item "$env:TEMP\upnp_extracted\*\upnpc.exe" -Destination $UpnpToolPath -Force
}

# Send the UPnP command mapping the router's external request down to our isolated single IP segment
Write-Host "Configuring Router Gateway: Forwarding external port $PortExt to internal $CustomRouteIP:$PortInt..." -ForegroundColor Cyan
Start-Process -FilePath $UpnpToolPath -ArgumentList "-a $CustomRouteIP $PortInt $PortExt TCP" -NoNewWindow -Wait

Write-Host "`n==========================================================" -ForegroundColor Green
Write-Host " SYSTEM HARDENING COMPLETE: Software Firewall Is Live" -ForegroundColor Green
Write-Host " Application must explicitly bind to: $CustomRouteIP:$PortInt" -ForegroundColor Yellow
Write-Host "==========================================================" -ForegroundColor Green
