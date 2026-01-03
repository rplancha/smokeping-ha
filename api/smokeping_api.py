#!/usr/bin/env python3
"""
SmokePing RRD to JSON API

A lightweight HTTP server that reads SmokePing RRD files and exposes
latency/loss data as JSON for Home Assistant REST sensors.

Project: https://github.com/ryanplanchart/smokeping-ha
License: MIT

Deploy to: /usr/local/bin/smokeping_api.py
Run as: systemd service (see smokeping-api.service)

Usage:
    curl http://localhost:8080/
    curl http://localhost:8080/health
    curl http://localhost:8080/target/cloudflare

Configuration via environment variables:
    SMOKEPING_API_BIND_ADDRESS - Address to bind to (default: 127.0.0.1)
    SMOKEPING_API_PORT         - Port to listen on (default: 8080)
    SMOKEPING_API_DATA_DIR     - Path to SmokePing RRD data (default: /var/lib/smokeping)
    SMOKEPING_API_TOTAL_PINGS  - Number of pings per probe cycle (default: 20)
    SMOKEPING_API_ISP          - ISP identifier (default: auto-detected from hostname)

Security notes:
    - By default, binds to 127.0.0.1 (localhost only) for security
    - Set SMOKEPING_API_BIND_ADDRESS=0.0.0.0 to allow network access
    - No authentication - rely on network-level security (firewall, VPN)
    - CORS is set to allow all origins (*) for local network use
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from statistics import median
from typing import Any

# Type alias for RRD data response
RRDData = dict[str, Any]


# =============================================================================
# CONFIGURATION HELPERS
# =============================================================================


def _parse_int_env(name: str, default: int, min_val: int = 1) -> int:
    """
    Parse integer from environment variable with validation.

    Args:
        name: Environment variable name
        default: Default value if not set or invalid
        min_val: Minimum allowed value

    Returns:
        Parsed integer value, or default if invalid
    """
    value = os.environ.get(name)
    if value is None:
        return default

    try:
        result = int(value)
        if result < min_val:
            print(
                f"Warning: {name}={result} is below minimum {min_val}, using {default}",
                file=sys.stderr,
            )
            return default
        return result
    except ValueError:
        print(
            f"Warning: {name}='{value}' is not a valid integer, using {default}",
            file=sys.stderr,
        )
        return default


# =============================================================================
# CONFIGURATION - Override via environment variables or edit defaults below
# =============================================================================

# Network binding configuration
# SECURITY: Default to localhost only. Set SMOKEPING_API_BIND_ADDRESS=0.0.0.0
# to allow connections from other machines (required for Home Assistant on
# a different host). Ensure proper firewall rules are in place.
BIND_ADDRESS: str = os.environ.get("SMOKEPING_API_BIND_ADDRESS", "127.0.0.1")
PORT: int = _parse_int_env("SMOKEPING_API_PORT", 8080, min_val=1)

# Path to SmokePing RRD data directory
SMOKEPING_DATA_DIR: str = os.environ.get("SMOKEPING_API_DATA_DIR", "/var/lib/smokeping")

# Number of pings per SmokePing probe cycle (check your SmokePing config)
# Used to calculate packet loss percentage
TOTAL_PINGS: int = _parse_int_env("SMOKEPING_API_TOTAL_PINGS", 20, min_val=1)

# Targets to expose (relative to SMOKEPING_DATA_DIR)
# Format: "friendly_name": "path/to/file.rrd"
# Find your RRD files with: find /var/lib/smokeping -name "*.rrd"
TARGETS: dict[str, str] = {
    "cloudflare": "external/cloudflare.rrd",
    "google": "external/google_dns.rrd",
    "aws_use1": "external/aws_use1.rrd",
    "netflix": "netflix/nflx_was.rrd",
}

# ISP/connection identifier
# Customize this for your setup - used to label data in Home Assistant
HOSTNAME: str = socket.gethostname().lower()


def detect_isp(hostname: str) -> str:
    """
    Detect ISP based on hostname. Customize for your setup.

    This function is used as a fallback when SMOKEPING_API_ISP is not set.

    Examples:
        - hostname starts with "pi" -> "fios"
        - "cake" in hostname -> "comcast"
        - "primary" in hostname -> "primary"
        - "backup" in hostname -> "backup"

    Args:
        hostname: The hostname to check (lowercase)

    Returns:
        ISP identifier string
    """
    # Use startswith for "pi" to avoid matching "smokeping" etc.
    if hostname.startswith("pi"):
        return "fios"
    elif "cake" in hostname:
        return "comcast"
    else:
        return "unknown"


# ISP can be set explicitly via environment variable, or auto-detected from hostname
ISP: str = os.environ.get("SMOKEPING_API_ISP", detect_isp(HOSTNAME))

# =============================================================================
# API IMPLEMENTATION - No need to edit below this line
# =============================================================================


def parse_rrd_lastupdate(output: str) -> RRDData:
    """
    Parse rrdtool lastupdate output.

    Example output:
        uptime ping1 ping2 ... ping20 loss

        1735840200: 123456 1.23e-02 1.45e-02 ... 0

    Args:
        output: Raw output from rrdtool lastupdate command

    Returns:
        Dict with latency_ms (median), loss_pct, timestamp, and optionally error
    """
    lines = output.strip().split("\n")

    if len(lines) < 2:
        return {"latency_ms": None, "loss_pct": None, "error": "Invalid RRD output"}

    # Get the data line (last non-empty line with a colon)
    data_line: str | None = None
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

    # Parse timestamp with error handling
    try:
        timestamp = int(parts[0].strip())
    except ValueError:
        return {"latency_ms": None, "loss_pct": None, "error": "Invalid timestamp"}

    values_str = parts[1].strip()

    # Split values (space-separated)
    values = values_str.split()

    if len(values) < 2:
        return {"latency_ms": None, "loss_pct": None, "error": "Not enough values"}

    # First value is uptime (ignore), last value is loss count
    # Middle values are ping times in seconds (scientific notation)
    # We want the median of the ping values

    ping_values: list[float] = []
    for v in values[1:-1]:  # Skip uptime (first) and loss (last)
        try:
            if v.lower() in ("u", "nan", "-nan"):
                continue
            val = float(v)
            if val > 0:  # Valid ping time (positive only)
                ping_values.append(val)
        except (ValueError, TypeError):
            continue

    # Calculate median latency in milliseconds using statistics.median
    latency_ms: float | None = None
    if ping_values:
        latency_ms = round(median(ping_values) * 1000, 2)

    # Parse loss count (last value) and calculate percentage
    # Guard against TOTAL_PINGS=0 (should not happen due to validation, but be safe)
    loss_pct: float | None = None
    if TOTAL_PINGS > 0:
        try:
            loss_count = int(float(values[-1]))
            loss_pct = round((loss_count / TOTAL_PINGS) * 100, 1)
            # Cap at 100% in case loss_count exceeds TOTAL_PINGS
            if loss_pct > 100.0:
                loss_pct = 100.0
        except (ValueError, TypeError, IndexError):
            pass

    return {
        "latency_ms": latency_ms,
        "loss_pct": loss_pct,
        "timestamp": datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat(),
    }


def get_target_data(target_name: str, rrd_path: str) -> RRDData:
    """
    Read RRD file and return parsed data.

    Args:
        target_name: Friendly name of the target (for logging)
        rrd_path: Relative path to RRD file within SMOKEPING_DATA_DIR

    Returns:
        Dict with latency_ms, loss_pct, timestamp, and optionally error
    """
    full_path = os.path.join(SMOKEPING_DATA_DIR, rrd_path)

    # SECURITY: Prevent path traversal attacks
    # Resolve to absolute path and verify it's within the data directory
    real_path = os.path.realpath(full_path)
    base_path = os.path.realpath(SMOKEPING_DATA_DIR)
    if not real_path.startswith(base_path + os.sep) and real_path != base_path:
        return {
            "latency_ms": None,
            "loss_pct": None,
            "error": "Invalid path",
        }

    if not os.path.exists(real_path):
        return {
            "latency_ms": None,
            "loss_pct": None,
            "error": f"RRD file not found: {rrd_path}",
        }

    try:
        result = subprocess.run(
            ["rrdtool", "lastupdate", real_path],
            capture_output=True,
            text=True,
            timeout=5,
        )

        if result.returncode != 0:
            # SECURITY: Don't leak full stderr, just indicate an error occurred
            return {
                "latency_ms": None,
                "loss_pct": None,
                "error": "rrdtool error reading file",
            }

        return parse_rrd_lastupdate(result.stdout)

    except subprocess.TimeoutExpired:
        return {"latency_ms": None, "loss_pct": None, "error": "rrdtool timeout"}
    except FileNotFoundError:
        return {"latency_ms": None, "loss_pct": None, "error": "rrdtool not installed"}
    except Exception:
        # SECURITY: Don't leak exception details in error messages
        return {"latency_ms": None, "loss_pct": None, "error": "Unexpected error reading RRD file"}


class SmokePingAPIHandler(BaseHTTPRequestHandler):
    """HTTP request handler for SmokePing API."""

    def log_message(self, fmt: str, *args: Any) -> None:
        """Suppress default logging (too noisy for systemd)."""
        pass

    def _send_cors_headers(self) -> None:
        """Send CORS headers for cross-origin requests."""
        # SECURITY: Allow cross-origin requests for local network API usage.
        # This is safe for local network services. If exposing to the internet,
        # consider restricting to specific origins or adding authentication.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def send_json(self, data: dict[str, Any], status: int = 200) -> None:
        """Send JSON response with CORS headers."""
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode())

    def do_OPTIONS(self) -> None:
        """Handle CORS preflight requests."""
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self) -> None:
        """Handle GET requests."""
        if self.path == "/health":
            self.send_json({"status": "ok", "hostname": HOSTNAME, "isp": ISP})
            return

        if self.path in ("/", "/metrics"):
            # Collect all target data
            results: dict[str, RRDData] = {}
            for target_name, rrd_path in TARGETS.items():
                results[target_name] = get_target_data(target_name, rrd_path)

            response: dict[str, Any] = {
                "targets": results,
                "isp": ISP,
                "hostname": HOSTNAME,
                "collected_at": datetime.now(timezone.utc).isoformat(),
            }
            self.send_json(response)
            return

        # Single target endpoint: /target/<name>
        match = re.match(r"^/target/([\w-]+)$", self.path)
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


def main() -> None:
    """Start the HTTP server."""
    server = HTTPServer((BIND_ADDRESS, PORT), SmokePingAPIHandler)
    print(f"SmokePing API starting on {BIND_ADDRESS}:{PORT}")
    print(f"Hostname: {HOSTNAME}, ISP: {ISP}")
    print(f"Data directory: {SMOKEPING_DATA_DIR}")
    print(f"Targets: {list(TARGETS.keys())}")

    if BIND_ADDRESS == "127.0.0.1":
        print(
            "Note: Bound to localhost only. "
            "Set SMOKEPING_API_BIND_ADDRESS=0.0.0.0 for network access."
        )

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
