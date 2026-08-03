\# Run Scripts as Administrators. 

\# Powershell

&#x20;

\#Applies a Second IP to a Network Interface, Creates firewall rules for a specific Port

&#x20;

.\\IsolatedIP(0TrustMatrix4FrontendDebug)Win.ps1



\# Removes Ip and Firewall Rules



.\\IsolatedIP\&PORT(0trustIP\&FirewallIN\&OUTIP4) Remove.ps1



\# Powershell -  Ip Isolated IP Verification



Get-NetIPAddress -IPAddress 192.\*.\*.\*



&#x20;        # What to look for:

\# Look at the PrefixLength property in the output.

\# It should say 32, confirming that Windows has locked this address down # to a single-host mask,

\# separating it from the rest of your local network routing.



\-------------------------------------------------------------------------------------------------------

\# Powershell - Firewall rule Verification



Get-NetFirewallRule -DisplayName "MicroFW\_Isolated\_\*" | Get-NetFirewallPortFilter



&#x20;        # What to look for:

\# You should see two active rules—one Inbound and one Outbound.

\# They will explicitly lock your custom application port down so that it only listens

\# to your trusted external IP and your new 192.\*.\*.\*/32 address,

\# keeping the rest of your machine invisible to the internet.

