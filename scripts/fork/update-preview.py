#!/usr/bin/env python3
"""Apply a verified Fork preview bundle on its server or one idle Connector device."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def verify(root):
    manifest = json.loads((root / 'manifest.json').read_text())
    for name, expected in manifest['files'].items():
        path = root / name
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()) or digest(path) != expected:
            raise RuntimeError('更新文件校验失败: ' + name)
    return manifest


def run(args, *, log=None):
    result = subprocess.run(args, capture_output=True, text=True)
    if log:
        with log.open('a') as stream:
            stream.write(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError('命令失败: ' + args[0] + '；详细信息仅保存在服务器日志中。')
    return result.stdout.strip()


def get(url):
    with urllib.request.urlopen(url, timeout=15) as response:
        return json.load(response)


def protected(url):
    request = urllib.request.Request(url, data=b'{}', headers={'Content-Type': 'application/json'})
    try:
        urllib.request.urlopen(request, timeout=15).close()
    except urllib.error.HTTPError as error:
        if error.code == 401:
            return
        raise RuntimeError('新版转发接口检查失败: HTTP ' + str(error.code)) from error
    raise RuntimeError('新版转发接口未要求登录，已停止更新。')


def update_server(root, manifest):
    base = Path('/opt/agents-anywhere-fork')
    config = base / 'fork.env'
    previous = config.read_text()
    if sum(line.startswith('FORK_IMAGE=') for line in previous.splitlines()) != 1:
        raise RuntimeError('无法确认 Fork 镜像配置，未修改服务。')
    compose = ['docker', 'compose', '--env-file', str(config), '-f', str(base / 'compose.yml')]
    def query(sql):
        return run(['docker', 'exec', 'agents-anywhere-fork-postgres-1', 'psql', '-U', 'agents_anywhere_fork', '-d', 'agents_anywhere_fork', '-At', '-c', sql])
    def idle():
        states = "('running','pending','waiting','waiting_approval','stopping','blocked')"
        if query(f'SELECT (SELECT count(*) FROM sessions WHERE status IN {states}) + (SELECT count(*) FROM session_active_runs WHERE status IN {states})') != '0':
            raise RuntimeError('Fork 中仍有运行或等待中的任务；请结束后重新执行，未重启服务。')
    def inventory():
        ids = run(['docker', 'ps', '-q']).splitlines()
        return {row['Name']: (row['Id'], row['State']['StartedAt']) for row in json.loads(run(['docker', 'inspect', *ids])) if row['Name'] != '/agents-anywhere-fork-server-1'}
    health = get('http://127.0.0.1:18500/api/v2/health')
    if health.get('version') != '2.6.0' or query('SELECT version_num FROM alembic_version') != 'v2_57':
        raise RuntimeError('当前版本或数据库版本不匹配；未修改服务，不执行数据库迁移。')
    idle()
    old_containers = inventory()
    backup = base / 'backups' / time.strftime('before-2.5.10-%Y%m%dT%H%M%SZ', time.gmtime())
    backup.mkdir(mode=0o700, parents=True)
    for name in ['fork.env', 'compose.yml']:
        shutil.copy2(base / name, backup / name)
    with (backup / 'database.dump').open('wb') as stream:
        result = subprocess.run(['docker', 'exec', 'agents-anywhere-fork-postgres-1', 'pg_dump', '-U', 'agents_anywhere_fork', '-d', 'agents_anywhere_fork', '-Fc'], stdout=stream, stderr=subprocess.PIPE)
        if result.returncode or stream.tell() == 0:
            raise RuntimeError('数据库备份失败，未重启服务。')
    with (backup / 'database.dump').open('rb') as stream:
        result = subprocess.run(['docker', 'exec', '-i', 'agents-anywhere-fork-postgres-1', 'pg_restore', '--list'], stdin=stream, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if result.returncode:
            raise RuntimeError('数据库备份验证失败，未重启服务。')
    old_image = run(['docker', 'inspect', '--format={{.Image}}', 'agents-anywhere-fork-server-1'])
    image = 'agents-anywhere-fork:2.6.0-desktop-2.5.10-' + manifest['source'][:8]
    print('备份完成，正在构建新镜像；现有服务继续运行。', flush=True)
    run(['docker', 'build', '--network=none', '--build-arg', 'BASE_IMAGE=' + old_image, '-t', image, str(root)], log=backup / 'build.log')
    idle()
    try:
        config.write_text('\n'.join('FORK_IMAGE=' + image if line.startswith('FORK_IMAGE=') else line for line in previous.splitlines()) + '\n')
        config.chmod(0o600)
        run(compose + ['up', '-d', '--no-deps', 'server'], log=backup / 'restart.log')
        for _ in range(45):
            try:
                if get('http://127.0.0.1:18500/api/v2/health').get('status') == 'ok':
                    break
            except (OSError, ValueError):
                pass
            time.sleep(1)
        else:
            raise RuntimeError('新版服务健康检查失败。')
        protected('http://127.0.0.1:18500/api/v2/task-groups/from-session/check-only/handoffs')
        public = 'https://81.71.71.114:9443'
        protected(public + '/api/v2/task-groups/from-session/check-only/handoffs')
        if get(public + '/api/v2/health').get('status') != 'ok':
            raise RuntimeError('公网健康检查失败。')
        with urllib.request.urlopen(public + '/', timeout=15) as response:
            if hashlib.sha256(response.read()).hexdigest() != manifest['files']['web-static/index.html']:
                raise RuntimeError('公网 Web 页面与更新包不一致。')
        if query('SELECT version_num FROM alembic_version') != 'v2_57' or inventory() != old_containers:
            raise RuntimeError('数据库版本或其他容器发生变化。')
        auth = get('http://127.0.0.1:18500/api/v2/auth/config')
        if auth['registrationOpen'] or auth['oauthRegistrationOpen']:
            raise RuntimeError('注册设置发生变化。')
    except BaseException:
        config.write_text(previous)
        config.chmod(0o600)
        run(compose + ['up', '-d', '--no-deps', 'server'], log=backup / 'rollback.log')
        print('验证失败，已恢复原 Fork 镜像配置并请求恢复原服务。数据库未迁移、未还原。', flush=True)
        raise
    result = {'status': 'ok', 'source': manifest['source'], 'image': image, 'backup': str(backup), 'schema': 'v2_57', 'webUpdated': True, 'forwardEndpointVerified': True}
    (backup / 'result.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, ensure_ascii=False), flush=True)


def update_connector(root, manifest):
    # Apply only the two additive workspace files; do not resolve dependencies or touch account data.
    python = Path('/home/aa-fork/.venv/bin/python')
    package = Path(run([str(python), '-c', 'import connector; print(next(iter(connector.__path__)))']))
    if not package.resolve().is_relative_to(Path('/home/aa-fork/.venv').resolve()):
        raise RuntimeError('Connector 安装目录不匹配，未修改。')
    files = ['local/worktrees.py', 'server/local_rpc.py']
    for name in files:
        target = package / name
        if digest(target) not in manifest['connectorBases'][name]:
            raise RuntimeError('设备 Connector 与已验证的版本不同，未修改: ' + name)
    backup = Path('/opt/agents-anywhere-fork-connector/backups') / time.strftime('before-2.5.10-%Y%m%dT%H%M%SZ', time.gmtime())
    backup.mkdir(mode=0o700, parents=True)
    for name in files:
        saved = backup / name
        saved.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(package / name, saved)
    run(['systemctl', 'stop', 'agents-anywhere-fork.service'])
    try:
        for name in files:
            shutil.copyfile(root / 'connector/connector' / name, package / name)
        run([str(python), '-c', 'import sys,pathlib; [compile(pathlib.Path(p).read_text(), p, "exec") for p in sys.argv[1:]]', *[str(package / name) for name in files]])
        run(['systemctl', 'start', 'agents-anywhere-fork.service'])
        time.sleep(3)
        run(['systemctl', 'is-active', '--quiet', 'agents-anywhere-fork.service'])
    except BaseException:
        for name in files:
            shutil.copyfile(backup / name, package / name)
        run(['systemctl', 'start', 'agents-anywhere-fork.service'])
        raise
    print(json.dumps({'status': 'ok', 'connectorWorkspaceUpdate': True, 'backup': str(backup)}, ensure_ascii=False))


def main():
    os.umask(0o077)
    root = Path(__file__).resolve().parent
    manifest = verify(root)
    mode = sys.argv[1] if len(sys.argv) > 1 else 'verify'
    if mode == 'verify':
        print('更新包文件校验通过；未修改任何服务。')
        return
    if os.geteuid() != 0:
        raise RuntimeError('请使用 sudo python3 deploy.py server 或 connector。')
    if mode == 'server':
        update_server(root, manifest)
    elif mode == 'connector':
        update_connector(root, manifest)
    else:
        raise RuntimeError('用法: deploy.py verify|server|connector')


if __name__ == '__main__':
    main()
