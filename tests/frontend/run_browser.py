"""Isolated UI/API/CSV QA with a full synthetic batch, never a real-model claim."""
import csv
import json
import os
from pathlib import Path
import socket
import signal
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests/tooling'))
from test_package_ml_handoff import make_package_inputs
from scripts.package_ml_handoff import package
from backend.handoff.install import install


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def main():
    processes = []
    with tempfile.TemporaryDirectory(prefix='tramflow-ui-') as tmp:
        root = Path(tmp)
        if os.environ.get('QA_RELEASE'):
            release = Path(os.environ['QA_RELEASE']).resolve()
            forecast = release / 'forecast.csv'
            source_kind = 'real'
        else:
            model, forecast = make_package_inputs(root)
            package(model, forecast, root / 'package.zip')
            install(root / 'package.zip', root / 'release')
            release = root / 'release'
            source_kind = 'synthetic'
        backend_port, frontend_port = port(), port()
        base = f'http://127.0.0.1:{frontend_port}'
        env = {**os.environ, 'TRAMFLOW_HANDOFF_DIR': str(release), 'BACKEND_URL': f'http://127.0.0.1:{backend_port}'}
        with (root / 'server.log').open('w+') as log:
            try:
                processes.append(subprocess.Popen([sys.executable, '-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', str(backend_port)], cwd=ROOT, env=env, stdout=log, stderr=log, start_new_session=True))
                processes.append(subprocess.Popen(['npm', '--prefix', 'frontend', 'run', 'dev', '--', '--host', '127.0.0.1', '--port', str(frontend_port), '--strictPort'], cwd=ROOT, env=env, stdout=log, stderr=log, start_new_session=True))
                for _ in range(100):
                    try:
                        with urlopen(base + '/api/v2/handoff/ready', timeout=1) as response:
                            if response.status == 200:
                                break
                    except Exception:
                        time.sleep(.1)
                else:
                    raise RuntimeError('Isolated stack did not start')
                output = ROOT / f'artifacts/verification/ui-{source_kind}'
                output.mkdir(parents=True, exist_ok=True)
                subprocess.run([sys.executable, '-m', 'backend.handoff.check', '--base-url', base, '--release', str(release)], cwd=ROOT, env=env, check=True)
                result = subprocess.run([os.environ.get('QA_NODE', 'node'), str(ROOT / 'tests/frontend/handoff.cjs')], input=json.dumps({'baseURL': base, 'forecast': str(forecast), 'output': str(output), 'sourceKind': source_kind}), text=True, cwd=ROOT, env=env)
                if result.returncode:
                    log.seek(0)
                    print(log.read()[-5000:])
                    raise SystemExit(result.returncode)
            finally:
                for process in reversed(processes):
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                for process in reversed(processes):
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()


if __name__ == '__main__':
    main()
