# SmokePing to Home Assistant Integration

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.1+-blue.svg)](https://www.home-assistant.io/)
[![SmokePing](https://img.shields.io/badge/SmokePing-2.8+-green.svg)](https://oss.oetiker.ch/smokeping/)

A lightweight integration that exposes SmokePing latency data to Home Assistant via REST sensors. Monitor your WAN health, compare ISP performance, and get alerts when network issues occur.

<!-- Add your own screenshot: ![Dashboard Preview](docs/images/dashboard-preview.png) -->

## Features

- **Real-time latency monitoring** - Poll SmokePing RRD data every 60 seconds
- **Multi-ISP support** - Compare latency across different WAN connections
- **Color-coded dashboard cards** - Green/yellow/red based on latency thresholds
- **Smart alerting** - Push notifications with cooldown to prevent spam
- **Zero dependencies** - Uses only Python standard library + rrdtool CLI
- **Lightweight** - Simple HTTP API, ~250 lines of Python

## How It Works

```
┌─────────────────┐     ┌─────────────────┐
│  SmokePing      │     │  SmokePing      │
│  Server 1       │     │  Server 2       │
│  (ISP A)        │     │  (ISP B)        │
│       ↓         │     │       ↓         │
│ smokeping-api   │     │ smokeping-api   │
│   :8080         │     │   :8080         │
└────────┬────────┘     └────────┬────────┘
         │                       │
         └───────────┬───────────┘
                     │ HTTP/JSON
              ┌──────▼──────┐
              │ Home        │
              │ Assistant   │
              │ REST Sensors│
              └──────┬──────┘
                     │
         ┌───────────┴───────────┐
         │                       │
    ┌────▼────┐           ┌──────▼──────┐
    │Dashboard│           │ Automations │
    │ Cards   │           │   Alerts    │
    └─────────┘           └─────────────┘
```

## Quick Start

### 1. Install the API on your SmokePing server(s)

```bash
# Install rrdtool
sudo apt update && sudo apt install -y rrdtool

# Download and install the API
sudo curl -o /usr/local/bin/smokeping-api.py \
  https://raw.githubusercontent.com/ryanplanchart/smokeping-ha/main/api/smokeping-api.py
sudo chmod +x /usr/local/bin/smokeping-api.py

# Install and start the service
sudo curl -o /etc/systemd/system/smokeping-api.service \
  https://raw.githubusercontent.com/ryanplanchart/smokeping-ha/main/api/smokeping-api.service
sudo systemctl daemon-reload
sudo systemctl enable --now smokeping-api

# Verify it's working
curl http://localhost:8080/
```

### 2. Configure Home Assistant

Add to your `configuration.yaml`:

```yaml
rest: !include smokeping_sensors.yaml
```

Copy `homeassistant/sensors/smokeping_sensors.yaml` to your HA config directory and update the server hostnames.

### 3. Restart Home Assistant

The sensors will appear as:
- `sensor.fios_cloudflare_latency`
- `sensor.comcast_cloudflare_latency`
- etc.

## Configuration

### API Configuration

Edit the `TARGETS` dictionary in `smokeping-api.py` to match your SmokePing targets:

```python
TARGETS = {
    "cloudflare": "external/cloudflare.rrd",
    "google": "external/google_dns.rrd",
    "aws": "external/aws_use1.rrd",
    "netflix": "netflix/nflx_was.rrd",
}
```

The ISP name is auto-detected from the hostname. Customize the detection logic in the script if needed.

### Home Assistant Sensors

The sensor configuration polls the API every 60 seconds. Each sensor includes:
- **State**: Latency in milliseconds
- **Attributes**: `loss_pct`, `timestamp`

### Dashboard Cards

See `examples/dashboard-cards.yaml` for Mushroom card examples with color-coded status.

### Automations

See `homeassistant/automations/` for alert templates:
- **WAN Degraded** - Alert when latency > 100ms for 10 minutes
- **WAN Recovered** - Notify when latency returns to normal
- **Both WANs Degraded** - Critical alert when all connections are affected
- **Packet Loss** - Alert when loss > 10%

Features:
- 10-minute sustained threshold before alerting
- 1-hour cooldown between alerts
- Recovery notifications only if an alert was sent

## API Reference

### Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /` | Returns all target latencies as JSON |
| `GET /health` | Health check endpoint |
| `GET /target/<name>` | Returns single target data |

### Response Format

```json
{
  "targets": {
    "cloudflare": {
      "latency_ms": 12.5,
      "loss_pct": 0.0,
      "timestamp": "2024-01-15T10:30:00+00:00"
    }
  },
  "isp": "fios",
  "hostname": "pi",
  "collected_at": "2024-01-15T10:30:05+00:00"
}
```

## Requirements

### SmokePing Server
- SmokePing 2.8+ with RRD data
- Python 3.9+
- `rrdtool` package (`apt install rrdtool`)

### Home Assistant
- Home Assistant 2024.1+
- REST integration (built-in)
- Optional: Mushroom Cards for dashboard

## Troubleshooting

### API returns "rrdtool not installed"
```bash
sudo apt install rrdtool
```

### Sensors show "unavailable"
1. Check API is running: `curl http://your-server:8080/`
2. Check HA can reach the server (firewall, DNS)
3. Check HA logs for REST sensor errors

### Service won't start
```bash
sudo journalctl -u smokeping-api -n 50
```

Common issues:
- Wrong user in service file (change `User=smokeping` to `User=pi`)
- RRD files not readable

## Contributing

Contributions are welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Submit a pull request

## License

MIT License - see [LICENSE](LICENSE) for details.

## Acknowledgments

- [SmokePing](https://oss.oetiker.ch/smokeping/) by Tobi Oetiker
- [Home Assistant](https://www.home-assistant.io/) community
- [Mushroom Cards](https://github.com/piitaya/lovelace-mushroom) for beautiful dashboard components
