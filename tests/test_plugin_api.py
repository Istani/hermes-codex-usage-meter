"""Behavior tests for the local Codex quota adapter.

These tests only exercise normalized, synthetic app-server payloads. They never
read a credential file or contact OpenAI.
"""
from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = PLUGIN_ROOT / "dashboard" / "plugin_api.py"


def load_module():
    spec = importlib.util.spec_from_file_location("codex_usage_meter_api", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CodexUsageMeterBackendTests(unittest.TestCase):
    def test_normalizes_real_app_server_limit_shapes_and_preserves_absence(self):
        api = load_module()
        payload = {
            "rateLimits": {
                "primary": {"usedPercent": 42, "windowDurationMins": 300, "resetsAt": 1_800_000_000},
                "secondary": {"used_percent": 68, "window_duration_mins": 10_080, "reset_at": "2027-01-15T12:00:00Z"},
                "credits": {"balance": 3},
            }
        }
        result = api.normalize_rate_limits(payload, now=datetime(2027, 1, 12, tzinfo=timezone.utc))
        self.assertEqual(result["five_hour"]["used_percent"], 42)
        self.assertEqual(result["five_hour"]["remaining_percent"], 58)
        self.assertEqual(result["five_hour"]["reset_at"], "2027-01-15T08:00:00+00:00")
        self.assertEqual(result["week"]["used_percent"], 68)
        self.assertEqual(result["week"]["remaining_percent"], 32)
        self.assertEqual(result["week"]["reset_at"], "2027-01-15T12:00:00+00:00")
        self.assertEqual(result["credits"], 3)
        self.assertIsNone(api.normalize_rate_limits({}, now=datetime.now(timezone.utc))["week"])

    def test_marks_expired_reset_as_refreshing_instead_of_inventing_zero(self):
        api = load_module()
        result = api.normalize_rate_limits(
            {"rateLimits": {"primary": {"usedPercent": 20, "resetsAt": 1_700_000_000}}},
            now=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(result["five_hour"]["reset_state"], "refreshing")
        self.assertIsNone(result["week"])

    def test_pace_uses_actual_reset_interval_and_workweek_excludes_weekend(self):
        api = load_module()
        start = datetime(2027, 1, 4, 0, 0, tzinfo=timezone.utc)  # Monday
        reset = datetime(2027, 1, 11, 0, 0, tzinfo=timezone.utc)
        mid_workweek = datetime(2027, 1, 6, 12, 0, tzinfo=timezone.utc)
        work = api.compute_pace(used_percent=48, reset_at=reset, observed_at=start, now=mid_workweek, mode="workweek")
        calendar = api.compute_pace(used_percent=48, reset_at=reset, observed_at=start, now=mid_workweek, mode="calendar")
        self.assertEqual(work["target_used_percent"], 50)
        self.assertEqual(work["status"], "im_plan")
        self.assertEqual(calendar["target_used_percent"], 36)
        self.assertEqual(calendar["status"], "over_plan")

    def test_pace_returns_unavailable_without_a_trustworthy_observation_boundary(self):
        api = load_module()
        self.assertIsNone(api.compute_pace(used_percent=20, reset_at=None, observed_at=None, now=datetime.now(timezone.utc), mode="workweek"))

    def test_finds_the_official_windows_codex_app_without_relying_on_path(self):
        api = load_module()
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "OpenAI" / "Codex" / "bin" / "release" / "codex.exe"
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b"")
            with patch.object(api.shutil, "which", return_value=None), patch.dict(os.environ, {"LOCALAPPDATA": directory}, clear=False):
                self.assertEqual(api._find_codex_executable(), str(executable))


if __name__ == "__main__":
    unittest.main()
