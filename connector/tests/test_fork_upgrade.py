"""The upgrade rollback must restore code, without touching native credentials."""
import hashlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_failed_post_install_check_restores_package_and_service(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[2] / 'scripts/upgrade-fork-connector.py'
    spec = importlib.util.spec_from_file_location('upgrade', path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    home = tmp_path / 'aa-fork'
    venv = home / '.venv'
    site = venv / 'lib/python3.12/site-packages'
    base = tmp_path / 'opt'
    config = home / '.agents-anywhere-fork/connector.json'
    for folder in [site / 'connector', site / 'anywhere_cli-2.5.4.dist-info', venv / 'bin', base / 'bin', config.parent]:
        folder.mkdir(parents=True, exist_ok=True)
    module = site / 'connector/__init__.py'
    module.write_text('old code')
    (venv / 'bin/anywhere-cli').write_text('original entry')
    (base / 'bin/uv').touch()
    config.write_text('{"connectorId":"conn_test"}')
    native = home / '.agents-anywhere-fork/native/codex/auth.json'
    native.parent.mkdir(parents=True)
    native.write_text('synthetic-do-not-change')
    wheel = tmp_path / m.WHEEL
    wheel.write_bytes(b'test-wheel')
    for name, value in [('HOME', home), ('VENV', venv), ('BASE', base), ('CONFIG', config)]:
        monkeypatch.setattr(m, name, value)
    monkeypatch.setattr(m, 'SHA256', hashlib.sha256(wheel.read_bytes()).hexdigest())
    monkeypatch.setattr(m.os, 'geteuid', lambda: 0)
    monkeypatch.setattr(m.pwd, 'getpwnam', lambda _: SimpleNamespace(pw_dir=str(home)))
    monkeypatch.setattr(m.sys, 'argv', ['upgrade', '--wheel', str(wheel)])
    version = ['2.5.4']
    monkeypatch.setattr(m, 'metadata', lambda: {'events': True, 'python': [3, 12], 'site': str(site), 'version': version[0]})
    unit = f'{venv}/bin/anywhere-cli {config} AA_CONNECTOR_PROFILE=fork AGENT_CONNECTOR_DATA_DIR={config.parent}'
    events = []
    run = m.subprocess.run

    def fake_run(args, **kwargs):
        if args[0] == 'systemctl':
            events.append(tuple(args[1:]))
            output = 'aa-fork' if 'show' in args else unit if 'cat' in args else 'active'
            return SimpleNamespace(returncode=0, stdout=output)
        if args[0] == str(base / 'bin/uv'):
            module.write_text('new but broken code')
            version[0] = m.VERSION
            return SimpleNamespace(returncode=0)
        if args[0] == 'chown':
            return SimpleNamespace(returncode=0)
        return run(args, **kwargs)

    monkeypatch.setattr(m.subprocess, 'run', fake_run)
    monkeypatch.setattr(m, 'native_check', lambda _: (_ for _ in ()).throw(RuntimeError('native check failed')))
    with pytest.raises(RuntimeError, match='native check failed'):
        m.main()
    assert module.read_text() == 'old code'
    assert native.read_text() == 'synthetic-do-not-change'
    assert config.read_text() == '{"connectorId":"conn_test"}'
    assert ('stop', m.SERVICE) in events and events[-1] == ('start', m.SERVICE)
