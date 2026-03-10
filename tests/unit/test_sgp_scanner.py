"""Unit tests for sgp_scanner.py CLI."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCANNER = ROOT / "scripts" / "sgp_scanner.py"
PYTHON = sys.executable


def test_cli_help_exits_cleanly():
    """--help must exit with code 0 and contain 'mode' in stdout."""
    result = subprocess.run(
        [PYTHON, str(SCANNER), "--help"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert result.returncode == 0, f"Expected exit 0, got {result.returncode}\n{result.stderr}"
    assert "mode" in result.stdout.lower(), "'mode' not found in --help output"


def test_cli_no_api_key_exits_gracefully(monkeypatch):
    """Running without ODDS_API_KEY must not crash with a traceback."""
    import os
    env = {k: v for k, v in os.environ.items() if k != "ODDS_API_KEY"}
    # Also scrub any .env-loaded value by passing empty string
    env["ODDS_API_KEY"] = ""

    result = subprocess.run(
        [PYTHON, str(SCANNER), "--mode", "parlay"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        env=env,
    )
    # Should exit cleanly (0 or non-zero but no unhandled exception)
    assert "Traceback" not in result.stdout
    assert "Traceback" not in result.stderr
