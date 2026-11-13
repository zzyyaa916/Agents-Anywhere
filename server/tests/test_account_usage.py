import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from agent_server.core.account_usage import UsageCollection
from agent_server.core.utc import utc_now
from agent_server.infra.db import schema as db
from agent_server.services.account_usage import AccountUsageService
from sqlalchemy import insert
from test_connector_deletion import api as api_fixture
from test_connector_deletion import create_device

api = api_fixture
KEY = "a" * 64


async def seed(store, device, runtime="codex"):
    now = utc_now()
    async with store._engine.begin() as conn:
        await conn.execute(
            insert(db.connector_runtime_types).values(
                connector_id=device,
                runtime_type=runtime,
                implementation_type=runtime,
                display_name=runtime,
                discovery_json="{}",
                defaults_json="{}",
                capabilities_json="{}",
                metadata_json="{}",
                instance_policy="single",
                last_discovered_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        await conn.execute(
            insert(db.device_runtimes).values(
                connector_id=device,
                runtime_id=runtime,
                runtime_type=runtime,
                name=runtime,
                name_key=runtime,
                config_json="{}",
                created_at=now,
                updated_at=now,
            )
        )


def payload(runtime, now, stale=False):
    return {
        "runtime": runtime,
        "accountKey": KEY,
        "windows": [
            {
                "kind": "five_hour",
                "usedPercent": 90,
                "remainingPercent": 10,
                "resetsAt": datetime.fromtimestamp(now + 300, UTC).isoformat(),
                "windowDurationMins": 300,
            }
        ],
        "fetchedAt": datetime.fromtimestamp(now, UTC).isoformat(),
        "stale": stale,
    }


@pytest.mark.parametrize("runtime,minimum", [("codex", 60), ("claude", 300)])
def test_three_devices_dedupe_concurrent_refresh_cache_and_backoff(
    api, runtime, minimum
):
    client, headers = api
    devices = [create_device(client, headers, f"Device-{i}") for i in range(3)]
    store = client.app.state.store
    for device in devices:
        asyncio.run(seed(store, device, runtime))
    now = [2000000000.0]
    source = "claude_code" if runtime == "claude" else runtime
    calls = []
    failure = [False]

    async def request(device, method, params, **kwargs):
        calls.append(method)
        if method.endswith("identify"):
            return {"runtime": source, "accountKey": KEY}
        if failure[0]:
            raise ConnectionError("do not log raw response")
        return payload(source, now[0])

    rpc = type(
        "Rpc",
        (),
        {"is_online": AsyncMock(return_value=True), "request": staticmethod(request)},
    )()
    service = AccountUsageService(store, rpc, clock=lambda: now[0])
    client.app.state.account_usage_service = service

    async def check():
        await asyncio.gather(service.refresh(), service.refresh(), service.refresh())
        if runtime == "claude":
            assert calls == []  # Pure event push; no background identity or usage polling.
            return
        assert calls.count("accountUsage.collect") == 1
        owner = (await store.get_connector(devices[0])).userId
        result = await service.snapshot(owner)
        assert len(result.snapshots) == 1 and len(result.snapshots[0].bindings) == 3
        assert result.snapshots[0].windows[0].remaining_percent == 10
        before = len(calls)
        await service.refresh(owner)
        assert len(calls) == before
        failure[0] = True
        for advance, delay in [(minimum, 300), (300, 900), (900, 1800)]:
            now[0] += advance
            await service.refresh(owner)
            snapshot = (await service.snapshot(owner)).snapshots[0]
            assert snapshot.stale and snapshot.windows[0].remaining_percent == 10
            assert snapshot.next_attempt_at == now[0] + delay
        assert not (await service.snapshot("other-user")).snapshots

    asyncio.run(check())
    before = len(calls)
    response = client.get("/account-usage", headers=headers)
    assert response.status_code == 200 and len(calls) == before
    assert client.get("/account-usage").status_code == 401


def test_response_forbids_credentials_and_unknown_payloads():
    from pydantic import ValidationError

    body = payload("codex", 2000000000)
    body["accessToken"] = "synthetic-token"
    with pytest.raises(ValidationError):
        UsageCollection.model_validate(body)
    body.pop("accessToken")
    body["windows"][0]["remainingPercent"] = 50
    with pytest.raises(ValidationError):
        UsageCollection.model_validate(body)
