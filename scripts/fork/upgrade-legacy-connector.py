#!/usr/bin/env python3
"""Upgrade a legacy Fork Connector in a separate venv; keep the original for rollback."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

SERVICE = 'agents-anywhere-fork.service'
VENV = Path('/home/aa-fork/.venv')
VERSION = '2.6.2'


def run(args):
    return subprocess.check_output([str(x) for x in args], text=True).strip()


def switch(venv, new, backup, command=run, validate=lambda: None):
    # Keep the old venv at its original name until the service has stopped.
    command(['systemctl', 'stop', SERVICE])
    moved = False
    try:
        venv.rename(backup)
        moved = True
        venv.symlink_to(new, target_is_directory=True)
        command(['systemctl', 'start', SERVICE])
        time.sleep(8)
        command(['systemctl', 'is-active', '--quiet', SERVICE])
        validate()
    except BaseException:
        if moved:
            try:
                command(['systemctl', 'stop', SERVICE])
            except Exception:
                pass
            if venv.is_symlink():
                venv.unlink()
            backup.rename(venv)
        command(['systemctl', 'start', SERVICE])
        raise


def upgrade(root):
    if os.geteuid() != 0:
        raise RuntimeError('请使用 sudo python3 upgrade-legacy-connector.py 更新包目录')
    root = Path(root).resolve()
    manifest = json.loads((root / 'manifest.json').read_text())
    if manifest.get('version') != VERSION:
        raise RuntimeError('更新包版本不匹配；未修改服务。')
    for name, digest in manifest['files'].items():
        p = root / name
        if p.is_symlink() or not p.resolve().is_relative_to(root) or hashlib.sha256(p.read_bytes()).hexdigest() != digest:
            raise RuntimeError('文件校验失败: ' + name)
    if run(['systemctl', 'show', SERVICE, '-p', 'User', '--value']) != 'aa-fork':
        raise RuntimeError('服务运行用户不匹配；未修改服务。')
    executable = run(['systemctl', 'show', SERVICE, '-p', 'ExecStart', '--value'])
    if 'path=/home/aa-fork/.venv/bin/' not in executable:
        raise RuntimeError('服务启动方式不匹配；未修改服务。')
    unit = run(['systemctl', 'cat', SERVICE])
    config = Path('/home/aa-fork/.agents-anywhere-fork/connector.json')
    for required in [str(config), 'AA_CONNECTOR_PROFILE=fork', 'AGENT_CONNECTOR_DATA_DIR=' + str(config.parent)]:
        if required not in unit:
            raise RuntimeError('Fork 服务配置不匹配；未修改服务。')
    binding_digest = hashlib.sha256(config.read_bytes()).hexdigest()
    if run(['systemctl', 'show', SERVICE, '-p', 'ActiveState', '--value']) != 'inactive':
        raise RuntimeError('请先确认没有运行任务并在维护连接中停止 Fork Connector；本脚本不停止在线任务。')
    python = VENV / 'bin/python'
    current = run([python, '-c', 'from importlib.metadata import version; print(version("anywhere-cli"))'])
    if current not in ('2.5.5', '2.6.0', '2.6.1', VERSION):
        raise RuntimeError('Connector 来源版本未经验证；未修改服务。')
    if VENV.is_symlink() and (not VENV.resolve().is_relative_to(VENV.parent) or not VENV.resolve().name.startswith('.venv')):
        raise RuntimeError('Connector 环境链接目标未经验证；未修改服务。')
    uv = shutil.which('uv') or '/opt/agents-anywhere-fork-connector/bin/uv'
    if not Path(uv).is_file():
        raise RuntimeError('未找到 uv；未修改服务。')
    stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    new = VENV.with_name('.venv-fork-' + VERSION + '-' + stamp)
    backup = VENV.with_name('.venv-before-' + VERSION + '-' + stamp)
    new.mkdir(mode=0o700)
    print('正在复制原环境并安装新版，现有服务继续运行。', flush=True)
    subprocess.run(['cp', '-a', '--reflink=auto', str(VENV) + '/.', str(new)], check=True)
    subprocess.run([uv, 'pip', 'install', '--python', str(new / 'bin/python'), '--no-deps', '--reinstall-package', 'anywhere-cli', str(root / 'connector')], check=True)
    subprocess.run([uv, 'pip', 'check', '--python', str(new / 'bin/python')], check=True)
    run([new / 'bin/python', '-c', 'import connector.cli; from connector.local import worktrees; from connector.server import local_rpc; from importlib.metadata import version; assert version("anywhere-cli") == "2.6.2"; print("import check OK")'])
    owner = VENV.stat()
    subprocess.run(['chown', '-R', f'{owner.st_uid}:{owner.st_gid}', str(new)], check=True)
    def validate():
        if run(['systemctl', 'cat', SERVICE]) != unit or hashlib.sha256(config.read_bytes()).hexdigest() != binding_digest:
            raise RuntimeError('Fork 配对或服务配置发生变化')
        run([VENV / 'bin/python', '-c', 'from importlib.metadata import version; assert version("anywhere-cli") == "' + VERSION + '"'])
        if 'AA_FORK_RUNTIME_BROKER=1' in unit:
            run(['runuser', '-u', 'aa-fork', '--', 'env', 'HOME=/home/aa-fork',
                 'AA_CONNECTOR_PROFILE=fork', 'AA_FORK_RUNTIME_BROKER=1',
                 'CODEX_HOME=/home/aa-fork/.agents-anywhere-fork/native/codex',
                 'CLAUDE_CONFIG_DIR=/home/aa-fork/.agents-anywhere-fork/native/claude',
                 'CLAUDE_SECURESTORAGE_CONFIG_DIR=/home/aa-fork/.agents-anywhere-fork/native/claude',
                 str(VENV / 'bin/python'), '-c',
                 'from connector.core.fork_profile import validate_fork_environment, broker_executable; validate_fork_environment(); assert broker_executable("claude") and broker_executable("codex")'])
    try:
        switch(VENV, new, backup, validate=validate)
    except BaseException:
        print('新版启动失败，已尝试恢复原环境和原服务。', file=sys.stderr)
        raise
    print(json.dumps({'status': 'ok', 'release': VERSION + '-fork', 'connectorVersion': VERSION, 'previousVersion': current, 'backup': str(backup), 'environment': str(new)}, ensure_ascii=False))


if __name__ == '__main__':
    upgrade(sys.argv[1])
