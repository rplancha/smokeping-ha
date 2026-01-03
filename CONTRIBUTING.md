# Contributing to SmokePing-HA

Thank you for your interest in contributing! This project welcomes contributions of all kinds.

## Ways to Contribute

- **Bug Reports**: Open an issue describing the bug, steps to reproduce, and your environment
- **Feature Requests**: Open an issue describing the feature and use case
- **Documentation**: Improve README, add examples, fix typos
- **Code**: Bug fixes, new features, refactoring

## Development Setup

1. Fork the repository
2. Clone your fork:
   ```bash
   git clone https://github.com/YOUR_USERNAME/smokeping-ha.git
   cd smokeping-ha
   ```
3. Create a feature branch:
   ```bash
   git checkout -b feature/your-feature-name
   ```

## Code Style

- Python: Follow PEP 8
- YAML: 2-space indentation
- Keep it simple - this project intentionally has zero dependencies

## Testing

Before submitting:

1. Test the API script manually:
   ```bash
   python3 api/smokeping-api.py &
   curl http://localhost:8080/
   curl http://localhost:8080/health
   ```

2. Validate YAML files:
   ```bash
   python3 -c "import yaml; yaml.safe_load(open('homeassistant/sensors/smokeping_sensors.yaml'))"
   ```

3. Test in Home Assistant if possible

## Pull Request Process

1. Update documentation if needed
2. Add yourself to CONTRIBUTORS.md (optional)
3. Submit PR with clear description of changes
4. Respond to review feedback

## Questions?

Open an issue with the "question" label.
