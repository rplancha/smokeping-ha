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
3. Install development dependencies:
   ```bash
   # Using uv (recommended)
   uv sync --dev

   # Or using pip
   pip install -e ".[dev]"
   ```
4. Create a feature branch:
   ```bash
   git checkout -b feature/your-feature-name
   ```

## Code Style

- Python: Follow PEP 8, enforced by ruff
- YAML: 2-space indentation
- Type hints: Required for all functions
- Keep it simple - this project intentionally has zero runtime dependencies

## Testing

Before submitting, run all quality checks:

```bash
# Run tests
uv run pytest

# Run linter
uv run ruff check .

# Run formatter check
uv run ruff format --check .

# Run type checker
uv run mypy api/ tests/
```

All checks must pass before merging.

### Manual Testing

Test the API script manually:
```bash
python3 api/smokeping_api.py &
curl http://localhost:8080/
curl http://localhost:8080/health
```

Validate YAML files:
```bash
python3 -c "import yaml; yaml.safe_load(open('homeassistant/sensors/smokeping_sensors.yaml'))"
```

Test in Home Assistant if possible.

## Pull Request Process

1. Write tests for new functionality
2. Ensure all quality checks pass
3. Update documentation if needed
4. Submit PR with clear description of changes
5. Respond to review feedback

## Questions?

Open an issue with the "question" label.
