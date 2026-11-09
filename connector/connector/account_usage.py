"""Read-only local account usage. No raw credentials or upstream bodies leave this module."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import sys
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import httpx

from connector.core.fork_profile import fork_enabled
from connector.native_cli import claude_command, codex_command

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


def claude_windows(payload):
    result = []
    if isinstance(payload.get("limits"), list):
        for value in payload["limits"]:
            kind = {
                "session": "five_hour",
                "weekly_all": "seven_day",
                "weekly_scoped": "weekly_scoped",
            }.get(value.get("kind"))
            if kind is None:
                continue
            scope = None
            if kind == "weekly_scoped":
                raw = str(value.get("model_scope") or value.get("model") or "").lower()
                scope = next(
                    (name for name in ("opus", "sonnet", "haiku") if name in raw),
                    "unknown",
                )
            result.append(
                window(
                    kind,
                    value.get("percent"),
                    value.get("resets_at"),
                    300 if kind == "five_hour" else 10080,
                    scope,
                )
            )
    else:
        for name, kind, minutes in (
            ("five_hour", "five_hour", 300),
            ("seven_day", "seven_day", 10080),
        ):
            value = payload.get(name)
            if isinstance(value, dict):
                result.append(
                    window(
                        kind, value.get("utilization"), value.get("resets_at"), minutes
                    )
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
        if method not in {"initialize", "account/read", "account/rateLimits/read"}:
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


async def local_output(*args):
    child = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        output, _ = await asyncio.wait_for(child.communicate(), 5)
        return output, child.returncode
    finally:
        if child.returncode is None:
            child.kill()
            await child.wait()


class LocalAccountUsage:
    def __init__(
        self,
        kv,
        *,
        home=None,
        platform=None,
        clock=time.time,
        codex_factory=codex_process,
        http_factory=httpx.AsyncClient,
    ):
        self.kv, self.home = kv, Path(home) if home is not None else Path.home()
        self.platform, self.clock = platform or sys.platform, clock
        self.codex_factory, self.http_factory = codex_factory, http_factory
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

    async def _claude_token(self):
        if self.platform == "darwin":
            service = "Claude Code-credentials"
            directory = os.environ.get("CLAUDE_SECURESTORAGE_CONFIG_DIR", os.environ.get("CLAUDE_CONFIG_DIR", ""))
            if directory:
                service += "-" + hashlib.sha256(directory.encode()).hexdigest()[:8]
            raw, code = await local_output(
                "security",
                "find-generic-password",
                "-s",
                service,
                "-w",
            )
            if code:
                raise UsageUnavailable("account_unavailable")
            credentials = json.loads(raw)
        else:
            config = Path(os.environ.get("CLAUDE_CONFIG_DIR", self.home / ".claude"))
            credentials = json.loads((config / ".credentials.json").read_text())
        token = (credentials.get("claudeAiOauth") or {}).get("accessToken")
        if not isinstance(token, str) or not token:
            raise UsageUnavailable("unsupported_auth")
        return token

    async def _claude_usage(self, executable):
        command = await asyncio.to_thread(claude_command, ["--version"], executable)
        output, code = await local_output(*command)
        match = re.search(rb"\b(\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?)\b", output)
        if code or not match:
            raise UsageUnavailable("unavailable")
        token = await self._claude_token()
        try:
            async with self.http_factory(timeout=20, follow_redirects=False) as client:
                response = await client.get(
                    "https://api.anthropic.com/api/oauth/usage",
                    headers={
                        "Authorization": "Bearer " + token,
                        "anthropic-beta": "oauth-2025-04-20",
                        "User-Agent": "claude-code/" + match.group(1).decode(),
                    },
                )
                if response.status_code != 200:
                    raise UsageUnavailable(
                        "rate_limited" if response.status_code == 429 else "unavailable"
                    )
                return claude_windows(response.json())
        finally:
            token = ""

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
                    windows = await self._claude_usage(executable)
                cached = {
                    "windows": windows,
                    "fetched_at": datetime.fromtimestamp(now, UTC).isoformat(),
                    "stale": False,
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
                    next_attempt_at=now + (300, 900, 1800)[min(failures - 1, 2)],
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
            self.collector = LocalAccountUsage(self.host.runtime_kv)
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
