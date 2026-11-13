import asyncio
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from test_account_usage import KEY, seed
from test_connector_deletion import api as api_fixture
from test_connector_deletion import create_device

from agent_server.core.account_usage import (
    ClaudeUsageEvent,
    normalize_probe_state,
    probe_failure,
)
from agent_server.infra.db import schema as db
from agent_server.services.account_usage import AccountUsageService

api = api_fixture
NOW = 2000000000.0


def window(kind="five_hour", used=71, reset=NOW + 3600):
    return {"kind": kind, "usedPercent": used, "remainingPercent": 100 - used,
            "resetsAt": datetime.fromtimestamp(reset, UTC).isoformat(), "windowDurationMins": 300 if kind == "five_hour" else 10080}


async def event(store, device, received, windows, event_id="a" * 32):
    await store.record_claude_usage_event(device, ClaudeUsageEvent.model_validate({"runtimeId": "claude", "accountKey": KEY,
        "eventId": event_id, "windows": windows}), received_at=received)


def setup(api):
    client, headers = api
    device = create_device(client, headers)
    store = client.app.state.store
    asyncio.run(seed(store, device, "claude"))
    now = [NOW]
    rpc = type("Rpc", (), {"is_online": AsyncMock(return_value=True), "request": AsyncMock()})()
    rpc.request.return_value = {"runtime": "claude_code", "accountKey": KEY, "windows": [window(), window("seven_day", 28)]}
    service = AccountUsageService(store, rpc, clock=lambda: now[0]); service.probe_connector_id = device
    client.app.state.account_usage_service = service
    owner = asyncio.run(store.get_connector(device)).userId
    return client, headers, device, store, owner, now, rpc, service


def test_window_merge_server_receipts_and_no_expiry(api):
    _, _, device, store, owner, now, _rpc, service = setup(api)
    async def check():
        # Probe supplies both windows. Machine timestamps are not accepted as observation times.
        await service.manual_refresh(owner)
        now[0] += 30
        spoof = window(used=80); spoof.update(source="probe", receivedAt="2099-01-01T00:00:00Z")
        await event(store, device, now[0], [spoof])
        result = (await service.snapshot(owner)).snapshots[0]
        assert [(w.kind, w.source, w.used_percent) for w in result.windows] == [("five_hour", "event", 80), ("seven_day", "probe", 28)]
        assert result.windows[0].received_at.timestamp() == now[0]
        assert result.windows[1].received_at.timestamp() == NOW
        now[0] += 365 * 86400
        aged = (await service.snapshot(owner)).snapshots[0]
        assert len(aged.windows) == 2 and aged.windows[0].used_percent == 80
        assert aged.windows[0].age_seconds == 365 * 86400
        assert not aged.stale
        async with store.engine.connect() as conn:
            raw = (await conn.execute(select(db.account_usage_snapshots.c.claude_windows_json).where(db.account_usage_snapshots.c.account_key == KEY))).scalar_one()
        assert set(json.loads(raw)["five_hour"]) == {"event", "probe"}
    asyncio.run(check())


def test_manual_single_flight_across_service_workers_and_five_minute_success_gate(api):
    _, _, _, store, owner, now, rpc, service = setup(api)
    other = AccountUsageService(store, rpc, clock=lambda: now[0]); other.probe_connector_id = service.probe_connector_id
    started, finish = asyncio.Event(), asyncio.Event()
    async def request(*args, **kwargs):
        started.set(); await finish.wait()
        return {"runtime": "claude_code", "accountKey": KEY, "windows": [window()]}
    rpc.request.side_effect = request
    async def check():
        first = asyncio.create_task(service.manual_refresh(owner))
        await started.wait()
        followers = [asyncio.create_task(other.manual_refresh(owner)) for _ in range(5)]
        await asyncio.sleep(.05)
        assert rpc.request.await_count == 1
        finish.set(); await asyncio.gather(first, *followers)
        now[0] += 299
        await service.manual_refresh(owner)
        assert rpc.request.await_count == 1
        now[0] += 1
        await service.manual_refresh(owner)
        assert rpc.request.await_count == 2
    asyncio.run(check())


def test_failure_and_offline_preserve_all_window_bytes(api):
    _, _, device, store, owner, now, rpc, service = setup(api)
    async def raw():
        return (await store.account_usage_rows(owner))[0]["claude_windows_json"]
    async def check():
        await event(store, device, now[0], [window(), window("seven_day", 28)])
        before = await raw()
        rpc.request.return_value = {"runtime": "claude_code", "errorCode": "rate_limited", "retryAfterSeconds": 600}
        await service.manual_refresh(owner)
        assert await raw() == before
        response = await service.snapshot(owner)
        assert response.refresh.status == "retry" and response.refresh.next_allowed_at.timestamp() == NOW + 600
        now[0] += 600
        rpc.is_online.return_value = False
        await service.manual_refresh(owner)
        assert await raw() == before
        assert (await service.snapshot(owner)).refresh.status == "offline"
        assert rpc.request.await_count == 1
    asyncio.run(check())


def test_only_manual_post_probes_and_other_users_cannot_trigger(api):
    client, headers, device, _store, owner, _now, rpc, service = setup(api)
    assert client.get("/account-usage", headers=headers).status_code == 200
    assert rpc.request.await_count == 0
    asyncio.run(service.refresh(owner))
    assert rpc.request.await_count == 0
    asyncio.run(service.manual_refresh("different-user"))
    assert rpc.request.await_count == 0
    assert client.post("/account-usage/refresh", headers=headers).status_code == 200
    assert rpc.request.await_count == 1
    assert rpc.request.await_args.args[0] == device
    assert rpc.request.await_args.args[1] == "accountUsage.probe"


def test_three_429_circuit_success_reset_and_next_day():
    state = {}
    first = probe_failure(state, NOW, "rate_limited")
    assert first["next_allowed_at"] == NOW + 600
    second = probe_failure(first, NOW + 600, "rate_limited")
    assert second["next_allowed_at"] == NOW + 600 + 1200
    third = probe_failure(second, NOW + 1800, "rate_limited")
    assert third["status"] == "circuit"
    assert datetime.fromtimestamp(third["circuit_until"], UTC).hour == 0
    recovered = normalize_probe_state(third, third["circuit_until"])
    assert recovered["interval"] == 300 and recovered["consecutive_429"] == 0 and recovered["status"] == "idle"


def test_429_retry_after_uses_server_clock():
    result = probe_failure({}, NOW, "rate_limited", retry_after_seconds=42)
    assert result["next_allowed_at"] == NOW + 42
    date = datetime.fromtimestamp(NOW + 999, UTC)
    assert probe_failure({}, NOW, "rate_limited", retry_after_at=date)["next_allowed_at"] == NOW + 999


def test_success_clears_429_counter_and_partial_probe_keeps_other_window(api):
    _, _, device, store, owner, now, rpc, service = setup(api)
    async def check():
        await event(store, device, now[0], [window("seven_day", 50)])
        rpc.request.return_value = {"runtime": "claude_code", "errorCode": "rate_limited", "retryAfterSeconds": 0}
        await service.manual_refresh(owner); await service.manual_refresh(owner)
        rpc.request.return_value = {"runtime": "claude_code", "accountKey": KEY, "windows": [window()]}
        now[0] += 1
        await service.manual_refresh(owner)
        state = await store.claude_probe_state(now[0])
        assert state["consecutive_429"] == 0 and state["interval"] == 300
        data = (await service.snapshot(owner)).snapshots[0].windows
        assert [(w.kind, w.source) for w in data] == [("five_hour", "probe"), ("seven_day", "event")]
    asyncio.run(check())


def test_event_notification_ingestion_uses_server_receipt_and_rejects_extra_fields(api):
    import time
    from types import SimpleNamespace

    from agent_server.services.connector_notifications import (
        ConnectorNotificationService,
        NotificationValidationError,
    )
    _, _, device, store, owner, _, _, service = setup(api)
    service.clock = time.time
    notifications = ConnectorNotificationService(store, SimpleNamespace(apply=AsyncMock(return_value=False)))
    params = {"runtimeId": "claude", "accountKey": KEY, "eventId": "b" * 32, "windows": [window()]}
    async def check():
        before = time.time()
        await notifications.apply(connector_id=device, method="accountUsage.event", params=params)
        receipt = (await service.snapshot(owner)).snapshots[0].windows[0].received_at.timestamp()
        assert before <= receipt <= time.time()
        with pytest.raises(NotificationValidationError, match="invalid usage metadata"):
            await notifications.apply(connector_id=device, method="accountUsage.event", params={**params, "accessToken": "synthetic-secret"})
    asyncio.run(check())


def test_older_server_receipt_cannot_overwrite_newer_event(api):
    _, _, device, store, owner, _, _, service = setup(api)
    async def check():
        await event(store, device, NOW, [window(used=80)])
        await event(store, device, NOW - 1, [window(used=1)], "b" * 32)
        assert (await service.snapshot(owner)).snapshots[0].windows[0].used_percent == 80
    asyncio.run(check())


def test_timeout_lease_and_failed_rpc_never_mutate_data(api):
    _, _, device, store, owner, now, rpc, service = setup(api)
    async def check():
        await event(store, device, NOW, [window()])
        before = (await store.account_usage_rows(owner))[0]["claude_windows_json"]
        rpc.request.side_effect = TimeoutError("synthetic secret details must not escape")
        await service.manual_refresh(owner)
        assert (await store.account_usage_rows(owner))[0]["claude_windows_json"] == before
        assert (await service.snapshot(owner)).refresh.error_code == "timeout"
        now[0] += 600
        token, _ = await store.claim_claude_probe(now[0])
        assert token
        now[0] += 91
        state = await store.claude_probe_state(now[0])
        assert state["status"] == "retry" and state["error_code"] == "timeout"
        assert (await store.account_usage_rows(owner))[0]["claude_windows_json"] == before
    asyncio.run(check())


def test_legacy_device_clock_is_not_used_for_age(api):
    from sqlalchemy import update
    _, _, device, store, owner, _, _, service = setup(api)
    async def check():
        await event(store, device, NOW, [window("five_hour")])
        legacy = {"runtime": "claude_code", "accountKey": KEY, "windows": [window("seven_day", 28)],
                  "fetchedAt": "2099-01-01T00:00:00Z", "stale": False}
        async with store.engine.begin() as conn:
            await conn.execute(update(db.account_usage_snapshots).where(db.account_usage_snapshots.c.account_key == KEY).values(snapshot_json=json.dumps(legacy)))
        windows = (await service.snapshot(owner)).snapshots[0].windows
        assert windows[0].source == "event" and windows[0].received_at.timestamp() == NOW
        assert windows[1].used_percent == 28 and windows[1].received_at is None and windows[1].age_seconds is None
    asyncio.run(check())


def test_unrepresentable_retry_after_uses_backoff_without_poisoning_control():
    result = probe_failure({}, NOW, "rate_limited", retry_after_seconds=1e300)
    assert result["next_allowed_at"] == NOW + 600
    assert result["consecutive_429"] == 1


def test_quota_recheck_needs_fresh_receipts_for_each_window_without_probing(api):
    from sqlalchemy import update
    from test_connector_deletion import create_project

    client, headers, device, store, _owner, _now, rpc, _service = setup(api)
    project = create_project(client, headers, device, "manual-usage-quota")
    async def prepare():
        session = await store.create_session(connector_id=device, project_id=project, runtime="claude",
            external_session_id="quota-native", title="Quota", cwd=None)
        async with store.engine.begin() as conn:
            await conn.execute(update(db.sessions).where(db.sessions.c.id == session.id).values(status="limited", quota_json=json.dumps({
                "state": "limited", "accountKey": KEY, "windows": [], "resetsAt": None,
                "externalSessionId": "quota-native", "interruptedAt": datetime.fromtimestamp(NOW - 10, UTC).isoformat()})))
        await event(store, device, NOW - 100, [window()])
        await event(store, device, NOW, [window("seven_day", 28)], "b" * 32)
        return session.id
    sid = asyncio.run(prepare())
    response = client.post(f"/sessions/{sid}/quota/recheck", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["quotaLimit"]["state"] == "limited"
    asyncio.run(event(store, device, NOW, [window()], "c" * 32))
    response = client.post(f"/sessions/{sid}/quota/recheck", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["quotaLimit"]["state"] == "ready"
    assert rpc.request.await_count == 0
