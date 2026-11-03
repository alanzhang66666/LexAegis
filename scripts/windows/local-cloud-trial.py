"""Manage a local-only synthetic trial; no cloud credentials or external sends."""
from pathlib import Path
import argparse
import ctypes
from ctypes import wintypes
import json
import os
import secrets
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
TRIAL = ROOT / '.data' / 'local-cloud-trial'
STATE = TRIAL / 'state.json'
PORTS = {'model': 18080, 'api': 48765, 'gateway': 48766}


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def process_identity(pid, expected=None, terminate=False):
    """Compare creation time on the same handle before stopping an owned process."""
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    handle = kernel.OpenProcess(0x1000 | (1 if terminate else 0), False, pid)
    if not handle:
        return None
    try:
        exit_code = wintypes.DWORD()
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(exit_code)) or exit_code.value != 259:
            return None
        times = [wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle, *[ctypes.byref(t) for t in times]):
            return None
        token = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
        if expected is not None and token != expected:
            return None
        if terminate:
            # A Windows venv executable can own a base-Python child. Hold the
            # verified handle while stopping this process tree, avoiding PID reuse.
            result = subprocess.run(['taskkill.exe', '/PID', str(pid), '/T', '/F'],
                capture_output=True, timeout=15)
            if result.returncode:
                raise RuntimeError('Could not stop the verified trial process tree')
        return token
    finally:
        kernel.CloseHandle(handle)


def occupied(port):
    with socket.socket() as probe:
        return probe.connect_ex(('127.0.0.1', port)) == 0


def credentials():
    result = {}
    for name in ('local-password', 'gateway-secret'):
        path = TRIAL / 'credentials' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(secrets.token_urlsafe(24), encoding='utf-8')
        result[name] = path.read_text(encoding='utf-8').strip()
    return result


def environment(auth, role):
    env = {k: v for k, v in os.environ.items() if not k.startswith('LEX_')}
    env.update(PYTHONUTF8='1', PYTHONUNBUFFERED='1')
    if role == 'model':
        return env
    if role == 'gateway':
        env.update({
            'LEX_RUN_PROFILE': 'demo', 'LEX_DEPLOYMENT_MODE': 'native',
            'LEX_GATEWAY_DIR': str(TRIAL / 'cloud' / 'demo' / 'gateway'),
            'LEX_GATEWAY_SECRET': auth['gateway-secret'], 'LEX_RUNTIME_ROLE': role,
        })
        return env
    env.update({
        'PYTHONUTF8': '1', 'PYTHONUNBUFFERED': '1',
        'LEX_RUN_PROFILE': 'demo', 'LEX_DEPLOYMENT_MODE': 'native',
        'LEX_DATA_DIR': str(TRIAL / 'edge' / 'demo' / 'app'),
        'LEX_GATEWAY_DIR': str(TRIAL / 'cloud' / 'demo' / 'gateway'),
        'LEX_API_PORT': str(PORTS['api']), 'LEX_GATEWAY_PORT': str(PORTS['gateway']),
        'LEX_GATEWAY_URL': f"http://127.0.0.1:{PORTS['gateway']}",
        'LEX_GATEWAY_SECRET': auth['gateway-secret'],
        'LEX_RUNTIME_ROLE': role,
        'LEX_EDGE_URL': f"http://127.0.0.1:{PORTS['model']}/v1",
        'LEX_EDGE_MODEL': 'edge-small', 'LEX_EDGE_ALLOWED_HOSTS': '127.0.0.1',
        'LEX_EDGE_OUTBOUND_REVIEW': '1', 'LEX_DEMO_LIVE_EDGE_REVIEW': '1',
        'LEX_EDGE_IDLE_UNLOAD_SECONDS': '0',
        'LEX_OCR_ENABLED': '0', 'LEX_WHISPER_ENABLED': '0',
    })
    if role == 'api':
        env['LEX_LOCAL_PASSWORD'] = auth['local-password']
        env['LEX_LOCAL_ACTOR'] = '本地合成演示管理员'
    return env


def start():
    assets_path = TRIAL / 'setup' / 'ASSETS.json'
    if not assets_path.exists():
        raise RuntimeError('Model/runtime assets have not finished installing.')
    if STATE.exists():
        state = json.loads(STATE.read_text(encoding='utf-8'))
        alive = [p for p in state.get('processes', []) if process_identity(p['pid'], p['created'])]
        if alive:
            if len(alive) == 4:
                return status()
            raise RuntimeError('Partial trial is running. Stop it before starting again.')
    for name, port in PORTS.items():
        if occupied(port):
            raise RuntimeError(f'{name} port {port} is in use; existing process was left unchanged.')
    assets = json.loads(assets_path.read_text(encoding='utf-8'))
    auth = credentials()
    logs = TRIAL / 'logs'
    logs.mkdir(parents=True, exist_ok=True)
    state = {'profile': 'demo', 'deployment_mode': 'native', 'url': f"http://127.0.0.1:{PORTS['api']}", 'processes': []}
    import httpx

    def spawn(role, command):
        with (logs / f'{role}.stdout.log').open('ab') as out, (logs / f'{role}.stderr.log').open('ab') as err:
            process = subprocess.Popen(command, cwd=ROOT, env=environment(auth, role), stdin=subprocess.DEVNULL,
                stdout=out, stderr=err, creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)
        identity = process_identity(process.pid)
        if not identity:
            raise RuntimeError(f'{role} exited on startup; check {logs}')
        state['processes'].append({'role': role, 'pid': process.pid, 'created': identity})
        save(STATE, state)
        print(f'Started {role} PID {process.pid}', flush=True)
        return process

    def ready(url, process, timeout=120):
        deadline = time.monotonic() + timeout
        with httpx.Client(trust_env=False, timeout=2) as client:
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(f'Process exited; check {logs}')
                try:
                    if client.get(url).status_code == 200:
                        return
                except httpx.HTTPError:
                    pass
                time.sleep(0.5)
        raise RuntimeError(f'Service startup timed out: {url}')

    try:
        model = spawn('model', [assets['binary_path'], '--model', assets['model_path'], '--host', '127.0.0.1',
            '--port', str(PORTS['model']), '--alias', 'edge-small', '--jinja', '--ctx-size', '8192',
            '--batch-size', '512', '--ubatch-size', '128', '--parallel', '1', '--n-gpu-layers', '99',
            '--flash-attn', 'on', '--threads', '4'])
        ready(f"http://127.0.0.1:{PORTS['model']}/v1/models", model)
        gateway = spawn('gateway', [sys.executable, '-m', 'uvicorn', 'lexaegis.gateway:create_gateway', '--factory',
            '--host', '127.0.0.1', '--port', str(PORTS['gateway']), '--no-access-log'])
        deadline = time.monotonic() + 45
        while not occupied(PORTS['gateway']):
            if gateway.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError(f'Gateway not ready; check {logs}')
            time.sleep(0.5)
        api = spawn('api', [sys.executable, '-m', 'uvicorn', 'lexaegis.api:create_app', '--factory',
            '--host', '127.0.0.1', '--port', str(PORTS['api']), '--no-access-log'])
        ready(state['url'] + '/api/v1/health', api)
        spawn('worker', [sys.executable, '-m', 'lexaegis.worker'])
        print('Ready: ' + state['url'], flush=True)
        print('Login password file: ' + str(TRIAL / 'credentials' / 'local-password'), flush=True)
    except BaseException:
        for entry in reversed(state['processes']):
            process_identity(entry['pid'], entry['created'], terminate=True)
        raise


def status():
    state = json.loads(STATE.read_text(encoding='utf-8')) if STATE.exists() else {'processes': []}
    for entry in state['processes']:
        entry['alive'] = process_identity(entry['pid'], entry['created']) is not None
    print(json.dumps(state, ensure_ascii=False, indent=2))


def stop():
    if not STATE.exists():
        return status()
    state = json.loads(STATE.read_text(encoding='utf-8'))
    for entry in reversed(state['processes']):
        if process_identity(entry['pid'], entry['created'], terminate=True):
            print('Stopped ' + entry['role'])
    print('Trial stopped. Data, model assets and credentials retained.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start', 'stop', 'status'])
    args = parser.parse_args()
    try:
        {'start': start, 'stop': stop, 'status': status}[args.action]()
    except Exception as error:
        print(f'{type(error).__name__}: {error}', file=sys.stderr)
        raise SystemExit(1)
