from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from connector.quota_errors import is_usage_limit

ClaudeTerminalStatus = Literal["completed", "failed", "interrupted"]
INTERRUPTED_TERMINAL_REASONS = frozenset({"aborted_streaming", "aborted_tools"})


@dataclass(frozen=True, slots=True)
class ClaudeTerminalEvent:
    status: ClaudeTerminalStatus
    reason: str | None = None
    error_code: str | None = None
    error_message: str | None = None


def terminal_event_from_message(message: Any) -> ClaudeTerminalEvent | None:
    """Normalize a Claude SDK ResultMessage into one runtime terminal event."""

    # Claude versions may put the quota error in an assistant error block or
    # in an error result's result text. Plain assistant prose is never a signal.
    native_error = _string_attr(message, "error")
    if native_error or _bool_attr(message, "is_error", "isError"):
        content = _attr(message, "content")
        text = _string_attr(message, "result") or ""
        if isinstance(content, Sequence) and not isinstance(content, str | bytes):
            text += " ".join(_string_attr(block, "text") or "" for block in content)
        text += " " + (message_error_text(message) or "")
        if is_usage_limit("claude", {"code": native_error, "message": text}):
            return ClaudeTerminalEvent(status="failed", error_code="usage_limit_reached", error_message="Claude usage limit reached")
    if not is_result_message(message):
        return None
    terminal_reason = _string_attr(message, "terminal_reason", "terminalReason")
    if _bool_attr(message, "is_error", "isError"):
        return ClaudeTerminalEvent(
            status="failed",
            reason=terminal_reason,
            error_code="claude_result_error",
            error_message=message_error_text(message)
            or "Claude turn completed with an error",
        )
    if terminal_reason in INTERRUPTED_TERMINAL_REASONS:
        return ClaudeTerminalEvent(
            status="interrupted",
            reason=terminal_reason,
        )
    return ClaudeTerminalEvent(
        status="completed",
        reason=terminal_reason,
    )


def failed_terminal_event(
    *,
    code: str,
    message: str,
    reason: str | None = None,
) -> ClaudeTerminalEvent:
    return ClaudeTerminalEvent(
        status="failed",
        reason=reason,
        error_code=code,
        error_message=message,
    )


def interrupted_terminal_event(reason: str | None = None) -> ClaudeTerminalEvent:
    return ClaudeTerminalEvent(status="interrupted", reason=reason)


def is_result_message(message: Any) -> bool:
    if message.__class__.__name__ == "ResultMessage":
        return True
    raw_type = _attr(message, "type")
    subtype = _attr(message, "subtype")
    return raw_type == "result" or (isinstance(subtype, str) and "result" in subtype)


def message_error_text(message: Any) -> str | None:
    errors = _attr(message, "errors")
    if isinstance(errors, Sequence) and not isinstance(errors, str | bytes) and errors:
        return "; ".join(str(error) for error in errors)
    return _string_attr(message, "error", "terminal_reason", "terminalReason")


def _bool_attr(value: Any, *names: str) -> bool:
    return any(_attr(value, name) is True for name in names)


def _string_attr(value: Any, *names: str) -> str | None:
    for name in names:
        candidate = _attr(value, name)
        if isinstance(candidate, str) and candidate:
            return candidate
    return None


def _attr(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def native_usage_from_message(message: Any) -> list[tuple[str, float | None, int | None]]:
    """Read each native window once; unified windows take precedence over the outer fallback."""
    if message.__class__.__name__ != "RateLimitEvent" and _attr(message, "type") != "rate_limit_event":
        return []
    info = _attr(message, "rate_limit_info") or _attr(message, "rate_limitInfo")
    if info is None:
        return []
    raw = _attr(info, "raw")
    unified = _attr(raw, "unifiedWindows") or _attr(info, "unifiedWindows")
    outer_kind = _string_attr(info, "rate_limit_type", "rateLimitType")
    windows = []
    for kind in ("five_hour", "seven_day", "seven_day_opus", "seven_day_sonnet"):
        window = _attr(unified, kind) if kind in {"five_hour", "seven_day"} else None
        if not isinstance(window, Mapping):
            window = info if kind == outer_kind else None
        if window is None:
            continue
        utilization = _attr(window, "utilization")
        resets_at = _attr(window, "resets_at") or _attr(window, "resetsAt")
        if isinstance(utilization, bool) or not isinstance(utilization, (int, float)) or not math.isfinite(utilization) or not 0 <= utilization <= 1:
            utilization = None
        if isinstance(resets_at, bool) or not isinstance(resets_at, int):
            resets_at = None
        windows.append((kind, utilization, resets_at))
    return windows
