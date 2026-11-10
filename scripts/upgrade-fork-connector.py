#!/usr/bin/env python3
"""Upgrade the existing isolated aa-fork service; never install into the official user."""
import argparse
import hashlib
import json
import os
import pwd
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

VERSION = "2.5.5"
WHEEL = "anywhere_cli-2.5.5-py3-none-any.whl"
SHA256 = "1de2a36032dc713fd5645e9c7f9376f030212c303179c2e90a731f5d07831c08"
URL = "https://github.com/zzyyaa916/Agents-Anywhere/releases/download/v2.5.5-fork/" + WHEEL
SERVICE = "agents-anywhere-fork.service"
HOME = Path("/home/aa-fork")
VENV = HOME / ".venv"
CONFIG = HOME / ".agents-anywhere-fork/connector.json"
BASE = Path("/opt/agents-anywhere-fork-connector")


def command(args):
    result = subprocess.run(args, check=False, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError("Command failed: " + Path(args[0]).name)
    return result.stdout.strip()


def metadata():
    code = 'import json,sys;from importlib.metadata import version,distribution;import claude_agent_sdk.types as t;print(json.dumps({"version":version("anywhere-cli"),"site":str(distribution("anywhere-cli").locate_file("")),"events":hasattr(t,"RateLimitEvent") and hasattr(t,"RateLimitInfo"),"python":list(sys.version_info[:2])}))'
    return json.loads(command([str(VENV / "bin/python"), "-c", code]))


def native_check(unit):
    environment = ["HOME=" + str(HOME), "AA_CONNECTOR_PROFILE=fork"]
    if "AA_FORK_RUNTIME_BROKER=1" in unit:
        environment.append("AA_FORK_RUNTIME_BROKER=1")
    code = """import asyncio
from connector.core.fork_profile import prepare_native_profile, broker_executable
from connector.account_usage import codex_process
prepare_native_profile()
broker_executable('codex')
broker_executable('claude')
async def check():
    async with codex_process() as request:
        result = await request('account/read', {'refreshToken': False})
        models = await request('model/list', {'limit': 200})
        assert models.get('data'), 'Codex model catalog is empty'
        print('Codex initialized; models=' + str(len(models['data'])) + '; account=' + ('present' if result.get('account') else 'login_required'))
asyncio.run(check())
"""
    return command(["runuser", "-u", "aa-fork", "--", "env", *environment,
                    str(VENV / "bin/python"), "-c", code])


def bridge_check():
    state = subprocess.run(["systemctl", "show", "agents-anywhere-fork-dsh.service", "-p", "ActiveState", "--value"], check=False, capture_output=True, text=True)
    if state.stdout.strip() != "active":
        return
    account = command(["systemctl", "show", "agents-anywhere-fork-dsh.service", "-p", "User", "--value"])
    if account not in {"aa-fork", "ai-dsh"}:
        raise RuntimeError("Unexpected DSH service identity")
    code = """import json,socket,time
from pathlib import Path
path=Path('/home/aa-fork/.agents-anywhere/dsh-bridge/connector.json')
for attempt in range(40):
    try:
        data=json.loads(path.read_text())
        with socket.socket(socket.AF_UNIX) as peer:
            peer.settimeout(1)
            peer.connect(data['endpoint']['unixPath'])
        print('DSH Bridge readable and reachable as its service user')
        break
    except (OSError, ValueError, KeyError):
        if attempt==39:raise RuntimeError('DSH Bridge access check failed') from None
        time.sleep(0.5)
"""
    print(command(["runuser", "-u", account, "--", "/usr/bin/python3", "-c", code]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, help="Use a local wheel with the pinned SHA256")
    parser.add_argument("--check-only", action="store_true", help="Read-only installation checks")
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise RuntimeError("Run with sudo; only the isolated aa-fork installation is supported")
    account = pwd.getpwnam("aa-fork")
    if Path(account.pw_dir) != HOME or not CONFIG.is_file():
        raise RuntimeError("Expected an already paired aa-fork installation")
    if command(["systemctl", "show", SERVICE, "--property=User", "--value"]) != "aa-fork":
        raise RuntimeError("Service is not isolated as aa-fork; no changes made")
    unit = command(["systemctl", "cat", SERVICE])
    for required in [str(VENV / "bin/anywhere-cli"), str(CONFIG), "AA_CONNECTOR_PROFILE=fork", "AGENT_CONNECTOR_DATA_DIR=" + str(CONFIG.parent)]:
        if required not in unit:
            raise RuntimeError("Service paths/profile differ; no changes made")
    installed = metadata()
    if not installed["events"] or installed["python"] < [3, 12]:
        raise RuntimeError("Existing Python/Claude SDK needs separate preparation; no changes made")
    site = Path(installed["site"])
    if not site.is_relative_to(VENV):
        raise RuntimeError("Package is outside the isolated virtual environment")
    binding = json.loads(CONFIG.read_text())
    connector_id = binding.get("connectorId")
    if not isinstance(connector_id, str) or not connector_id.startswith("conn_"):
        raise RuntimeError("Missing existing pairing; no changes made")
    print("Host:", os.uname().nodename, "Connector:", connector_id, "Version:", installed["version"], flush=True)
    if args.check_only:
        print(native_check(unit))
        bridge_check()
        print("Preflight passed; no files or services changed")
        return
    uv = BASE / "bin/uv"
    if not uv.is_file():
        raise RuntimeError("Missing isolated uv binary; no changes made")
    # Native credential/configuration directories are neither read nor copied.
    with tempfile.TemporaryDirectory(prefix="aa-fork-upgrade-") as temporary:
        wheel = Path(temporary) / WHEEL
        if args.wheel:
            shutil.copyfile(args.wheel, wheel)
        else:
            with urllib.request.urlopen(URL, timeout=60) as response:
                wheel.write_bytes(response.read(16 * 1024 * 1024))
        if hashlib.sha256(wheel.read_bytes()).hexdigest() != SHA256:
            raise RuntimeError("Wheel SHA256 mismatch; no changes made")
        backup = BASE / "backups" / ("before-" + VERSION + "-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()))
        backup.mkdir(parents=True, mode=0o700)
        os.chmod(backup.parent, 0o700)
        members = [site / "connector", *site.glob("anywhere_cli-*.dist-info"), VENV / "bin/anywhere-cli"]
        if len(members) != 3:
            raise RuntimeError("Unexpected package layout; no changes made")
        command(["tar", "-cpf", str(backup / "package.tar"), "-C", str(VENV), *[str(p.relative_to(VENV)) for p in members]])
        os.chmod(backup / "package.tar", 0o600)
        active = command(["systemctl", "is-active", SERVICE]) == "active"
        config_digest = hashlib.sha256(CONFIG.read_bytes()).digest()
        stopped = False
        try:
            command(["systemctl", "stop", SERVICE])
            stopped = True
            env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "UV_CACHE_DIR": str(Path(temporary) / "cache"), "UV_NO_PROGRESS": "1"}
            with (backup / "install.log").open("w") as log:
                os.chmod(backup / "install.log", 0o600)
                result = subprocess.run([str(uv), "pip", "install", "--python", str(VENV / "bin/python"), "--no-index", "--no-deps", "--reinstall", str(wheel)], check=False, env=env, stdout=log, stderr=log)
            if result.returncode or metadata()["version"] != VERSION:
                raise RuntimeError("Package install/verification failed")
            subprocess.run(["chown", "-R", "aa-fork:aa-fork", str(site / "connector"), str(site / ("anywhere_cli-" + VERSION + ".dist-info")), str(VENV / "bin/anywhere-cli")], check=True, capture_output=True)
            if hashlib.sha256(CONFIG.read_bytes()).digest() != config_digest:
                raise RuntimeError("Pairing configuration changed unexpectedly")
            print(native_check(unit))
            if active:
                command(["systemctl", "start", SERVICE])
                time.sleep(3)
                if command(["systemctl", "is-active", SERVICE]) != "active":
                    raise RuntimeError("Service did not restart")
                bridge_check()
            print("Updated to " + VERSION + "; pairing unchanged; backup:", backup, flush=True)
        except Exception:
            if stopped:
                subprocess.run(["systemctl", "stop", SERVICE], check=False, capture_output=True)
                for path in [site / "connector", *site.glob("anywhere_cli-*.dist-info")]:
                    if path.is_dir():
                        shutil.rmtree(path)
                command(["tar", "-xpf", str(backup / "package.tar"), "-C", str(VENV)])
                if active:
                    command(["systemctl", "start", SERVICE])
                print("Restored previous package; backup:", backup, file=sys.stderr)
            raise


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
        print("Upgrade stopped:", type(error).__name__, str(error), file=sys.stderr)
        sys.exit(1)
