"""
Tests for SmokePing API.

These tests cover:
- RRD output parsing (parse_rrd_lastupdate)
- ISP detection (detect_isp)
- Target data retrieval with path validation (get_target_data)
- HTTP handler endpoints
"""

import json
import os
import sys
from io import BytesIO
from typing import Any, Optional
from unittest.mock import MagicMock, patch

import pytest

# Add the api directory to the path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))


class TestParseRrdLastupdate:
    """Tests for parse_rrd_lastupdate function."""

    def test_valid_output_with_good_pings(self) -> None:
        """Test parsing valid RRD output with successful pings."""
        # Import here to allow module-level patches in other tests
        from smokeping_api import parse_rrd_lastupdate

        output = """uptime ping1 ping2 ping3 ping4 ping5 loss

1735840200: 123456 1.23e-02 1.45e-02 1.50e-02 1.35e-02 1.40e-02 0"""

        result = parse_rrd_lastupdate(output)

        assert result["latency_ms"] is not None
        assert isinstance(result["latency_ms"], float)
        # Median of [12.3, 14.5, 15.0, 13.5, 14.0] = 14.0ms
        assert result["latency_ms"] == 14.0
        assert result["loss_pct"] == 0.0
        assert "error" not in result
        assert "timestamp" in result

    def test_empty_output(self) -> None:
        """Test parsing empty output returns error."""
        from smokeping_api import parse_rrd_lastupdate

        result = parse_rrd_lastupdate("")

        assert result["latency_ms"] is None
        assert "error" in result

    def test_nan_values_all_pings_failed(self) -> None:
        """Test parsing when all pings failed (U values)."""
        from smokeping_api import parse_rrd_lastupdate

        output = """uptime ping1 ping2 ping3 loss

1735840200: 123456 U U U 20"""

        result = parse_rrd_lastupdate(output)

        assert result["latency_ms"] is None
        assert result["loss_pct"] == 100.0

    def test_partial_nan_values(self) -> None:
        """Test parsing with mix of valid and NaN values."""
        from smokeping_api import parse_rrd_lastupdate

        output = """uptime ping1 ping2 ping3 ping4 ping5 loss

1735840200: 123456 1.00e-02 U 2.00e-02 U 1.50e-02 10"""

        result = parse_rrd_lastupdate(output)

        # Should only use valid pings: [10, 20, 15] -> median = 15ms
        assert result["latency_ms"] == 15.0
        assert result["loss_pct"] == 50.0  # 10/20 = 50%

    def test_malformed_data_line(self) -> None:
        """Test parsing malformed data returns error."""
        from smokeping_api import parse_rrd_lastupdate

        result = parse_rrd_lastupdate("garbage data without colon")

        assert result["latency_ms"] is None
        assert "error" in result

    def test_single_ping_value(self) -> None:
        """Test parsing with only one valid ping."""
        from smokeping_api import parse_rrd_lastupdate

        output = """uptime ping1 loss

1735840200: 123456 2.50e-02 0"""

        result = parse_rrd_lastupdate(output)

        assert result["latency_ms"] == 25.0
        assert result["loss_pct"] == 0.0

    def test_even_number_of_pings(self) -> None:
        """Test median calculation with even number of pings."""
        from smokeping_api import parse_rrd_lastupdate

        output = """uptime ping1 ping2 ping3 ping4 loss

1735840200: 123456 1.00e-02 2.00e-02 3.00e-02 4.00e-02 0"""

        result = parse_rrd_lastupdate(output)

        # Median of [10, 20, 30, 40] = (20 + 30) / 2 = 25ms
        assert result["latency_ms"] == 25.0

    def test_scientific_notation_parsing(self) -> None:
        """Test that scientific notation is correctly parsed."""
        from smokeping_api import parse_rrd_lastupdate

        output = """uptime ping1 loss

1735840200: 123456 1.234e-02 0"""

        result = parse_rrd_lastupdate(output)

        assert result["latency_ms"] == 12.34

    def test_negative_ping_values_ignored(self) -> None:
        """Test that negative or zero ping values are ignored."""
        from smokeping_api import parse_rrd_lastupdate

        output = """uptime ping1 ping2 ping3 loss

1735840200: 123456 -1.00e-02 0 2.00e-02 0"""

        result = parse_rrd_lastupdate(output)

        # Only 20ms is valid
        assert result["latency_ms"] == 20.0

    def test_not_enough_values(self) -> None:
        """Test parsing with insufficient values."""
        from smokeping_api import parse_rrd_lastupdate

        output = """header

1735840200: 123456"""

        result = parse_rrd_lastupdate(output)

        assert result["latency_ms"] is None
        assert "error" in result

    def test_lowercase_nan_variants(self) -> None:
        """Test that various NaN representations are handled."""
        from smokeping_api import parse_rrd_lastupdate

        output = """uptime ping1 ping2 ping3 loss

1735840200: 123456 nan -nan NaN 20"""

        result = parse_rrd_lastupdate(output)

        assert result["latency_ms"] is None
        assert result["loss_pct"] == 100.0

    def test_invalid_timestamp(self) -> None:
        """Test that invalid timestamp returns error."""
        from smokeping_api import parse_rrd_lastupdate

        output = """uptime ping1 loss

not_a_number: 123456 1.50e-02 0"""

        result = parse_rrd_lastupdate(output)

        assert result["latency_ms"] is None
        assert "error" in result
        assert "timestamp" in result["error"].lower()

    def test_loss_exceeds_total_pings_capped(self) -> None:
        """Test that loss percentage is capped at 100%."""
        from smokeping_api import parse_rrd_lastupdate

        # Loss count of 25 with TOTAL_PINGS=20 should cap at 100%
        output = """uptime ping1 loss

1735840200: 123456 1.50e-02 25"""

        result = parse_rrd_lastupdate(output)

        assert result["loss_pct"] == 100.0


class TestDetectIsp:
    """Tests for detect_isp function."""

    def test_pi_hostname(self) -> None:
        """Test that hostname starting with 'pi' returns 'fios'."""
        from smokeping_api import detect_isp

        assert detect_isp("pi4") == "fios"
        assert detect_isp("pi-smokeping") == "fios"
        assert detect_isp("pi") == "fios"
        # Note: "raspberry-pi" doesn't start with "pi", so it's unknown
        assert detect_isp("raspberry-pi") == "unknown"

    def test_cake_hostname(self) -> None:
        """Test that 'cake' in hostname returns 'comcast'."""
        from smokeping_api import detect_isp

        assert detect_isp("cake-router") == "comcast"
        assert detect_isp("openwrt-cake") == "comcast"

    def test_unknown_hostname(self) -> None:
        """Test that unknown hostname returns 'unknown'."""
        from smokeping_api import detect_isp

        assert detect_isp("server1") == "unknown"
        assert detect_isp("smokeping-host") == "unknown"  # "pi" must be at start
        assert detect_isp("") == "unknown"
        assert detect_isp("myserver") == "unknown"


class TestGetTargetData:
    """Tests for get_target_data function."""

    def test_valid_path_returns_parsed_data(self) -> None:
        """Test that valid path returns parsed RRD data."""
        from smokeping_api import get_target_data

        mock_output = """uptime ping1 loss

1735840200: 123456 1.50e-02 0"""

        with (
            patch("smokeping_api.os.path.exists", return_value=True),
            patch("smokeping_api.os.path.realpath", side_effect=lambda p: p),
            patch("smokeping_api.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout=mock_output, stderr="")

            result = get_target_data("test", "valid/path.rrd")

            assert result["latency_ms"] == 15.0
            assert result["loss_pct"] == 0.0

    def test_path_traversal_attempt_rejected(self) -> None:
        """Test that path traversal attempts are rejected."""
        from smokeping_api import SMOKEPING_DATA_DIR, get_target_data

        # Mock realpath to simulate path traversal resolution
        def mock_realpath(path: str) -> str:
            if ".." in path:
                return "/etc/passwd"
            return os.path.join(SMOKEPING_DATA_DIR, path)

        with patch("smokeping_api.os.path.realpath", side_effect=mock_realpath):
            result = get_target_data("evil", "../../../etc/passwd")

            assert result["latency_ms"] is None
            assert "error" in result
            assert "Invalid path" in result["error"]

    def test_nonexistent_file_returns_error(self) -> None:
        """Test that non-existent file returns appropriate error."""
        from smokeping_api import get_target_data

        with (
            patch("smokeping_api.os.path.realpath", side_effect=lambda p: p),
            patch("smokeping_api.os.path.exists", return_value=False),
        ):
            result = get_target_data("missing", "nonexistent.rrd")

            assert result["latency_ms"] is None
            assert "error" in result
            assert "not found" in result["error"]

    def test_rrdtool_not_installed(self) -> None:
        """Test handling when rrdtool is not installed."""
        from smokeping_api import get_target_data

        with (
            patch("smokeping_api.os.path.exists", return_value=True),
            patch("smokeping_api.os.path.realpath", side_effect=lambda p: p),
            patch("smokeping_api.subprocess.run", side_effect=FileNotFoundError),
        ):
            result = get_target_data("test", "valid.rrd")

            assert result["latency_ms"] is None
            assert "error" in result
            assert "rrdtool not installed" in result["error"]

    def test_rrdtool_timeout(self) -> None:
        """Test handling when rrdtool times out."""
        import subprocess

        from smokeping_api import get_target_data

        with (
            patch("smokeping_api.os.path.exists", return_value=True),
            patch("smokeping_api.os.path.realpath", side_effect=lambda p: p),
            patch("smokeping_api.subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 5)),
        ):
            result = get_target_data("test", "valid.rrd")

            assert result["latency_ms"] is None
            assert "error" in result
            assert "timeout" in result["error"]

    def test_rrdtool_error_return_code(self) -> None:
        """Test handling when rrdtool returns error."""
        from smokeping_api import get_target_data

        with (
            patch("smokeping_api.os.path.exists", return_value=True),
            patch("smokeping_api.os.path.realpath", side_effect=lambda p: p),
            patch("smokeping_api.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(
                returncode=1, stdout="", stderr="ERROR: file not readable"
            )

            result = get_target_data("test", "valid.rrd")

            assert result["latency_ms"] is None
            assert "error" in result

    def test_unexpected_exception_handled(self) -> None:
        """Test that unexpected exceptions are handled gracefully."""
        from smokeping_api import get_target_data

        with (
            patch("smokeping_api.os.path.exists", return_value=True),
            patch("smokeping_api.os.path.realpath", side_effect=lambda p: p),
            patch("smokeping_api.subprocess.run", side_effect=RuntimeError("Unexpected")),
        ):
            result = get_target_data("test", "valid.rrd")

            assert result["latency_ms"] is None
            assert "error" in result
            # Should NOT leak exception details
            assert "Unexpected error" in result["error"]


class MockRequest:
    """Mock HTTP request for testing handler."""

    def __init__(self, path: str) -> None:
        self.path = path

    def makefile(self, mode: str, bufsize: int = -1) -> BytesIO:
        request_line = f"GET {self.path} HTTP/1.1\r\nHost: localhost\r\n\r\n"
        return BytesIO(request_line.encode())


class TestSmokePingAPIHandler:
    """Tests for HTTP handler endpoints."""

    @pytest.fixture
    def handler_class(self) -> type:
        """Get the handler class with mocked dependencies."""
        from smokeping_api import SmokePingAPIHandler

        return SmokePingAPIHandler

    def _make_request(self, handler_class: type, path: str) -> tuple[int, dict[str, Any]]:
        """Helper to make a request and get response."""
        # Capture the response
        response_buffer = BytesIO()

        class TestHandler(handler_class):
            def __init__(self) -> None:
                self.path = path
                self.requestline = f"GET {path} HTTP/1.1"
                self.request_version = "HTTP/1.1"
                self.command = "GET"
                self.headers: dict[str, str] = {}
                self.wfile = response_buffer
                self.rfile = BytesIO()

            def send_response(self, code: int, message: Optional[str] = None) -> None:
                self._response_code = code
                response_buffer.write(f"HTTP/1.1 {code}\r\n".encode())

            def send_header(self, keyword: str, value: str) -> None:
                response_buffer.write(f"{keyword}: {value}\r\n".encode())

            def end_headers(self) -> None:
                response_buffer.write(b"\r\n")

            def log_message(self, fmt: str, *args: Any) -> None:
                pass

        handler = TestHandler()
        handler.do_GET()

        # Parse response
        response_buffer.seek(0)
        response_data = response_buffer.read().decode()

        # Extract status code and body
        parts = response_data.split("\r\n\r\n", 1)
        status_line = parts[0].split("\r\n")[0]
        status_code = int(status_line.split()[1])
        body = json.loads(parts[1]) if len(parts) > 1 and parts[1] else {}

        return status_code, body

    def test_health_endpoint(self, handler_class: type) -> None:
        """Test /health endpoint returns status, hostname, and isp."""
        status, body = self._make_request(handler_class, "/health")

        assert status == 200
        assert body["status"] == "ok"
        assert "hostname" in body
        assert "isp" in body

    def test_root_endpoint(self, handler_class: type) -> None:
        """Test / endpoint returns all targets."""
        with (
            patch("smokeping_api.os.path.exists", return_value=True),
            patch("smokeping_api.os.path.realpath", side_effect=lambda p: p),
            patch("smokeping_api.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="uptime ping1 loss\n\n1735840200: 123456 1.50e-02 0",
                stderr="",
            )

            status, body = self._make_request(handler_class, "/")

            assert status == 200
            assert "targets" in body
            assert "isp" in body
            assert "hostname" in body
            assert "collected_at" in body

    def test_metrics_endpoint_alias(self, handler_class: type) -> None:
        """Test /metrics endpoint works same as /."""
        with (
            patch("smokeping_api.os.path.exists", return_value=True),
            patch("smokeping_api.os.path.realpath", side_effect=lambda p: p),
            patch("smokeping_api.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="uptime ping1 loss\n\n1735840200: 123456 1.50e-02 0",
                stderr="",
            )

            status, body = self._make_request(handler_class, "/metrics")

            assert status == 200
            assert "targets" in body

    def test_valid_target_endpoint(self, handler_class: type) -> None:
        """Test /target/<name> endpoint for valid target."""
        with (
            patch("smokeping_api.os.path.exists", return_value=True),
            patch("smokeping_api.os.path.realpath", side_effect=lambda p: p),
            patch("smokeping_api.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="uptime ping1 loss\n\n1735840200: 123456 1.50e-02 0",
                stderr="",
            )

            status, body = self._make_request(handler_class, "/target/cloudflare")

            assert status == 200
            assert "latency_ms" in body
            assert body["target"] == "cloudflare"
            assert "isp" in body

    def test_invalid_target_endpoint(self, handler_class: type) -> None:
        """Test /target/<name> endpoint for invalid target returns 404."""
        status, body = self._make_request(handler_class, "/target/nonexistent")

        assert status == 404
        assert "error" in body
        assert "available" in body

    def test_unknown_path_returns_404(self, handler_class: type) -> None:
        """Test unknown path returns 404 with endpoints list."""
        status, body = self._make_request(handler_class, "/unknown/path")

        assert status == 404
        assert "error" in body
        assert "endpoints" in body

    def test_cors_headers_present(self, handler_class: type) -> None:
        """Test that CORS headers are present in response."""
        response_buffer = BytesIO()

        class TestHandler(handler_class):
            def __init__(self) -> None:
                self.path = "/health"
                self.requestline = "GET /health HTTP/1.1"
                self.request_version = "HTTP/1.1"
                self.command = "GET"
                self.headers: dict[str, str] = {}
                self.wfile = response_buffer
                self.rfile = BytesIO()
                self._headers_sent: list[tuple[str, str]] = []

            def send_response(self, code: int, message: Optional[str] = None) -> None:
                response_buffer.write(f"HTTP/1.1 {code}\r\n".encode())

            def send_header(self, keyword: str, value: str) -> None:
                self._headers_sent.append((keyword, value))
                response_buffer.write(f"{keyword}: {value}\r\n".encode())

            def end_headers(self) -> None:
                response_buffer.write(b"\r\n")

            def log_message(self, fmt: str, *args: Any) -> None:
                pass

        handler = TestHandler()
        handler.do_GET()

        # Check CORS headers were sent
        header_dict = dict(handler._headers_sent)
        assert "Access-Control-Allow-Origin" in header_dict
        assert header_dict["Access-Control-Allow-Origin"] == "*"

    def test_options_cors_preflight(self, handler_class: type) -> None:
        """Test OPTIONS request returns CORS preflight headers."""
        response_buffer = BytesIO()

        class TestHandler(handler_class):
            def __init__(self) -> None:
                self.path = "/"
                self.requestline = "OPTIONS / HTTP/1.1"
                self.request_version = "HTTP/1.1"
                self.command = "OPTIONS"
                self.headers: dict[str, str] = {}
                self.wfile = response_buffer
                self.rfile = BytesIO()
                self._headers_sent: list[tuple[str, str]] = []
                self._response_code: int = 0

            def send_response(self, code: int, message: Optional[str] = None) -> None:
                self._response_code = code
                response_buffer.write(f"HTTP/1.1 {code}\r\n".encode())

            def send_header(self, keyword: str, value: str) -> None:
                self._headers_sent.append((keyword, value))
                response_buffer.write(f"{keyword}: {value}\r\n".encode())

            def end_headers(self) -> None:
                response_buffer.write(b"\r\n")

            def log_message(self, fmt: str, *args: Any) -> None:
                pass

        handler = TestHandler()
        handler.do_OPTIONS()

        # Check response code is 204 No Content
        assert handler._response_code == 204

        # Check CORS headers were sent
        header_dict = dict(handler._headers_sent)
        assert "Access-Control-Allow-Origin" in header_dict
        assert "Access-Control-Allow-Methods" in header_dict
        assert "GET" in header_dict["Access-Control-Allow-Methods"]
        assert "OPTIONS" in header_dict["Access-Control-Allow-Methods"]

    def test_target_with_hyphen_in_name(self, handler_class: type) -> None:
        """Test that target names with hyphens are accepted."""
        # This tests the regex pattern allows hyphens
        status, body = self._make_request(handler_class, "/target/aws-use1")

        # Should return 404 because target doesn't exist, not because regex failed
        assert status == 404
        assert "error" in body
        assert "available" in body  # Shows it matched the route


class TestConfiguration:
    """Tests for configuration via environment variables."""

    def test_default_bind_address(self) -> None:
        """Test default bind address is localhost (secure by default)."""
        # Need to reload module to test defaults
        import importlib

        import smokeping_api

        # Check the default (without env var set)
        with patch.dict(os.environ, {}, clear=False):
            # Remove env var if set
            os.environ.pop("SMOKEPING_API_BIND_ADDRESS", None)
            importlib.reload(smokeping_api)
            assert smokeping_api.BIND_ADDRESS == "127.0.0.1"

    def test_bind_address_from_env(self) -> None:
        """Test bind address can be set via environment variable."""
        import importlib

        with patch.dict(os.environ, {"SMOKEPING_API_BIND_ADDRESS": "0.0.0.0"}):
            import smokeping_api

            importlib.reload(smokeping_api)
            assert smokeping_api.BIND_ADDRESS == "0.0.0.0"

    def test_port_from_env(self) -> None:
        """Test port can be set via environment variable."""
        import importlib

        with patch.dict(os.environ, {"SMOKEPING_API_PORT": "9090"}):
            import smokeping_api

            importlib.reload(smokeping_api)
            assert smokeping_api.PORT == 9090

    def test_total_pings_from_env(self) -> None:
        """Test total pings can be set via environment variable."""
        import importlib

        with patch.dict(os.environ, {"SMOKEPING_API_TOTAL_PINGS": "10"}):
            import smokeping_api

            importlib.reload(smokeping_api)
            assert smokeping_api.TOTAL_PINGS == 10

    def test_data_dir_from_env(self) -> None:
        """Test data directory can be set via environment variable."""
        import importlib

        with patch.dict(os.environ, {"SMOKEPING_API_DATA_DIR": "/custom/path"}):
            import smokeping_api

            importlib.reload(smokeping_api)
            assert smokeping_api.SMOKEPING_DATA_DIR == "/custom/path"

    def test_isp_from_env(self) -> None:
        """Test ISP can be set via environment variable."""
        import importlib

        with patch.dict(os.environ, {"SMOKEPING_API_ISP": "my-custom-isp"}):
            import smokeping_api

            importlib.reload(smokeping_api)
            assert smokeping_api.ISP == "my-custom-isp"

    def test_isp_fallback_to_detection(self) -> None:
        """Test ISP falls back to hostname detection when not set."""
        import importlib

        # Remove ISP env var and set a hostname that triggers detection
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SMOKEPING_API_ISP", None)
            import smokeping_api

            importlib.reload(smokeping_api)
            # Should use detect_isp() result
            expected_isp = smokeping_api.detect_isp(smokeping_api.HOSTNAME)
            assert expected_isp == smokeping_api.ISP

    def test_invalid_port_uses_default(self) -> None:
        """Test that invalid PORT value falls back to default."""
        import importlib
        from io import StringIO

        with (
            patch.dict(os.environ, {"SMOKEPING_API_PORT": "not_a_number"}),
            patch("sys.stderr", new_callable=StringIO) as mock_stderr,
        ):
            import smokeping_api

            importlib.reload(smokeping_api)
            assert smokeping_api.PORT == 8080
            assert "not a valid integer" in mock_stderr.getvalue()

    def test_port_below_minimum_uses_default(self) -> None:
        """Test that PORT below minimum falls back to default."""
        import importlib
        from io import StringIO

        with (
            patch.dict(os.environ, {"SMOKEPING_API_PORT": "0"}),
            patch("sys.stderr", new_callable=StringIO) as mock_stderr,
        ):
            import smokeping_api

            importlib.reload(smokeping_api)
            assert smokeping_api.PORT == 8080
            assert "below minimum" in mock_stderr.getvalue()

    def test_invalid_total_pings_uses_default(self) -> None:
        """Test that invalid TOTAL_PINGS value falls back to default."""
        import importlib
        from io import StringIO

        with (
            patch.dict(os.environ, {"SMOKEPING_API_TOTAL_PINGS": "abc"}),
            patch("sys.stderr", new_callable=StringIO) as mock_stderr,
        ):
            import smokeping_api

            importlib.reload(smokeping_api)
            assert smokeping_api.TOTAL_PINGS == 20
            assert "not a valid integer" in mock_stderr.getvalue()


class TestParseIntEnv:
    """Tests for _parse_int_env helper function."""

    def test_valid_value(self) -> None:
        """Test parsing valid integer value."""
        from smokeping_api import _parse_int_env

        with patch.dict(os.environ, {"TEST_VAR": "42"}):
            result = _parse_int_env("TEST_VAR", 10, min_val=1)
            assert result == 42

    def test_missing_env_var_uses_default(self) -> None:
        """Test missing env var returns default."""
        from smokeping_api import _parse_int_env

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TEST_VAR_MISSING", None)
            result = _parse_int_env("TEST_VAR_MISSING", 99, min_val=1)
            assert result == 99

    def test_invalid_value_uses_default(self) -> None:
        """Test invalid value returns default with warning."""
        from io import StringIO

        from smokeping_api import _parse_int_env

        with (
            patch.dict(os.environ, {"TEST_VAR": "invalid"}),
            patch("sys.stderr", new_callable=StringIO) as mock_stderr,
        ):
            result = _parse_int_env("TEST_VAR", 50, min_val=1)
            assert result == 50
            assert "not a valid integer" in mock_stderr.getvalue()

    def test_below_minimum_uses_default(self) -> None:
        """Test value below minimum returns default with warning."""
        from io import StringIO

        from smokeping_api import _parse_int_env

        with (
            patch.dict(os.environ, {"TEST_VAR": "0"}),
            patch("sys.stderr", new_callable=StringIO) as mock_stderr,
        ):
            result = _parse_int_env("TEST_VAR", 10, min_val=1)
            assert result == 10
            assert "below minimum" in mock_stderr.getvalue()
