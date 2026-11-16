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
import tempfile
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
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


class ParseError(ValueError):
    """Contains only controlled field paths and exception categories."""

    def __init__(self, warnings):
        self.warnings = warnings
        super().__init__("; ".join(w["field"] + ": " + w["reason"] for w in warnings))


def normalized_usage(payload):
    if not isinstance(payload, dict):
        raise ParseError([{"field": "$", "reason": "TypeError"}])
    windows, warnings = [], []
    for kind in ("five_hour", "seven_day"):
        if kind not in payload:
            warnings.append({"field": kind, "reason": "MissingField"})
            continue
        field = kind
        try:
            item = payload[kind]
            if not isinstance(item, dict):
                raise TypeError()
            field = kind + ".utilization"
            if "utilization" not in item:
                warnings.append({"field": field, "reason": "MissingField"})
                continue
            percent = item["utilization"]
            reset = item.get("resets_at")
            if percent is None and reset is None:
                percent = 0
            if isinstance(percent, bool) or not isinstance(percent, (int, float)):
                raise TypeError()
            if not math.isfinite(percent) or not 0 <= percent <= 100:
                raise ValueError()
            field = kind + ".resets_at"
            if reset is not None:
                if not isinstance(reset, str):
                    raise TypeError()
                reset = datetime.fromisoformat(reset)
                if reset.tzinfo is None:
                    raise ValueError()
                reset = reset.astimezone(UTC).isoformat()
            elif "resets_at" not in item:
                warnings.append({"field": field, "reason": "MissingField"})
            windows.append({"kind": kind, "used_percent": percent, "resets_at": reset})
        except (TypeError, ValueError, OverflowError) as error:
            warnings.append({"field": field, "reason": type(error).__name__})
    if not windows:
        raise ParseError(warnings or [{"field": "windows", "reason": "MissingField"}])
    return {"windows": windows, **({"parse_warnings": warnings} if warnings else {})}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


TOKEN_URL = "https://console.anthropic.com/v1/oauth/token"
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"


class AuthExpired(Exception):
    def __init__(self, detail=None):
        self.detail = detail


class CredentialLockTimeout(Exception):
    """Another cooperating process held the credential lock for too long."""


def _token(value):
    if not isinstance(value, str) or not value or "\r" in value or "\n" in value:
        raise AuthExpired()
    return value


def _credentials(path):
    with path.open() as stream:
        value = json.load(stream)
        stat = os.fstat(stream.fileno())
    oauth = value["claudeAiOauth"]
    _token(oauth["accessToken"])
    _token(oauth["refreshToken"])
    expires = oauth["expiresAt"]
    if isinstance(expires, bool) or not isinstance(expires, (int, float)) or not math.isfinite(expires):
        raise AuthExpired()
    return value, stat


@contextmanager
def _credential_lock(path):
    # Only cooperating writers use this lock. An external login can still race
    # the final refresh-token comparison and rename; that residual risk remains.
    import fcntl
    fd = os.open(str(path) + ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "a") as stream:
        deadline = time.monotonic() + 5
        while True:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise CredentialLockTimeout() from None
                time.sleep(0.05)
        yield


def _refresh(path, previous, client, *, force=False, user_agent):
    refreshed = False
    temporary = None
    try:
        with _credential_lock(path):
            current, _ = _credentials(path)
            oauth = current["claudeAiOauth"]
            if oauth["refreshToken"] != previous["claudeAiOauth"]["refreshToken"]:
                return current, False
            if not force and oauth["expiresAt"] > (time.time() + 60) * 1000:
                return current, False
            request = urllib.request.Request(TOKEN_URL, method="POST", data=json.dumps({
                "grant_type": "refresh_token", "refresh_token": oauth["refreshToken"],
                "client_id": CLIENT_ID,
            }).encode(), headers={"Content-Type": "application/json", "Accept": "application/json", "User-Agent": user_agent})
            with client.open(request, timeout=20) as response:
                raw = response.read(65537)
                if len(raw) > 65536:
                    raise AuthExpired()
                result = json.loads(raw)
            access = _token(result["access_token"])
            refresh = _token(result["refresh_token"])
            duration = result["expires_in"]
            if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
                raise AuthExpired()
            expires = int((time.time() + duration) * 1000)
            refreshed = True
            # Preserve other fields from the latest file, including changes made
            # during the request. Never overwrite a newer external login.
            latest, latest_stat = _credentials(path)
            if latest["claudeAiOauth"]["refreshToken"] != oauth["refreshToken"]:
                return latest, True
            latest["claudeAiOauth"].update(accessToken=access, refreshToken=refresh, expiresAt=expires)
            fd, temporary = tempfile.mkstemp(prefix=".credentials-", dir=path.parent)
            with os.fdopen(fd, "w") as stream:
                if (os.fstat(stream.fileno()).st_uid, os.fstat(stream.fileno()).st_gid) != (latest_stat.st_uid, latest_stat.st_gid):
                    os.fchown(stream.fileno(), latest_stat.st_uid, latest_stat.st_gid)
                os.fchmod(stream.fileno(), 0o600)
                json.dump(latest, stream)
                stream.flush()
                os.fsync(stream.fileno())
            # Hard requirement: compare again immediately before replacement.
            final, _ = _credentials(path)
            if final["claudeAiOauth"]["refreshToken"] != oauth["refreshToken"]:
                return final, True
            os.replace(temporary, path)
            temporary = None
            return latest, True
    except urllib.error.HTTPError as error:
        error.close()
        raise AuthExpired() from None
    except CredentialLockTimeout:
        raise
    except Exception:  # noqa: BLE001 -- Never include credential, response or exception text.
        raise AuthExpired("write_failed_after_refresh" if refreshed else None) from None
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass


def fetch_usage(command, *, opener=None):
    """Runs as the Claude identity. Only sanitized categories leave this helper."""
    try:
        version = subprocess.run([*command, "--version"], capture_output=True, text=True, timeout=10, check=True)
        match = re.search(r"\b(\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?)\b", version.stdout)
        if match is None:
            return {"error_code": "unavailable"}
        config = Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude")))
        path = config / ".credentials.json"
        try:
            credentials, _ = _credentials(path)
        except Exception:  # noqa: BLE001 -- sanitized credential read failure
            raise AuthExpired() from None
        # Both endpoints use direct TLS, with proxies and redirects disabled.
        client = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        refreshed = False
        user_agent = "claude-code/" + match.group(1)
        if credentials["claudeAiOauth"]["expiresAt"] <= (time.time() + 60) * 1000:
            credentials, refreshed = _refresh(path, credentials, client, user_agent=user_agent)
        for attempt in range(2):
            request = urllib.request.Request(URL, method="GET", headers={
                "Authorization": "Bearer " + _token(credentials["claudeAiOauth"]["accessToken"]),
                "anthropic-beta": "oauth-2025-04-20",
                "User-Agent": user_agent, "Accept": "application/json",
            })
            try:
                with client.open(request, timeout=20) as response:
                    data = response.read(65537)
                if len(data) > 65536:
                    raise ParseError([{"field": "$", "reason": "SizeLimit"}])
                try:
                    payload = json.loads(data)
                except (ValueError, UnicodeError) as error:
                    raise ParseError([{"field": "$", "reason": type(error).__name__}]) from None
                return normalized_usage(payload)
            except urllib.error.HTTPError as error:
                try:
                    if error.code == 429:
                        return {"error_code": "rate_limited", **retry_hint((error.headers or {}).get("Retry-After"))}
                    if error.code != 401:
                        return {"error_code": "unavailable"}
                finally:
                    error.close()
                if refreshed or attempt:
                    raise AuthExpired()
                credentials, refreshed = _refresh(path, credentials, client, force=True, user_agent=user_agent)
        raise AuthExpired()
    except ParseError as error:
        return {"error_code": "parse_error", "detail": str(error), "parse_warnings": error.warnings}
    except AuthExpired as error:
        return {"error_code": "auth_expired", **({"detail": error.detail} if error.detail else {})}
    except Exception:  # noqa: BLE001 -- No raw upstream, credential, subprocess or exception text.
        return {"error_code": "unavailable"}


if __name__ == "__main__":
    print(json.dumps(fetch_usage(sys.argv[1:])))
