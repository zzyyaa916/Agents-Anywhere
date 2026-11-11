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
BUNDLE_SHA = '5221374c33ed6b0e820021378fcaa8ca22e26decd098b60994620f6f672991ed'


def run(args):
    return subprocess.check_output([str(x) for x in args], text=True).strip()


def switch(venv, new, backup, command=run):
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


def main():
    if os.geteuid() != 0:
        raise RuntimeError('请使用 sudo python3 upgrade-legacy-connector.py 更新包目录')
    root = Path(sys.argv[1]).resolve()
    archive = root / 'update.tar.gz'
    if hashlib.sha256(archive.read_bytes()).hexdigest() != BUNDLE_SHA:
        raise RuntimeError('更新包 SHA256 不匹配；未修改服务。')
    manifest = json.loads((root / 'manifest.json').read_text())
    for name, digest in manifest['files'].items():
        p = root / name
        if p.is_symlink() or not p.resolve().is_relative_to(root) or hashlib.sha256(p.read_bytes()).hexdigest() != digest:
            raise RuntimeError('文件校验失败: ' + name)
    if run(['systemctl', 'show', SERVICE, '-p', 'User', '--value']) != 'aa-fork':
        raise RuntimeError('服务运行用户不匹配；未修改服务。')
    executable = run(['systemctl', 'show', SERVICE, '-p', 'ExecStart', '--value'])
    if 'path=/home/aa-fork/.venv/bin/' not in executable:
        raise RuntimeError('服务启动方式不匹配；未修改服务。')
    run(['systemctl', 'is-active', '--quiet', SERVICE])
    python = VENV / 'bin/python'
    current = run([python, '-c', 'from importlib.metadata import version; print(version("anywhere-cli"))'])
    if current != '2.5.5' or VENV.is_symlink():
        raise RuntimeError('本脚本只适用于已确认的 2.5.5 普通目录安装；未修改服务。')
    uv = shutil.which('uv')
    if not uv:
        raise RuntimeError('未找到 uv；未修改服务。')
    stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    new = VENV.with_name('.venv-fork-2.6.1-' + stamp)
    backup = VENV.with_name('.venv-before-2.6.1-' + stamp)
    new.mkdir(mode=0o700)
    print('正在复制原环境并安装新版，现有服务继续运行。', flush=True)
    subprocess.run(['cp', '-a', '--reflink=auto', str(VENV) + '/.', str(new)], check=True)
    subprocess.run([uv, 'pip', 'install', '--python', str(new / 'bin/python'), '--no-deps', '--reinstall-package', 'anywhere-cli', str(root / 'connector')], check=True)
    subprocess.run([uv, 'pip', 'check', '--python', str(new / 'bin/python')], check=True)
    run([new / 'bin/python', '-c', 'import connector.cli; from connector.local import worktrees; from connector.server import local_rpc; from importlib.metadata import version; assert version("anywhere-cli") == "2.6.0"; print("import check OK")'])
    owner = VENV.stat()
    subprocess.run(['chown', '-R', f'{owner.st_uid}:{owner.st_gid}', str(new)], check=True)
    try:
        switch(VENV, new, backup)
    except BaseException:
        print('新版启动失败，已尝试恢复原环境和原服务。', file=sys.stderr)
        raise
    print(json.dumps({'status': 'ok', 'release': '2.6.1-fork', 'connectorVersion': '2.6.0', 'previousVersion': current, 'backup': str(backup), 'environment': str(new)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
