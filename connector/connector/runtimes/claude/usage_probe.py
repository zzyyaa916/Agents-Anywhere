"""Opt-in node-local OAuth usage probe. Credentials never leave this helper's memory."""
from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

URL = "https://api.anthropic.com/api/oauth/usage"


def node_enabled(connector_id):
    """Both pins must match; copying the service environment to another node is insufficient."""
    expected = os.environ.get("AA_CLAUDE_USAGE_PROBE_CONNECTOR_ID")
    machine = os.environ.get("AA_CLAUDE_USAGE_PROBE_MACHINE_ID")
    if not expected or expected != connector_id or not machine or sys.platform != "linux" or platform.machine() not in {"aarch64", "arm64"}:
        return False
    try:
        return hashlib.sha256(Path("/etc/machine-id").read_bytes().strip()).hexdigest() == machine
    except OSError:
        return False


def retry_hint(value):
    try:
        seconds = float(value)
        if math.isfinite(seconds) and seconds >= 0:
            return {"retry_after_seconds": seconds}
    except (ValueError, TypeError):
        pass
    try:
        date = parsedate_to_datetime(value)
        if date.tzinfo is not None:
            return {"retry_after_at": date.astimezone(UTC).isoformat()}
    except (ValueError, TypeError, OverflowError):
        pass
    return {}


def normalized_usage(payload):
    windows = []
    for kind in ("five_hour", "seven_day"):
        item = payload.get(kind)
        if item is None:
            continue
        percent = item.get("utilization")
        if isinstance(percent, bool) or not isinstance(percent, (int, float)) or not math.isfinite(percent) or not 0 <= percent <= 100:
            raise ValueError("invalid usage")
        reset = datetime.fromisoformat(item["resets_at"])
        if reset.tzinfo is None:
            raise ValueError("reset must be timezone aware")
        windows.append({"kind": kind, "used_percent": percent, "resets_at": reset.astimezone(UTC).isoformat()})
    if not windows:
        raise ValueError("no current windows")
    return {"windows": windows}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_usage(command, *, opener=None):
    """Runs as the Claude identity, including behind the fixed-user broker. Never logs exceptions."""
    try:
        version = subprocess.run([*command, "--version"], capture_output=True, text=True, timeout=10, check=True)
        match = re.search(r"\b(\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?)\b", version.stdout)
        if match is None:
            return {"error_code": "unavailable"}
        config = Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude")))
        credentials = json.loads((config / ".credentials.json").read_text())
        token = credentials["claudeAiOauth"]["accessToken"]
        if not isinstance(token, str) or not token or "\r" in token or "\n" in token:
            return {"error_code": "unavailable"}
        request = urllib.request.Request(URL, method="GET", headers={
            "Authorization": "Bearer " + token,
            "anthropic-beta": "oauth-2025-04-20",
            "User-Agent": "claude-code/" + match.group(1),
            "Accept": "application/json",
        })
        # Direct TLS only. Never forward the bearer token to redirects or environment proxies.
        client = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with client.open(request, timeout=20) as response:
            data = response.read(65537)
            if len(data) > 65536:
                return {"error_code": "unavailable"}
            return normalized_usage(json.loads(data))
    except urllib.error.HTTPError as error:
        try:
            if error.code == 429:
                return {"error_code": "rate_limited", **retry_hint((error.headers or {}).get("Retry-After"))}
            return {"error_code": "unavailable"}
        finally:
            error.close()
    except Exception:  # noqa: BLE001 -- raw upstream/credential failures must never escape.
        # Upstream errors, response bodies, subprocess output and credentials must never be logged.
        return {"error_code": "unavailable"}


if __name__ == "__main__":
    print(json.dumps(fetch_usage(sys.argv[1:])))
