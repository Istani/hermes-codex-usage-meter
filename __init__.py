"""Unified package marker for the Codex Usage Meter.

The feature exposes no model-visible tools or hooks; its FastAPI router is
loaded from dashboard/plugin_api.py and its desktop UI from desktop/plugin.js.
"""


def register(ctx):
    """Satisfy the unified Hermes plugin lifecycle without registering tools."""
    return None
