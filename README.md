# codex-usage-meter

A **local, read-only** Hermes Desktop plugin that shows the real Codex quota
reported by the installed Codex CLI: the current 5-hour window, the weekly
window, their provider-supplied reset timestamps, and a weekly consumption pace.

## Data source and privacy

- Calls `codex app-server --stdio`, then the documented JSON-RPC method
  `account/rateLimits/read`.
- Uses the existing Codex ChatGPT/OAuth login only. It never reads, copies,
  stores, logs, or transmits OAuth tokens, API keys, browser cookies, account
  identifiers, Codex sessions, project files, or conversation contents.
- No telemetry, analytics, third-party network calls, quota estimation, credit
  purchase, limit reset, or subscription changes.
- Only the rendered quota fields (percentage, reset time, optional balance and
  count of available reset credits) are retained in process memory as a
  short-lived cache. UI preferences, notification de-duplication, and — only
  when the user enables it — the most recent local quota snapshot are stored
  privately with `ctx.storage`. The snapshot contains no credentials or session
  data and is visibly marked as stale when used.

## Installation and activation

Clone this repository directly into your Hermes plugin directory:

```bash
git clone https://github.com/Istani/hermes-desktop-codex-usage-meter.git \
  "$HERMES_HOME/plugins/codex-usage-meter"
```

The unified plugin must then be located at:

```text
$HERMES_HOME/plugins/codex-usage-meter/
```

Enable the backend from a local terminal:

```bash
hermes plugins enable codex-usage-meter
```

Then in **Hermes Desktop → Settings → Plugins**, enable **Codex Usage Meter**.
Use **Cmd/Ctrl+K → Reload desktop plugins** if it was open while installed.
The desktop contribution is opt-in by design.

## UI

- **Status bar, right side:** compact two-meter chip (`5 h` and `Woche`),
  remaining percentage, warning/offline state, native tooltip. Click it to open
  the detailed workspace view.
- **Native pane:** **Codex-Verbrauch**, initially placed on the right and fully
  draggable like any Hermes pane. It includes 5-hour and weekly cards, exact
  local reset times and countdowns, weekly pace, settings, refresh button, and
  last successful update.
- **Notifications:** disabled by default. When enabled, the meter only sends a
  de-duplicated in-app notice for a material pace deviation or clearly high
  residual budget late in the actual weekly quota period. OS notifications use
  `ctx.os.notify` only after their separate opt-in.

## Weekly pace

Default mode is **Arbeitswoche** (Monday–Friday); **Kalenderwoche** is optional.
The pace denominator is calculated from the actual weekly reset timestamp and
window duration supplied by Codex — not from a hard-coded ISO week. Missing or
expired resets show **Nicht verfügbar** / **wird aktualisiert**, never a false
zero.

## Troubleshooting

- **“Codex CLI nicht gefunden”** — install or update the local Codex app/CLI.
- **No authorized limits** — run `codex login status`; sign in through the
  normal Codex app/CLI flow. Do not paste credentials into Hermes.
- **Data stale** — the last valid local reading remains visible while the next
  app-server request fails. Use **Aktualisieren** to retry.
- **Remote Hermes gateway** — `ctx.rest()` is routed to the focused gateway, so
  a remote gateway cannot execute the local Codex CLI. In **Einstellungen**, you
  can enable **„Bei Remote-Gateways letzten lokalen Snapshot anzeigen“**. The
  meter then ignores the remote result and keeps showing the last successful
  local reading, explicitly labeled **„Lokaler Snapshot“** / stale. It is a
  continuity display, not a live remote poll; credentials are never copied to
  the remote gateway.

## Development checks

```bash
python tests/test_plugin_api.py
python -m py_compile dashboard/plugin_api.py
node --check desktop/plugin.js
hermes plugins doctor "$HERMES_HOME/plugins/codex-usage-meter"
```
