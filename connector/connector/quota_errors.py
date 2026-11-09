"""Conservative terminal usage-limit classification, never generic transport 429."""

from collections.abc import Mapping


def is_usage_limit(runtime, error):
    if runtime not in {"codex", "claude"} or not isinstance(error, Mapping):
        return False
    code = str(error.get("code") or error.get("type") or "").casefold().replace("_", "")
    raw = error.get("raw") if isinstance(error.get("raw"), Mapping) else {}
    info = str(raw.get("codexErrorInfo") or "").casefold().replace("_", "")
    if code in {
        "usagelimitexceeded",
        "usagelimitreached",
        "usagelimiterror",
        "insufficientquota",
    } or info in {"usagelimitexceeded", "usagelimitreached"}:
        return True
    message = str(error.get("message") or "")[:8192].casefold()
    return any(
        value in message
        for value in (
            "you've hit your limit",
            "you have hit your limit",
            "you’ve hit your limit",
            "you've hit your usage limit",
            "you have reached your usage limit",
            "usage limit has been reached",
            "usage limit reached",
            "usage limit exceeded",
            "weekly limit reached",
            "5-hour limit reached",
            "weekly usage limit",
        )
    )
