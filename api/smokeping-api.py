#!/usr/bin/env python3
"""
SmokePing RRD to JSON API

A lightweight HTTP server that reads SmokePing RRD files and exposes
latency/loss data as JSON for Home Assistant REST sensors.

Project: https://github.com/ryanplanchart/smokeping-ha
License: MIT

Deploy to: /usr/local/bin/smokeping-api.py
Run as: systemd service (see smokeping-api.service)

Usage:
    curl http://localhost:8080/
    curl http://localhost:8080/health
    curl http://localhost:8080/target/cloudflare
"""

import json
import os
import re
import socket
import subprocess
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any

# =============================================================================
# CONFIGURATION - Edit these values to match your setup
# =============================================================================

# Port to listen on
PORT = 8080

# Path to SmokePing RRD data directory
SMOKEPING_DATA_DIR = "/var/lib/smokeping"

# Targets to expose (relative to SMOKEPING_DATA_DIR)
# Format: "friendly_name": "path/to/file.rrd"
# Find your RRD files with: find /var/lib/smokeping -name "*.rrd"
TARGETS = {
    "cloudflare": "external/cloudflare.rrd",
    "google": "external/google_dns.rrd",
    "aws_use1": "external/aws_use1.rrd",
    "netflix": "netflix/nflx_was.rrd",
}

# ISP detection based on hostname
# Customize this for your setup - used to label data in Home Assistant
HOSTNAME = socket.gethostname().lower()


def detect_isp(hostname: str) -> str:
    """
    Detect ISP based on hostname. Customize for your setup.

    Examples:
        - "pi" in hostname -> "fios"
        - "cake" in hostname -> "comcast"
        - "primary" in hostname -> "primary"
        - "backup" in hostname -> "backup"
    """
    if "pi" in hostname:
        return "fios"
    elif "cake" in hostname:
        return "comcast"
    else:
        return "unknown"


ISP = detect_isp(HOSTNAME)

# =============================================================================
# API IMPLEMENTATION - No need to edit below this line
# =============================================================================


def parse_rrd_lastupdate(output: str) -> dict[str, Any]:
    """
    Parse rrdtool lastupdate output.

    Example output:
        uptime ping1 ping2 ... ping20 loss

        1735840200: 123456 1.23e-02 1.45e-02 ... 0

    Returns dict with latency_ms (median) and loss_pct.
    """
    lines = output.strip().split("\n")

    if len(lines) < 2:
        return {"latency_ms": None, "loss_pct": None, "error": "Invalid RRD output"}

    # Get the data line (last non-empty line)
    data_line = None
    for line in reversed(lines):
        line = line.strip()
        if line and ":" in line:
            data_line = line
            break

    if not data_line:
        return {"latency_ms": None, "loss_pct": None, "error": "No data line found"}

    # Parse timestamp and values
    # Format: "timestamp: val1 val2 val3 ..."
    parts = data_line.split(":")
    if len(parts) != 2:
        return {"latency_ms": None, "loss_pct": None, "error": "Malformed data line"}

    timestamp = int(parts[0].strip())
    values_str = parts[1].strip()

    # Split values (space-separated)
    values = values_str.split()

    if len(values) < 2:
        return {"latency_ms": None, "loss_pct": None, "error": "Not enough values"}

    # First value is uptime (ignore), last value is loss count
    # Middle values are ping times in seconds (scientific notation)
    # We want the median of the ping values

    ping_values = []
    for v in values[1:-1]:  # Skip uptime (first) and loss (last)
        try:
            if v.lower() in ("u", "nan", "-nan"):
                continue
            val = float(v)
            if val > 0:  # Valid ping time
                ping_values.append(val)
        except (ValueError, TypeError):
            continue

    # Calculate median latency in milliseconds
    latency_ms = None
    if ping_values:
        ping_values.sort()
        mid = len(ping_values) // 2
        if len(ping_values) % 2 == 0:
            latency_ms = (ping_values[mid - 1] + ping_values[mid]) / 2 * 1000
        else:
            latency_ms = ping_values[mid] * 1000
        latency_ms = round(latency_ms, 2)

    # Parse loss count (last value)
    loss_pct = None
    try:
        loss_count = int(float(values[-1]))
        total_pings = 20  # SmokePing default
        loss_pct = round((loss_count / total_pings) * 100, 1)
    except (ValueError, TypeError, IndexError):
        pass

    return {
        "latency_ms": latency_ms,
        "loss_pct": loss_pct,
        "timestamp": datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat(),
    }


def get_target_data(target_name: str, rrd_path: str) -> dict[str, Any]:
    """Read RRD file and return parsed data."""
    full_path = os.path.join(SMOKEPING_DATA_DIR, rrd_path)

    if not os.path.exists(full_path):
        return {
            "latency_ms": None,
            "loss_pct": None,
            "error": f"RRD file not found: {full_path}",
        }

    try:
        result = subprocess.run(
            ["rrdtool", "lastupdate", full_path],
            capture_output=True,
            text=True,
            timeout=5,
        )

        if result.returncode != 0:
            return {
                "latency_ms": None,
                "loss_pct": None,
                "error": f"rrdtool error: {result.stderr}",
            }

        return parse_rrd_lastupdate(result.stdout)

    except subprocess.TimeoutExpired:
        return {"latency_ms": None, "loss_pct": None, "error": "rrdtool timeout"}
    except FileNotFoundError:
        return {"latency_ms": None, "loss_pct": None, "error": "rrdtool not installed"}
    except Exception as e:
        return {"latency_ms": None, "loss_pct": None, "error": str(e)}


class SmokePingAPIHandler(BaseHTTPRequestHandler):
    """HTTP request handler for SmokePing API."""

    def log_message(self, format, *args):
        """Suppress default logging (too noisy for systemd)."""
        pass

    def send_json(self, data: dict, status: int = 200):
        """Send JSON response."""
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode())

    def do_GET(self):
        """Handle GET requests."""
        if self.path == "/health":
            self.send_json({"status": "ok", "hostname": HOSTNAME, "isp": ISP})
            return

        if self.path == "/" or self.path == "/metrics":
            # Collect all target data
            results = {}
            for target_name, rrd_path in TARGETS.items():
                results[target_name] = get_target_data(target_name, rrd_path)

            response = {
                "targets": results,
                "isp": ISP,
                "hostname": HOSTNAME,
                "collected_at": datetime.now(timezone.utc).isoformat(),
            }
            self.send_json(response)
            return

        # Single target endpoint: /target/<name>
        match = re.match(r"^/target/(\w+)$", self.path)
        if match:
            target_name = match.group(1)
            if target_name in TARGETS:
                data = get_target_data(target_name, TARGETS[target_name])
                data["target"] = target_name
                data["isp"] = ISP
                self.send_json(data)
            else:
                self.send_json(
                    {
                        "error": f"Unknown target: {target_name}",
                        "available": list(TARGETS.keys()),
                    },
                    status=404,
                )
            return

        # 404 for unknown paths
        self.send_json(
            {"error": "Not found", "endpoints": ["/", "/health", "/target/<name>"]},
            status=404,
        )


def main():
    """Start the HTTP server."""
    server = HTTPServer(("0.0.0.0", PORT), SmokePingAPIHandler)
    print(f"SmokePing API starting on port {PORT}")
    print(f"Hostname: {HOSTNAME}, ISP: {ISP}")
    print(f"Targets: {list(TARGETS.keys())}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
