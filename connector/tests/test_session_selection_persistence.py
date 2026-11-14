import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from connector.runtime_protocol import (
    RuntimeCapability,
    RuntimeCapabilitySet,
    RuntimeIdentity,
    RuntimeInstance,
    RuntimeInstanceHost,
    RuntimeInstanceSpec,
    RuntimeModelCatalog,
    RuntimeModelItem,
    RuntimeOperationResult,
    RuntimeReasoningItem,
    SessionState,
)
from connector.runtime_protocol.session_selections import SessionSelectionStore


class DiskHost:
    def __init__(self, directory):
        self.directory = directory
        self.session_state_update = AsyncMock()
        self.publish_runtime_notifications = AsyncMock()

    async def sync_state_read(self, key):
        path = self.directory / (key.replace('/', '_') + '.json')
        return json.loads(path.read_text()) if path.exists() else None

    async def sync_state_write(self, key, value):
        (self.directory / (key.replace('/', '_') + '.json')).write_text(json.dumps(value))


def _model(model_id):
    return RuntimeModelItem(
        id=model_id,
        title=model_id,
        selection_id=f'{model_id}/model',
        reasoning_items=tuple(
            RuntimeReasoningItem(id=level, title=level, selection_id=f'{model_id}/{level}')
            for level in ('low', 'medium', 'high')
        ),
    )


DEFAULT_MODELS = tuple(
    _model(model_id)
    for model_id in (
        'fable-5.2', 'fable', 'deepseek', 'first', 'second',
        'model-a', 'model-b', 'rejected-model', 'old-default',
    )
)


def bound(directory, kind, runtime_id='rti_one'):
    base = DiskHost(directory)
    instance = RuntimeInstanceSpec(runtime_id, kind, 'Test')
    scoped = RuntimeInstanceHost(base, instance)
    store = SessionSelectionStore(kind, scoped)
    native = SimpleNamespace(
        identity=RuntimeIdentity(runtime=kind, runtime_version='test'),
        get_runtime_capabilities=AsyncMock(return_value=RuntimeCapabilitySet(runtime=kind, revision=1, capabilities=(RuntimeCapability(capability_id='catalog.model', scope='runtime', runtime=kind),))),
        list_model_catalog=AsyncMock(return_value=RuntimeModelCatalog(runtime=kind, revision=1, models=DEFAULT_MODELS)),
        create_and_start_session=AsyncMock(return_value=RuntimeOperationResult(ok=True)),
        start_turn=AsyncMock(return_value=RuntimeOperationResult(ok=True)),
        update_session_selections=AsyncMock(return_value=RuntimeOperationResult(ok=True)),
        get_session_state=AsyncMock(return_value=SessionState(session_id='s', external_session_id='n', runtime=kind, status='idle', selections={})),
    )
    return RuntimeInstance(instance, native, store), replace(scoped, selection_store=store), base


@pytest.mark.parametrize('kind', ['claude', 'codex', 'dsh'])
def test_model_effort_survives_restart_and_changes_only_on_success(kind, tmp_path):
    async def check():
        runtime, _, _ = bound(tmp_path, kind)
        choice = {'model': 'fable-5.2/low', 'permission': 'ask'}
        await runtime.create_and_start_session('s', 'start', selections=choice)
        runtime, host, base = bound(tmp_path, kind)  # Fresh objects, same durable storage.
        state = await runtime.get_session_state('s', 'n')
        assert state.selections == choice
        await runtime.start_turn('s', 'n', 'continue')
        assert runtime.native_runtime.start_turn.await_args.kwargs['selections'] == choice
        await host.session_state_update('s', kind, selections={})
        assert base.session_state_update.await_args.kwargs['selections'] == choice
        # Native observations cannot overwrite the saved user choice.
        await host.session_state_update('s', kind, selections={'model': 'native-default'})
        assert base.session_state_update.await_args.kwargs['selections']['model'] == choice['model']
        await runtime.start_turn('s', 'n', 'again')
        assert runtime.native_runtime.start_turn.await_args.kwargs['selections']['model'] == choice['model']
        # Forwarded old Server state is not an explicit user switch.
        await runtime.start_turn('s', 'n', 'stale snapshot', selections={'model': 'old-default', 'permission': 'old-permission'})
        assert runtime.native_runtime.start_turn.await_args.kwargs['selections'] == choice
        assert await runtime.selection_store.read('s') == choice
        # Partial permission changes keep both the model and effort.
        await runtime.update_session_selections('s', 'n', {'permission': 'accept-edits'})
        assert runtime.native_runtime.update_session_selections.await_args.args[2] == {**choice, 'permission': 'accept-edits'}
        runtime.native_runtime.update_session_selections.return_value = RuntimeOperationResult(ok=False)
        await runtime.update_session_selections('s', 'n', {'model': 'rejected-model'})
        assert (await runtime.selection_store.read('s'))['model'] == choice['model']
        before = runtime.native_runtime.start_turn.await_count
        blocked = await runtime.start_turn('s', 'n', 'must reselect after failure')
        assert not blocked.ok and runtime.native_runtime.start_turn.await_count == before
        runtime.native_runtime.update_session_selections.return_value = RuntimeOperationResult(ok=True)
        await runtime.update_session_selections('s', 'n', {'model': 'fable-5.2/high'})
        runtime, _, _ = bound(tmp_path, kind)
        await runtime.start_turn('s', 'n', 'after switch')
        assert runtime.native_runtime.start_turn.await_args.kwargs['selections'] == {'model': 'fable-5.2/high', 'permission': 'accept-edits'}
    asyncio.run(check())


def test_instance_and_session_isolation_and_default_is_rejected(tmp_path):
    async def check():
        a, _, _ = bound(tmp_path, 'claude')
        await a.create_and_start_session('s', 'start', selections={'model': 'fable/low'})
        b, _, _ = bound(tmp_path, 'claude', 'rti_other')
        assert (await b.get_session_state('s', 'n')).selections == {}
        outcome = await a.start_turn('other_session', 'other_native', 'hello')
        assert not outcome.ok and outcome.code == 'session_model_selection_required'
        a.native_runtime.start_turn.assert_not_awaited()
        outcome = await a.update_session_selections('s', 'n', {'model': None})
        assert not outcome.ok
        a.native_runtime.update_session_selections.assert_not_awaited()
        a, _, _ = bound(tmp_path, 'claude')
        assert (await a.get_session_state('s', 'n')).selections == {}
        outcome = await a.start_turn('s', 'n', 'no default')
        assert not outcome.ok

    asyncio.run(check())


def test_failed_creation_and_turn_do_not_pin_choices(tmp_path):
    async def check():
        a, _, _ = bound(tmp_path, 'codex')
        a.native_runtime.create_and_start_session.return_value = RuntimeOperationResult(ok=False)
        await a.create_and_start_session('s', 'hello', selections={'model': 'invalid'})
        assert await a.selection_store.read('s') == {}
        a.native_runtime.start_turn.return_value = RuntimeOperationResult(ok=False)
        await a.start_turn('s', 'n', 'hello', selections={'model': 'invalid'})
        assert await a.selection_store.read('s') == {}
    asyncio.run(check())


def test_dsh_batch_notifications_recover_missing_selections(tmp_path):
    async def check():
        a, host, base = bound(tmp_path, 'dsh')
        await a.create_and_start_session('s', 'start', selections={'model': 'deepseek/low'})
        notices = [{'method': 'session.state.updated', 'params': {'sessionId': 's', 'selections': {}}}]
        await host.publish_runtime_notifications('dsh', notices)
        assert base.publish_runtime_notifications.await_args.args[1][0]['params']['selections'] == {'model': 'deepseek/low'}
        assert notices[0]['params']['selections'] == {}  # Never mutate the plugin's payload.
    asyncio.run(check())


def test_real_runtime_storage_flush_and_reload(tmp_path, monkeypatch):
    from connector.server.runtime_host import ConnectorRuntimeHost
    from connector.server.sync_state import JsonSyncStateStore

    async def check():
        monkeypatch.setenv('AGENT_CONNECTOR_KV_FILE', str(tmp_path / 'legacy-kv.json'))
        path = tmp_path / 'state.json'
        spec = RuntimeInstanceSpec('rti_persist', 'claude', 'Test')
        base = ConnectorRuntimeHost('conn', AsyncMock(), AsyncMock(), JsonSyncStateStore(path))
        scoped = RuntimeInstanceHost(await base.prepare_runtime_host(spec.runtime_id), spec)
        await SessionSelectionStore('claude', scoped).remember('s', {'model': 'fable-5.2/low', 'permission': 'ask'})
        assert base.flush_runtime_storage()
        fresh = ConnectorRuntimeHost('conn', AsyncMock(), AsyncMock(), JsonSyncStateStore(path))
        scoped = RuntimeInstanceHost(await fresh.prepare_runtime_host(spec.runtime_id), spec)
        assert await SessionSelectionStore('claude', scoped).read('s') == {'model': 'fable-5.2/low', 'permission': 'ask'}
    asyncio.run(check())


def test_native_default_and_temporary_planning_do_not_change_pins(tmp_path):
    async def check():
        a, host, base = bound(tmp_path, 'claude')
        await a.create_and_start_session('s', 'hello', selections={'model': 'fable/low', 'permission': 'ask'})
        await host.session_state_update('s', 'claude', selections={'model': None, 'permission': 'plan'})
        assert base.session_state_update.await_args.kwargs['selections'] == {'model': 'fable/low', 'permission': 'plan'}
        assert await a.selection_store.read('s') == {'model': 'fable/low', 'permission': 'ask'}
        await host.session_state_update('s', 'claude', selections={'model': None, 'permission': None})
        assert base.session_state_update.await_args.kwargs['selections'] == {'model': 'fable/low', 'permission': 'ask'}
        a.native_runtime.get_session_state.return_value = None
        assert await a.get_session_state('s', 'n') is None
    asyncio.run(check())


def test_corrupt_pins_block_turn_instead_of_falling_back(tmp_path):
    async def check():
        runtime, _, _ = bound(tmp_path, 'codex')
        await runtime.selection_store.host.sync_state_write('codex/session-selections/s', {'selections': {'model': 123}})
        with pytest.raises(ValueError, match='invalid_saved_session_selections'):
            await runtime.start_turn('s', 'n', 'hello')
        runtime.native_runtime.start_turn.assert_not_awaited()
    asyncio.run(check())


@pytest.mark.parametrize('kind', ['claude', 'codex', 'dsh'])
def test_unknown_or_default_model_never_calls_native(kind, tmp_path):
    async def check():
        runtime, _, _ = bound(tmp_path, kind)
        for selection in [None, {}, {'model': None}, {'model': ''}]:
            result = await runtime.create_and_start_session('s', 'hello', selections=selection)
            assert not result.ok and result.code == 'session_model_selection_required'
        runtime.native_runtime.create_and_start_session.assert_not_awaited()
        result = await runtime.start_turn('legacy', 'n', 'hello', selections={'model': 'untrusted-native-default'})
        assert not result.ok
        runtime.native_runtime.start_turn.assert_not_awaited()
    asyncio.run(check())


def test_model_with_efforts_requires_explicit_effort(tmp_path):
    async def check():
        runtime, _, _ = bound(tmp_path, 'claude')
        runtime.native_runtime.list_model_catalog.return_value = RuntimeModelCatalog(runtime='claude', revision=1, models=(
            RuntimeModelItem(id='fable', title='Fable', selection_id='model-only', reasoning_items=(
                RuntimeReasoningItem(id='low', title='Low', selection_id='fable/low'),)),))
        result = await runtime.create_and_start_session('s', 'hello', selections={'model': 'model-only'})
        assert not result.ok
        runtime.native_runtime.create_and_start_session.assert_not_awaited()
        result = await runtime.create_and_start_session('s', 'hello', selections={'model': 'fable/low'})
        assert result.ok
    asyncio.run(check())


def test_multi_client_switches_are_serialized_and_report_next_turn(tmp_path):
    async def run():
        runtime, _, _ = bound(tmp_path, 'claude')
        first_entered, release = asyncio.Event(), asyncio.Event()
        calls = []
        async def update(sid, external, selections):
            calls.append(selections['model'])
            if len(calls) == 1:
                first_entered.set()
                await release.wait()
            return RuntimeOperationResult(ok=True, result={'selections': dict(selections)})
        runtime.native_runtime.update_session_selections.side_effect = update
        one = asyncio.create_task(runtime.update_session_selections('s', 'n', {'model':'first/low'}))
        await first_entered.wait()
        two = asyncio.create_task(runtime.update_session_selections('s', 'n', {'model':'second/high'}))
        await asyncio.sleep(0)
        assert calls == ['first/low']
        release.set()
        results = await asyncio.gather(one, two)
        assert calls == ['first/low', 'second/high']
        assert (await runtime.selection_store.read('s'))['model'] == 'second/high'
        assert all(r.result['selectionEffect'] == 'next_turn' for r in results)
    asyncio.run(run())


def test_batch_restoration_isolated_across_sessions_and_missing_fields(tmp_path):
    async def run():
        runtime, host, base = bound(tmp_path, 'dsh')
        await runtime.selection_store.remember('a', {'model':'model-a/low'})
        await runtime.selection_store.remember('b', {'model':'model-b/high'})
        notices = [
            {'method':'session.state.updated','params':{'sessionId':'a'}},
            {'method':'session.state.updated','params':{'sessionId':'b','selections':None}},
            {'method':'session.state.updated','params':{'sessionId':'unknown','selections':{}}},
        ]
        await host.publish_runtime_notifications('dsh', notices)
        sent = base.publish_runtime_notifications.await_args.args[1]
        assert sent[0]['params']['selections']['model'] == 'model-a/low'
        assert sent[1]['params']['selections']['model'] == 'model-b/high'
        assert sent[2]['params']['selections'] == {}
        assert 'selections' not in notices[0]['params']
        assert notices[1]['params']['selections'] is None
    asyncio.run(run())


def test_remember_never_clears_a_pinned_model(tmp_path):
    async def check():
        runtime, _, _ = bound(tmp_path, 'claude')
        await runtime.selection_store.remember('s', {'model': 'fable/low', 'permission': 'ask'})
        await runtime.selection_store.remember('s', {'model': None})
        assert await runtime.selection_store.read('s') == {'model': 'fable/low', 'permission': 'ask'}
    asyncio.run(check())


def test_missing_or_unknown_catalog_blocks_model_call(tmp_path):
    async def check():
        runtime, _, _ = bound(tmp_path, 'claude')
        runtime.native_runtime.list_model_catalog.return_value = RuntimeModelCatalog(runtime='claude', revision=1, models=())
        result = await runtime.create_and_start_session('s', 'hello', selections={'model': 'fable/low'})
        assert not result.ok and result.code == 'session_model_selection_required'
        runtime.native_runtime.create_and_start_session.assert_not_awaited()

        runtime.native_runtime.list_model_catalog.return_value = RuntimeModelCatalog(runtime='claude', revision=1, models=(
            RuntimeModelItem(id='fable', title='Fable', selection_id='fable/model', reasoning_items=(
                RuntimeReasoningItem(id='low', title='Low', selection_id='fable/low'),)),))
        await runtime.selection_store.remember('s', {'model': 'gone/low'})
        before = runtime.native_runtime.start_turn.await_count
        result = await runtime.start_turn('s', 'n', 'hello')
        assert not result.ok and result.code == 'session_model_selection_required'
        assert runtime.native_runtime.start_turn.await_count == before
    asyncio.run(check())


def test_legacy_session_snapshot_is_not_a_user_confirmation(tmp_path):
    async def check():
        runtime, _, _ = bound(tmp_path, 'claude')
        result = await runtime.start_turn(
            'legacy', 'legacy-native', 'hello',
            selections={'model': 'fable/low', 'permission': 'ask'},
        )
        assert not result.ok and result.code == 'session_model_selection_required'
        runtime.native_runtime.start_turn.assert_not_awaited()
    asyncio.run(check())


def test_mismatched_runtime_receipt_keeps_old_pin_and_blocks_turn(tmp_path):
    async def check():
        runtime, _, _ = bound(tmp_path, 'claude')
        await runtime.create_and_start_session('s', 'start', selections={'model': 'fable/low'})
        runtime.native_runtime.update_session_selections.return_value = RuntimeOperationResult(
            ok=True, result={'selections': {'model': 'fable/high'}, 'selectionEffect': 'next_turn'},
        )
        result = await runtime.update_session_selections('s', 'n', {'model': 'fable/low'})
        assert not result.ok and result.code == 'session_model_selection_unconfirmed'
        assert (await runtime.selection_store.read('s'))['model'] == 'fable/low'
        before = runtime.native_runtime.start_turn.await_count
        blocked = await runtime.start_turn('s', 'n', 'after mismatch')
        assert not blocked.ok
        assert runtime.native_runtime.start_turn.await_count == before
    asyncio.run(check())


def test_start_turn_and_switch_use_the_same_session_lock(tmp_path):
    async def check():
        runtime, _, _ = bound(tmp_path, 'claude')
        await runtime.create_and_start_session('s', 'start', selections={'model': 'fable/low'})
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []

        async def start(session_id, external_session_id, content, selections, attachments=(), client_message_id=None, cwd=None):
            calls.append('start')
            entered.set()
            await release.wait()
            return RuntimeOperationResult(ok=True)

        async def update(session_id, external_session_id, selections):
            calls.append('update')
            return RuntimeOperationResult(ok=True, result={'selections': dict(selections)})

        runtime.native_runtime.start_turn.side_effect = start
        runtime.native_runtime.update_session_selections.side_effect = update
        starting = asyncio.create_task(runtime.start_turn('s', 'n', 'hello'))
        await entered.wait()
        switching = asyncio.create_task(runtime.update_session_selections('s', 'n', {'model': 'fable/high'}))
        await asyncio.sleep(0.05)
        assert calls == ['start']
        release.set()
        await starting
        await switching
        assert calls == ['start', 'update']

    asyncio.run(check())


def test_permission_only_update_does_not_clear_a_pending_model_reselection(tmp_path):
    async def check():
        runtime, _, _ = bound(tmp_path, 'claude')
        await runtime.create_and_start_session('s', 'start', selections={'model': 'fable/low'})
        runtime.native_runtime.update_session_selections.return_value = RuntimeOperationResult(
            ok=True, result={'selections': {'model': 'fable/high'}},
        )
        failed = await runtime.update_session_selections('s', 'n', {'model': 'fable/low'})
        assert not failed.ok
        runtime.native_runtime.update_session_selections.return_value = RuntimeOperationResult(
            ok=True, result={'selections': {'model': 'fable/low', 'permission': 'accept-edits'}},
        )
        allowed = await runtime.update_session_selections('s', 'n', {'permission': 'accept-edits'})
        assert allowed.ok
        before = runtime.native_runtime.start_turn.await_count
        blocked = await runtime.start_turn('s', 'n', 'still blocked')
        assert not blocked.ok
        assert runtime.native_runtime.start_turn.await_count == before
    asyncio.run(check())


def test_runtime_without_model_catalog_can_start_without_a_pin(tmp_path):
    async def check():
        runtime, _, _ = bound(tmp_path, 'claude')
        runtime.native_runtime.get_runtime_capabilities.return_value = RuntimeCapabilitySet(
            runtime='claude', revision=1, capabilities=(),
        )
        created = await runtime.create_and_start_session('s', 'start')
        assert created.ok
        sent = await runtime.start_turn('s', 'n', 'next')
        assert sent.ok
        runtime.native_runtime.start_turn.assert_awaited_once()
    asyncio.run(check())
