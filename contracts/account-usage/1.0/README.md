# Account usage 1.0

P2 uses `GET /api/v2/account-usage` (cache only), `POST /api/v2/account-usage/refresh` (same minimum interval and backoff).
Server-to-Connector RPC: `accountUsage.identify({runtimeId})` returns stable SHA-256 accountKey, runtime and planType. `accountUsage.collect({runtimeId,accountKey})` returns normalized windows, fetchedAt, stale, nextAttemptAt and a finite errorCode. JSON fields follow camelCase; provider `claude` maps to usage source `claude_code`; dsh is reserved only.

Model source: Server `core/account_usage.py`; extra fields forbidden. Generate the shared response schema from UsageResponse.model_json_schema(by_alias=True). No credentials, raw upstream responses, unmasked account emails or error messages are allowed in either direction, logs or snapshots. Account labels are hash prefixes. UI only reads Server cache.

Identity discovery is not quota collection. Server persists a 5 minute discovery gate per source, and an atomic account-wide quota gate per (user,runtime,accountKey). One selected online Connector spends one attempt; uncertain network outcomes never fan out to another device. Quota collection minima: Codex 60 seconds, Claude 300 seconds; failures back off 300→900→1800 seconds, also persisted locally. Late results are fenced by attempt identity. Account changes must be checked locally before quota calls; unavailable identity never becomes a token hash.

Codex uses a short-lived stdio app-server: initialize, initialized, account/read with refreshToken:false, account/rateLimits/read; no login/logout/turn requests. Windows are classified by duration, never position. Verified against [official app-server docs](https://developers.openai.com/codex/app-server).

Claude uses local OAuth credentials (JSON on Linux/Windows; the Claude Code Keychain item on macOS), the specified GET endpoint, beta header and local CLI version User-Agent. `limits` has priority over legacy five_hour/seven_day. This is an undocumented upstream interface: unknown structures or unavailable identity degrade to unavailable/stale. No real account probes are part of development tests.

后续用户修订：新 Connector 的 Claude 来源改为正常任务的原生 SDK 限额事件缓存，停用私有接口及 OAuth 凭据读取，wire schema 不变；缺字段或过期仍降级。详见 [原生来源说明](../../../docs/fork/claude-native-usage.md)。上段 Claude 私有接口描述仅适用于旧实现。
