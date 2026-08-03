#!/usr/bin/env python3
# Sf2AiS IP Probe
# Checks your public IP periodically and reports changes back to your gateway
# so your shareable link keeps working even if your IP address changes.
#
# Cross-platform: works on Windows, macOS, and Linux with Python 3 installed.
#
# USAGE:
#   python3 probe.py
#
# Schedule it to run every 5 minutes:
#   Windows  -> Task Scheduler: create a Basic Task, trigger "Repeat every 5 minutes",
#               action: python.exe, argument: full path to this script
#   macOS    -> cron: */5 * * * * /usr/bin/python3 /path/to/probe.py
#   Linux    -> cron: */5 * * * * /usr/bin/python3 /path/to/probe.py

import json
import urllib.request

GATEWAY_URL = "http://192.168.1.5:8000"
PROBE_TOKEN = "c8H9Yd9qNv2WyDaDVy27sqh6421JQaRe"
CACHE_FILE = "sf2ais_probe_last_ip.txt"


def get_public_ip():
    with urllib.request.urlopen("https://api.ipify.org", timeout=10) as r:
        return r.read().decode().strip()


def read_cached_ip():
    try:
        with open(CACHE_FILE) as f:
            return f.read().strip()
    except FileNotFoundError:
        return None


def write_cached_ip(ip):
    with open(CACHE_FILE, "w") as f:
        f.write(ip)


def report_ip(ip):
    payload = json.dumps({"token": PROBE_TOKEN, "ip": ip}).encode()
    req = urllib.request.Request(
        GATEWAY_URL.rstrip("/") + "/api/ip-update",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status


def main():
    ip = get_public_ip()
    if ip != read_cached_ip():
        report_ip(ip)
        write_cached_ip(ip)
        print("IP changed -> " + ip + " (reported to gateway)")
    else:
        print("IP unchanged (" + ip + ") - nothing to do.")


if __name__ == "__main__":
    main()
