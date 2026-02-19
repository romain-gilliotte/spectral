"""Tests for cli/helpers/subprocess.py."""

import subprocess
from unittest.mock import patch

import pytest

from cli.helpers.subprocess import run_cmd


class TestRunCmd:
    def test_success(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["echo"], returncode=0, stdout="hello\n", stderr=""
            )
            result = run_cmd(["echo", "hello"], "Echo test")
            assert result.stdout == "hello\n"

    def test_failure_raises_runtime_error(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["false"], returncode=1, stdout="", stderr="boom"
            )
            with pytest.raises(RuntimeError, match="Doing stuff \\(exit 1\\): boom"):
                run_cmd(["false"], "Doing stuff")

    def test_error_message_format(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=42, stdout="", stderr="bad thing"
            )
            with pytest.raises(RuntimeError, match=r"\(exit 42\)"):
                run_cmd(["x"], "Build")

    def test_timeout_forwarded(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            )
            run_cmd(["sleep", "0"], "Sleep test", timeout=999)
            _, kwargs = mock_run.call_args
            assert kwargs["timeout"] == 999
