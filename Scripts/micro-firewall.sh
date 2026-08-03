
#!/bin/bash

# Ensure the script is run as root
if [ "$EUID" -ne 0 ]; then
  echo "Please run this script using sudo."
  exit 1
fi

# ==========================================
# 1. USER CONFIGURATION INPUTS
# ==========================================
echo "--- Micro Software Firewall Configuration ---"
read -p "Enter your local network interface (e.g., eth0, wlan0): " NIC
read -p "Enter the external port to open on the router via UPnP: " PORT_EXT
read -p "Enter the internal port for your software to listen on: " PORT_INT
read -p "Enter the trusted IPv4 address allowed to connect: " TRUSTED_IP

# Define the isolated target routing destination (Using 127.0.0.2 instead of invalid 0.0.0.0)
ISOLATED_IP="127.0.0.2"

# Get the actual current IP address of your local network card
LOCAL_IP=$(ip -4 addr show dev "$NIC" | grep -oP '(?<=inet \s)\d+(\.\d+){3}')

if [ -z "$LOCAL_IP" ]; then
    echo "Error: Could not automatically find an IP on interface $NIC."
    exit 1
fi

echo -e "\nConfiguring routing: $LOCAL_IP -> $ISOLATED_IP"
echo "Allowing trusted IPv4: $TRUSTED_IP"

# ==========================================
# 2. FIREWALL & ROUTING RULES (Using iptables)
# ==========================================
echo "Applying firewall rules..."

# Enable local routing to a loopback/local address structure
sysctl -w net.ipv4.conf.$NIC.route_localnet=1 > /dev/null

# Clear out any previous conflicting rules
iptables -t nat -F
iptables -F

# Block ALL incoming traffic to the internal isolated port by default
iptables -A INPUT -p tcp --dport "$PORT_INT" -j DROP

# ALLOW ONLY the trusted IP address to pass through the firewall to that port
iptables -I INPUT -p tcp -s "$TRUSTED_IP" --dport "$PORT_INT" -j ACCEPT

# Route incoming traffic aimed at your Network Card IP over to the isolated IP
iptables -t nat -A PREROUTING -i "$NIC" -p tcp --dport "$PORT_INT" -j DNAT --to-destination "$ISOLATED_IP":"$PORT_INT"

# ==========================================
# 3. AUTOMATED UPnP PORT FORWARDING
# ==========================================
echo "Contacting router via UPnP to map External Port $PORT_EXT to Local IP $LOCAL_IP..."

# upnpc syntax: -a [Internal_IP] [Internal_Port] [External_Port] [Protocol]
upnpc -a "$LOCAL_IP" "$PORT_INT" "$PORT_EXT" TCP

echo -e "\n[SUCCESS] Firewall active and router port mapping requested."
echo "Your app should now listen directly on $ISOLATED_IP:$PORT_INT"
