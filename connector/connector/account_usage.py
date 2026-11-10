"""Read-only local account usage. No raw credentials or upstream bodies leave this module."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path


from connector.core.fork_profile import fork_enabled
from connector.native_cli import codex_command

MINIMUM = {"codex": 60, "claude_code": 300}
PLANS = {"free", "plus", "pro", "max", "team", "business", "enterprise", "edu", "go"}


class UsageUnavailable(Exception):
    def __init__(self, code="unavailable"):
        self.code = code
        super().__init__(code)


def identity(runtime, value, plan=None):
    if not isinstance(value, str) or not value.strip():
        raise UsageUnavailable("account_unavailable")
    key = hashlib.sha256(
        (runtime + "\0" + value.strip().casefold()).encode()
    ).hexdigest()
    return {
        "runtime": runtime,
        "account_key": key,
        "plan_type": plan if plan in PLANS else None,
    }


def window(kind, used, reset, minutes, scope=None):
    if (
        isinstance(used, bool)
        or not isinstance(used, (int, float))
        or not math.isfinite(used)
        or not 0 <= used <= 100
    ):
        raise UsageUnavailable("invalid_response")
    if isinstance(reset, (int, float)) and not isinstance(reset, bool):
        reset = datetime.fromtimestamp(reset, UTC)
    elif isinstance(reset, str):
        reset = datetime.fromisoformat(reset)
        if reset.tzinfo is None:
            raise UsageUnavailable("invalid_response")
    else:
        raise UsageUnavailable("invalid_response")
    return {
        "kind": kind,
        "model_scope": scope,
        "used_percent": used,
        "remaining_percent": 100 - used,
        "resets_at": reset.astimezone(UTC).isoformat(),
        "window_duration_mins": minutes,
    }


def codex_windows(payload):
    bucket = (payload.get("rateLimitsByLimitId") or {}).get("codex") or payload.get(
        "rateLimits"
    )
    if not isinstance(bucket, dict) or bucket.get("limitId", "codex") != "codex":
        raise UsageUnavailable("invalid_response")
    result = []
    for field in ("primary", "secondary"):
        value = bucket.get(field)
        if value is None:
            continue
        duration = value.get("windowDurationMins")
        if isinstance(duration, bool) or not isinstance(duration, int) or duration <= 0:
            raise UsageUnavailable("invalid_response")
        kind = {300: "five_hour", 10080: "weekly"}.get(duration, "other")
        result.append(
            window(kind, value.get("usedPercent"), value.get("resetsAt"), duration)
        )
    if not result:
        raise UsageUnavailable("invalid_response")
    return result


@asynccontextmanager
async def codex_process(executable=None):
    # Intentionally no auth-file reads, token forwarding, login/logout or turn requests.
    command, environment = await asyncio.to_thread(codex_command, ["app-server"], executable)
    process = await asyncio.create_subprocess_exec(
        *command,
        env=environment,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        limit=2 * 1024 * 1024,
    )
    sequence = 0

    async def request(method, params=None):
        nonlocal sequence
        if method not in {"initialize", "account/read", "account/rateLimits/read", "model/list"}:
            raise UsageUnavailable("invalid_request")
        sequence += 1
        request_id = sequence
        process.stdin.write(
            (
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "method": method,
                        "params": params or {},
                    }
                )
                + "\n"
            ).encode()
        )
        await process.stdin.drain()
        async with asyncio.timeout(20):
            while True:
                line = await process.stdout.readline()
                if not line:
                    raise UsageUnavailable()
                body = json.loads(line)
                if body.get("id") != request_id:
                    if "method" in body and "id" in body:
                        process.stdin.write(
                            (
                                json.dumps(
                                    {
                                        "jsonrpc": "2.0",
                                        "id": body["id"],
                                        "error": {
                                            "code": -32601,
                                            "message": "read-only collector",
                                        },
                                    }
                                )
                                + "\n"
                            ).encode()
                        )
                        await process.stdin.drain()
                    continue
                if "error" in body:
                    raise UsageUnavailable(
                        "rate_limited"
                        if (body["error"].get("data") or {}).get("httpStatusCode")
                        == 429
                        else "unavailable"
                    )
                return body["result"]

    try:
        await request(
            "initialize",
            {
                "clientInfo": {
                    "name": "agents_anywhere_usage",
                    "title": "Agents Anywhere usage",
                    "version": "2.5.2",
                }
            },
        )
        process.stdin.write(b'{"jsonrpc":"2.0","method":"initialized"}\n')
        await process.stdin.drain()
        yield request
    finally:
        if process.stdin:
            process.stdin.close()
        if process.returncode is None:
            try:
                process.terminate()
                await asyncio.wait_for(process.wait(), 2)
            except ProcessLookupError:
                pass
            except TimeoutError:
                process.kill()
                await process.wait()


class LocalAccountUsage:
    def __init__(
        self,
        kv,
        *,
        home=None,
        clock=time.time,
        codex_factory=codex_process,
    ):
        self.kv, self.home = kv, Path(home) if home is not None else Path.home()
        self.clock = clock
        self.codex_factory = codex_factory
        self._lock = asyncio.Lock()

    def claude_identity(self):
        config_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR", self.home / ".claude"))
        profile_path = (
            self.home / ".claude.json"
            if "CLAUDE_CONFIG_DIR" not in os.environ
            else config_dir / ".claude.json"
        )
        profile = json.loads(profile_path.read_text())
        account = profile.get("oauthAccount") or {}
        # Stable identity, never hash a rotating OAuth credential.
        return identity(
            "claude_code",
            account.get("accountUuid") or account.get("emailAddress"),
            account.get("subscriptionType"),
        )

    async def identify(self, runtime, executable=None):
        try:
            if runtime == "codex":
                async with self.codex_factory(executable) as request:
                    account = (
                        await request("account/read", {"refreshToken": False})
                    ).get("account") or {}
                    if account.get("type") != "chatgpt":
                        raise UsageUnavailable("unsupported_auth")
                    return identity(
                        runtime, account.get("email"), account.get("planType")
                    )
            if runtime == "claude_code":
                return self.claude_identity()
            raise UsageUnavailable("unsupported_auth")
        except Exception as exc:  # noqa: BLE001 -- sanitized failure, never propagate upstream bodies
            return {
                "runtime": runtime,
                "account_key": None,
                "plan_type": None,
                "error_code": exc.code
                if isinstance(exc, UsageUnavailable)
                else "account_unavailable"
                if isinstance(exc, FileNotFoundError)
                else "unavailable",
            }

    def observe_claude_window(self, expected_key, kind, utilization, resets_at):
        """Accept only normalized native metadata; never read a credential or make a request."""
        try:
            info = self.claude_identity()
            if info["account_key"] != expected_key:
                return False
            if isinstance(utilization, bool) or not isinstance(utilization, (int, float)) or not math.isfinite(utilization) or not 0 <= utilization <= 1:
                return False
            if isinstance(resets_at, bool) or not isinstance(resets_at, int) or resets_at <= self.clock():
                return False
            normalized_kind, scope, minutes = {
                "five_hour": ("five_hour", None, 300),
                "seven_day": ("seven_day", None, 10080),
                "seven_day_opus": ("weekly_scoped", "opus", 10080),
                "seven_day_sonnet": ("weekly_scoped", "sonnet", 10080),
            }[kind]
            value = window(normalized_kind, utilization * 100, resets_at, minutes, scope)
            key = "native-claude-usage/" + expected_key
            cached = dict(self.kv.get(key) or {})
            windows = dict(cached.get("windows") or {})
            windows[kind] = {"window": value, "observed_at": self.clock()}
            self.kv.set(key, {"windows": windows})
            return True
        except Exception:  # Metadata collection must never fail the user's task.
            return False

    def _claude_cached_usage(self, account_key):
        value = self.kv.get("native-claude-usage/" + account_key) or {}
        observations = list((value.get("windows") or {}).values())
        if not observations:
            raise UsageUnavailable("unavailable")
        windows = [item["window"] for item in observations]
        observed_at = min(item["observed_at"] for item in observations)
        stale = self.clock() - observed_at >= MINIMUM["claude_code"] or any(datetime.fromisoformat(w["resets_at"]).timestamp() <= self.clock() for w in windows)
        return windows, observed_at, stale

    async def collect(self, runtime, expected_account_key, executable=None):
        async with self._lock:
            info = await self.identify(runtime, executable)
            if (
                not info.get("account_key")
                or info["account_key"] != expected_account_key
            ):
                return {
                    **info,
                    "windows": [],
                    "stale": True,
                    "error_code": "account_changed",
                }
            key = "account-usage/" + runtime + "/" + info["account_key"]
            cached = dict(self.kv.get(key) or {})
            now = self.clock()
            if now < cached.get("next_attempt_at", 0):
                return {**info, **cached}
            # Persist the gate before touching the usage endpoint; survives process restarts.
            cached["next_attempt_at"] = now + MINIMUM[runtime]
            self.kv.set(key, cached)
            try:
                if runtime == "codex":
                    async with self.codex_factory(executable) as request:
                        account = (
                            await request("account/read", {"refreshToken": False})
                        ).get("account") or {}
                        current = identity(
                            runtime, account.get("email"), account.get("planType")
                        )
                        if current["account_key"] != expected_account_key:
                            raise UsageUnavailable("account_changed")
                        windows = codex_windows(
                            await request("account/rateLimits/read")
                        )
                else:
                    windows, observed_at, native_stale = self._claude_cached_usage(expected_account_key)
                cached = {
                    "windows": windows,
                    "fetched_at": datetime.fromtimestamp(observed_at if runtime == "claude_code" else now, UTC).isoformat(),
                    "stale": native_stale if runtime == "claude_code" else False,
                    "error_code": None,
                    "failures": 0,
                    "next_attempt_at": now + MINIMUM[runtime],
                }
            except Exception as exc:  # noqa: BLE001 -- sanitized failure, never propagate upstream bodies
                failures = cached.get("failures", 0) + 1
                cached.update(
                    stale=True,
                    failures=failures,
                    error_code=exc.code
                    if isinstance(exc, UsageUnavailable)
                    else "unavailable",
                    next_attempt_at=now + (MINIMUM[runtime] if runtime == "claude_code" else (300, 900, 1800)[min(failures - 1, 2)]),
                )
            self.kv.set(key, cached)
            return {**info, **cached, "windows": cached.get("windows", [])}


class AccountUsageRpc:
    def __init__(self, supervisor, host):
        self.supervisor, self.host, self.collector = supervisor, host, None

    async def dispatch(self, method, params):
        runtime_id = params.get("runtimeId")
        entry = self.supervisor.entry_or_none(runtime_id)
        if entry is None or entry.runtime_type not in {"codex", "claude"}:
            return {
                "runtime": "codex",
                "errorCode": "unsupported_auth",
                "accountKey": None,
            }
        values = entry.requested_values or {}
        runtime = "claude_code" if entry.runtime_type == "claude" else "codex"
        if (
            values.get("modelGateway")
            or values.get("environment")
            or (values.get("codexHome") and (not fork_enabled()
                or Path(values["codexHome"]).resolve() != Path(os.environ["CODEX_HOME"]).resolve()))
        ):
            # Custom credential environments need explicit profile support; never read a different account.
            return {
                "runtime": runtime,
                "errorCode": "unsupported_auth",
                "accountKey": None,
            }
        if self.collector is None:
            self.collector = LocalAccountUsage(getattr(self.host, "account_usage_kv", self.host.runtime_kv))
        executable = values.get(
            "codexExecutablePath" if runtime == "codex" else "executablePath"
        )
        if method == "accountUsage.identify":
            value = await self.collector.identify(runtime, executable)
        else:
            value = await self.collector.collect(
                runtime, params.get("accountKey"), executable
            )
        fields = {
            "runtime": "runtime",
            "account_key": "accountKey",
            "plan_type": "planType",
            "fetched_at": "fetchedAt",
            "next_attempt_at": "nextAttemptAt",
            "error_code": "errorCode",
            "stale": "stale",
            "windows": "windows",
        }
        result = {
            wire: value[local] for local, wire in fields.items() if local in value
        }
        if "windows" in result:
            fields = {
                "kind": "kind",
                "model_scope": "modelScope",
                "used_percent": "usedPercent",
                "remaining_percent": "remainingPercent",
                "resets_at": "resetsAt",
                "window_duration_mins": "windowDurationMins",
            }
            result["windows"] = [
                {
                    wire: window[local]
                    for local, wire in fields.items()
                    if local in window
                }
                for window in result["windows"]
            ]
        return result
