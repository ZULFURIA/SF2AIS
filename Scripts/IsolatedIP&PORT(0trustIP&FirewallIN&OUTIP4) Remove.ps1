# Define the names used during setup

$RuleInName    = "MicroFW_Isolated_Inbound"
$RuleOutName   = "MicroFW_Isolated_Outbound"
$CustomRouteIP = "192.*.*.*" # <-- Change this to the custom IP you used

Write-Host "Cleaning up Micro Software Firewall environment..." -ForegroundColor Yellow

# 1. Remove the custom Firewall rules
Remove-NetFirewallRule -DisplayName $RuleInName -ErrorAction SilentlyContinue
Remove-NetFirewallRule -DisplayName $RuleOutName -ErrorAction SilentlyContinue

# 2. Remove the secondary /32 IP address from your network card
Remove-NetIPAddress -IPAddress $CustomRouteIP -Confirm:$false -ErrorAction SilentlyContinue

Write-Host "[SUCCESS] Network card and firewall returned to default settings." -ForegroundColor Green
