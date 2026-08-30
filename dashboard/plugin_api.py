"""Local, read-only Codex rate-limit adapter for codex-usage-meter.

Only invokes the installed Codex CLI's app-server protocol. OAuth material stays
inside Codex; this module neither reads nor logs credential files.
"""
from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

try:
    from fastapi import APIRouter
except Exception:  # permits isolated standard-library tests
    class APIRouter:  # type: ignore[no-redef]
        def get(self, *_args: Any, **_kwargs: Any):
            return lambda fn: fn
        def post(self, *_args: Any, **_kwargs: Any):
            return lambda fn: fn

router = APIRouter()

CACHE_TTL_SECONDS = 55
APP_SERVER_TIMEOUT_SECONDS = 15
_cache_lock = threading.Lock()
_cache: Optional[Dict[str, Any]] = None
_cache_at = 0.0


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _clamp_percent(value: Any) -> Optional[int]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number < 0 or number > 100:
        return None
    return int(round(number))


def _parse_time(value: Any) -> Optional[datetime]:
    if isinstance(value, (int, float)) and value > 0:
        # Codex currently returns Unix seconds; accept milliseconds defensively.
        seconds = float(value) / 1000 if value > 10_000_000_000 else float(value)
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            return None
    return None


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _read_value(mapping: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def _normalize_window(raw: Any, now: datetime) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    used = _clamp_percent(_read_value(raw, "usedPercent", "used_percent"))
    if used is None:
        return None
    reset = _parse_time(_read_value(raw, "resetsAt", "reset_at", "resetAt"))
    duration = _read_value(raw, "windowDurationMins", "window_duration_mins")
    try:
        duration_minutes = int(duration) if duration is not None else None
    except (TypeError, ValueError):
        duration_minutes = None
    return {
        "used_percent": used,
        "remaining_percent": 100 - used,
        "reset_at": _iso(reset),
        "reset_state": "refreshing" if reset is None or reset <= now else "scheduled",
        "window_duration_minutes": duration_minutes,
    }


def normalize_rate_limits(payload: Dict[str, Any], now: Optional[datetime] = None) -> Dict[str, Any]:
    """Return the only quota fields UI needs; missing input stays unavailable."""
    now = now or _utc_now()
    limits = payload.get("rateLimits") if isinstance(payload, dict) else None
    if not isinstance(limits, dict):
        limits = payload if isinstance(payload, dict) else {}
    credits = limits.get("credits") if isinstance(limits.get("credits"), dict) else {}
    balance = _read_value(credits, "balance", "available")
    try:
        balance = int(balance) if balance is not None else None
    except (TypeError, ValueError):
        balance = None
    reset_credits = payload.get("rateLimitResetCredits") if isinstance(payload, dict) else {}
    available_resets = reset_credits.get("availableCount") if isinstance(reset_credits, dict) else None
    try:
        available_resets = int(available_resets) if available_resets is not None else None
    except (TypeError, ValueError):
        available_resets = None
    return {
        "five_hour": _normalize_window(limits.get("primary"), now),
        "week": _normalize_window(limits.get("secondary"), now),
        "credits": balance,
        "available_reset_credits": available_resets,
    }


def _work_seconds(start: datetime, end: datetime) -> float:
    """Seconds inside Mon–Fri, retaining precise partial-day boundaries."""
    if end <= start:
        return 0.0
    cursor = start
    total = 0.0
    while cursor < end:
        day_end = min(end, datetime.combine(cursor.date() + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc))
        if cursor.weekday() < 5:
            total += max(0.0, (day_end - cursor).total_seconds())
        cursor = day_end
    return total


def compute_pace(*, used_percent: int, reset_at: Optional[datetime], observed_at: Optional[datetime], now: datetime, mode: str) -> Optional[Dict[str, Any]]:
    """Compare actual weekly use to the elapsed provider-defined quota period."""
    if reset_at is None or observed_at is None or reset_at <= observed_at:
        return None
    now = min(max(now, observed_at), reset_at)
    if mode == "workweek":
        total = _work_seconds(observed_at, reset_at)
        elapsed = _work_seconds(observed_at, now)
    else:
        total = (reset_at - observed_at).total_seconds()
        elapsed = (now - observed_at).total_seconds()
    if total <= 0:
        return None
    target = int(round(100 * elapsed / total))
    delta = int(used_percent) - target
    status = "under_plan" if delta <= -7 else "over_plan" if delta >= 7 else "im_plan"
    return {"target_used_percent": target, "actual_used_percent": int(used_percent), "delta_percent": delta, "status": status}


def _safe_error(value: Any) -> str:
    message = str(value or "Abruf fehlgeschlagen.").replace("\n", " ")[:180]
    for marker in ("Bearer ", "access_token", "refresh_token", "Authorization"):
        if marker.lower() in message.lower():
            return "Lokaler Codex-Abruf fehlgeschlagen. Details wurden aus Datenschutzgründen ausgeblendet."
    return message


def _find_codex_executable() -> Optional[str]:
    """Resolve Codex without inspecting any credential or project files."""
    on_path = shutil.which("codex")
    if on_path:
        return on_path
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return None
    # The official Windows installer keeps versioned CLI builds here. Limit the
    # lookup to that product-owned directory; never search user files broadly.
    root = Path(local_app_data) / "OpenAI" / "Codex" / "bin"
    for pattern in ("*/codex.exe", "*/codex"):
        for candidate in sorted(root.glob(pattern), reverse=True):
            if candidate.is_file():
                return str(candidate)
    return None


def _rpc_read_rate_limits() -> Dict[str, Any]:
    executable = _find_codex_executable()
    if not executable:
        raise RuntimeError("Codex CLI nicht gefunden. Installiere oder aktualisiere die lokale Codex-App.")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.Popen(
        [executable, "app-server", "--stdio"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True, bufsize=1, creationflags=flags,
    )
    messages: "queue.Queue[Dict[str, Any]]" = queue.Queue()
    def reader() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            try:
                value = json.loads(line)
                if isinstance(value, dict):
                    messages.put(value)
            except json.JSONDecodeError:
                continue
    threading.Thread(target=reader, daemon=True).start()
    def request(request_id: int, method: str, params: Any = None) -> Dict[str, Any]:
        assert proc.stdin is not None
        body: Dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            body["params"] = params
        proc.stdin.write(json.dumps(body) + "\n")
        proc.stdin.flush()
        deadline = time.monotonic() + APP_SERVER_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            try:
                item = messages.get(timeout=0.25)
            except queue.Empty:
                if proc.poll() is not None:
                    raise RuntimeError("Codex app-server wurde unerwartet beendet.")
                continue
            if item.get("id") == request_id:
                if isinstance(item.get("error"), dict):
                    raise RuntimeError(_safe_error(item["error"].get("message")))
                result = item.get("result")
                if not isinstance(result, dict):
                    raise RuntimeError("Codex lieferte keine lesbaren Rate-Limits.")
                return result
        raise RuntimeError("Codex app-server hat nicht rechtzeitig geantwortet.")
    try:
        request(1, "initialize", {"clientInfo": {"name": "codex-usage-meter", "version": "1.0.0"}, "capabilities": {}})
        return request(2, "account/rateLimits/read")
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)
        if proc.returncode not in (0, None, -15):
            # Exit status is deliberately checked, but not surfaced verbatim.
            pass


def _fetch(force: bool = False) -> Dict[str, Any]:
    global _cache, _cache_at
    now = _utc_now()
    with _cache_lock:
        if not force and _cache and time.monotonic() - _cache_at < CACHE_TTL_SECONDS:
            return {**_cache, "cached": True}
    try:
        raw = _rpc_read_rate_limits()
        data = normalize_rate_limits(raw, now)
        week = data.get("week")
        if isinstance(week, dict):
            reset = _parse_time(week.get("reset_at"))
            duration = week.get("window_duration_minutes")
            observed = reset - timedelta(minutes=int(duration)) if reset and duration else None
            data["pace"] = compute_pace(used_percent=week["used_percent"], reset_at=reset, observed_at=observed, now=now, mode="calendar")
        else:
            data["pace"] = None
        result = {"state": "ok", "message": "Lokale Codex-Anmeldung", "data": data, "source_updated_at": _iso(now), "stale": False, "cached": False, "local_source": True}
        with _cache_lock:
            _cache, _cache_at = result, time.monotonic()
        return result
    except Exception as exc:
        with _cache_lock:
            if _cache:
                return {**_cache, "state": "stale", "message": _safe_error(exc), "stale": True, "cached": False}
        return {"state": "unavailable", "message": _safe_error(exc), "data": None, "source_updated_at": None, "stale": False, "cached": False, "local_source": True}


@router.get("/usage")
def usage() -> Dict[str, Any]:
    return _fetch()


@router.post("/refresh")
def refresh() -> Dict[str, Any]:
    return _fetch(force=True)
