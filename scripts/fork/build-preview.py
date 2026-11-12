#!/usr/bin/env python3
"""Package committed Fork Server/Connector sources and the freshly exported Web build."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tomllib

ROOT = Path(__file__).resolve().parents[2]


def build(destination):
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT).strip():
        raise RuntimeError('Commit the reviewed source before packaging')
    version = tomllib.loads((ROOT / 'connector/pyproject.toml').read_text())['project']['version']
    source = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    web = ROOT / 'web-next/out'
    if not (web / 'index.html').is_file():
        raise RuntimeError('Run NEXT_OUTPUT=export next build in web-next first')
    tracked_web = subprocess.check_output(['git', 'ls-files', '-z', 'web-next'], cwd=ROOT).decode().split('\0')
    if any((ROOT / name).stat().st_mtime > (web / 'index.html').stat().st_mtime for name in filter(None, tracked_web)):
        raise RuntimeError('Web export predates the committed source; rebuild before packaging')
    files = {}
    tracked = subprocess.check_output(['git', 'ls-files', '-z', 'server', 'connector'], cwd=ROOT).decode().split('\0')
    for name in filter(None, tracked):
        path = Path(name)
        if any(part in {'tests', '_reference', '_deprecated'} for part in path.parts) or path.name.startswith('.'):
            continue
        files[name] = ROOT / path
    for path in web.rglob('*'):
        if path.is_file():
            files['web-static/' + str(path.relative_to(web))] = path
    files['deploy.py'] = ROOT / 'scripts/fork/update-preview.py'
    files['upgrade-legacy-connector.py'] = ROOT / 'scripts/fork/upgrade-legacy-connector.py'
    files['runtime-broker.py'] = ROOT / 'scripts/fork/runtime-broker.py'
    files['native-history-cleanup.py'] = ROOT / 'connector/connector/runtimes/claude/history/deletion.py'
    payload = {}
    for name, path in files.items():
        if path.is_symlink():
            raise ValueError('Release files cannot be links: ' + name)
        payload[name] = path.read_bytes()
    payload['Dockerfile'] = b'''ARG BASE_IMAGE
FROM ${BASE_IMAGE}
RUN rm -rf /app/server /app/web-static
COPY server /app/server
COPY web-static /app/web-static
WORKDIR /app/server
CMD ["/opt/venv/bin/python", "-m", "agent_server.main"]
'''
    manifest = {'version': version, 'source': source, 'files': {name: hashlib.sha256(data).hexdigest() for name, data in payload.items()}}
    payload['manifest.json'] = json.dumps(manifest, sort_keys=True, indent=2).encode()
    destination = Path(destination)
    with destination.open('xb') as stream, tarfile.open(fileobj=stream, mode='w:gz') as archive:
        for name, data in sorted(payload.items()):
            info = tarfile.TarInfo(name)
            info.size = len(data); info.mode = 0o644
            archive.addfile(info, io.BytesIO(data))
    print(hashlib.sha256(destination.read_bytes()).hexdigest(), destination)


if __name__ == '__main__':
    build(sys.argv[1])
