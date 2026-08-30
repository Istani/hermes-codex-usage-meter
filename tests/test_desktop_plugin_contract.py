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

    def test_can_persist_and_render_a_clearly_marked_local_snapshot_for_remote_work(self):
        source = PLUGIN_JS.read_text(encoding="utf-8")
        self.assertIn("keepLocalQuotaOnRemote: false", source)
        self.assertIn("localQuotaSnapshot", source)
        self.assertIn("Lokaler Snapshot", source)
        self.assertIn("snapshotResponse", source)
        self.assertIn("liveResponse?.route_mode === 'remote' && settings.keepLocalQuotaOnRemote", source)


if __name__ == "__main__":
    unittest.main()
