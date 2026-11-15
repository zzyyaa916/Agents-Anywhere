"""Pure policy tests, runnable without the integration database fixtures."""
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from jsonschema import validate

from agent_server.core.account_usage import (
    ClaudeProbeResult,
    UsageResponse,
    UsageWindow,
    merged_claude_windows,
    probe_failure,
)


def test_only_consecutive_429_doubles_and_caps():
    state = {}
    for count, interval in enumerate([600, 1200, 1800, 1800], 1):
        state = probe_failure(state, 2000000000, 'rate_limited')
        assert state['interval'] == interval
        assert state['consecutive_429'] == count
    for code in ['auth_expired', 'parse_error', 'unavailable', 'timeout', 'node_offline']:
        result = probe_failure(state, 2000000000, code)
        assert result['interval'] == 300
        assert result['next_allowed_at'] == 2000000300
        assert result['consecutive_429'] == 0
        assert result['circuit_until'] == 0
        assert probe_failure(result, 2000000300, 'rate_limited')['interval'] == 600


def test_retry_after_has_priority_over_local_cap():
    state = probe_failure({}, 2000000000, 'rate_limited', retry_after_seconds=7200)
    assert state['next_allowed_at'] == 2000007200
    assert probe_failure(state, 2000000000, 'rate_limited', retry_after_at=datetime.fromtimestamp(2000008000, UTC))['next_allowed_at'] == 2000008000


def test_null_reset_merge_keeps_window_receipts_independent():
    def window(kind, reset):
        return UsageWindow(kind=kind, used_percent=0, remaining_percent=100, resets_at=reset,
            window_duration_mins=300 if kind == 'five_hour' else 10080)
    old = window('five_hour', '2033-05-18T04:00:00Z')
    inactive = window('five_hour', None)
    weekly = window('seven_day', '2033-05-25T04:00:00Z')
    data = {'five_hour': {'probe': {'window': inactive.model_dump(mode='json', by_alias=True), 'source': 'probe', 'received_at': '2033-05-18T03:33:20+00:00'}},
        'seven_day': {'probe': {'window': weekly.model_dump(mode='json', by_alias=True), 'source': 'probe', 'received_at': '2033-05-18T03:23:20+00:00'}},
        'parse_warnings': [{'field': 'seven_day.utilization', 'reason': 'TypeError'}]}
    result = merged_claude_windows(data, [old], 2000000000)
    assert result[0].resets_at is None
    assert result[0].age_seconds == 0
    assert result[1].age_seconds == 600


def test_contracts_match_models_and_accept_inactive_parse_warnings():
    root = Path(__file__).resolve().parents[2] / 'contracts/account-usage/1.0'
    for name, model in [('claude-probe-result', ClaudeProbeResult), ('usage-response', UsageResponse)]:
        assert json.loads((root / (name + '.schema.json')).read_text()) == model.model_json_schema(by_alias=True)
    result = ClaudeProbeResult(runtime='claude_code', account_key='a'*64, windows=[{
        'kind': 'five_hour', 'usedPercent': 0, 'remainingPercent': 100, 'resetsAt': None, 'windowDurationMins': 300}],
        parse_warnings=[{'field':'seven_day.utilization','reason':'TypeError'}])
    validate(result.model_dump(mode='json', by_alias=True), json.loads((root / 'claude-probe-result.schema.json').read_text()))
    with pytest.raises(ValueError):
        ClaudeProbeResult(runtime='claude_code', detail='raw response must not pass')


@pytest.mark.parametrize('code', ['auth_expired', 'parse_error'])
def test_non_429_ignores_retry_after_and_resets_backoff(code):
    state = probe_failure({'consecutive_429': 2, 'interval': 1200}, 2000000000, code, retry_after_seconds=7200)
    assert state['interval'] == 300
    assert state['next_allowed_at'] == 2000000300
    assert state['consecutive_429'] == 0
