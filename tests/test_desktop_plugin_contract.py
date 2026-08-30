"""Contract checks for the desktop data-source routing policy.

The desktop bridge already scopes ctx.rest() to the focused chat's backend.
A registry containing *other* remote profiles must not suppress a request for
an active This-device chat, because that produces a false "Nicht verfügbar".
"""
from pathlib import Path
import unittest

PLUGIN_JS = Path(__file__).resolve().parents[1] / "desktop" / "plugin.js"


class DesktopPluginContractTests(unittest.TestCase):
    def test_usage_queries_are_not_disabled_by_unrelated_remote_routes(self):
        source = PLUGIN_JS.read_text(encoding="utf-8")
        self.assertNotIn("enabled: localSource !== false", source)
        self.assertEqual(source.count("enabled: true"), 2)

    def test_snapshot_fallback_is_not_shipped(self):
        source = PLUGIN_JS.read_text(encoding="utf-8")
        for removed in ("keepLocalQuotaOnRemote", "localQuotaSnapshot", "Lokaler Snapshot", "snapshotResponse", "route_mode"):
            self.assertNotIn(removed, source)


if __name__ == "__main__":
    unittest.main()
