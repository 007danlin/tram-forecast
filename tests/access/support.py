"""Isolated loopback HTTPS stack; never changes the host trust store or VPS."""

from contextlib import contextmanager, ExitStack
import json
import os
from pathlib import Path
import secrets
import socket
import ssl
import subprocess
from tempfile import TemporaryDirectory
import threading
import time
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

import uvicorn
from backend.main import app


ROOT = Path(__file__).resolve().parents[2]


def stop_process(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


@contextmanager
def protected_stack(caddy, static_root=None):
    with ExitStack() as cleanup:
        temp = Path(cleanup.enter_context(TemporaryDirectory(prefix="tramflow-access-")))
        if static_root is None:
            static_root = temp / "static"
            (static_root / "map-local").mkdir(parents=True)
            (static_root / "index.html").write_text("<!doctype html><title>TramFlow access test</title>")
            (static_root / "map-local/network.json").write_text('{"synthetic":true}')
        username, password = "local-qa", secrets.token_urlsafe(24)
        hashed = subprocess.run(
            [caddy, "hash-password"], input=password + "\n",
            text=True, capture_output=True, check=True,
        ).stdout.strip()
        auth_file = temp / "users.caddy"
        auth_file.write_text(f"{username} {hashed}\n")
        auth_file.chmod(0o600)
        seen_headers = []

        async def observed_app(scope, receive, send):
            if scope["type"] == "http":
                seen_headers.append(dict(scope["headers"]))
            await app(scope, receive, send)

        backend_socket = socket.socket()
        cleanup.callback(backend_socket.close)
        backend_socket.bind(("127.0.0.1", 0))
        backend = f"127.0.0.1:{backend_socket.getsockname()[1]}"
        server = uvicorn.Server(uvicorn.Config(observed_app, log_level="critical"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [backend_socket]}, daemon=True)
        thread.start()

        def stop_backend():
            server.should_exit = True
            thread.join(timeout=5)

        cleanup.callback(stop_backend)
        with socket.socket() as port_socket:
            port_socket.bind(("127.0.0.1", 0))
            https_port = port_socket.getsockname()[1]
        base_url = f"https://localhost:{https_port}"
        env = os.environ | {
            "TRAMFLOW_SITE": base_url,
            "TRAMFLOW_ROOT": str(static_root),
            "TRAMFLOW_BACKEND": backend,
            "TRAMFLOW_AUTH_FILE": str(auth_file),
            "XDG_DATA_HOME": str(temp / "data"),
            "XDG_CONFIG_HOME": str(temp / "config"),
        }
        config = temp / "Caddyfile"
        config.write_text(
            "{\n admin off\n auto_https disable_redirects\n skip_install_trust\n"
            " default_bind 127.0.0.1\n}\n"
            f"import {json.dumps(str(ROOT / 'deploy/Caddyfile.protected'), ensure_ascii=False)}\n"
        )
        validation = subprocess.run(
            [caddy, "validate", "--config", str(config), "--adapter", "caddyfile"],
            env=env, capture_output=True, text=True,
        )
        if validation.returncode:
            raise RuntimeError("Caddy protected config validation failed.")
        log = cleanup.enter_context((temp / "caddy.log").open("w+"))
        process = subprocess.Popen(
            [caddy, "run", "--config", str(config), "--adapter", "caddyfile"],
            env=env, stdout=log, stderr=log,
        )
        cleanup.callback(stop_process, process)
        ca_file = temp / "data/caddy/pki/authorities/local/root.crt"
        for _ in range(200):
            if process.poll() is not None:
                raise RuntimeError("Local Caddy exited before becoming ready.")
            if ca_file.exists() and server.started:
                context = ssl.create_default_context(cafile=str(ca_file))
                try:
                    urlopen(base_url + "/", context=context, timeout=0.5).close()
                except HTTPError as exc:
                    status = exc.code
                    exc.close()
                    if status == 401:
                        break
                except (URLError, OSError):
                    pass
            time.sleep(0.05)
        else:
            raise RuntimeError("Local HTTPS stack did not become ready.")
        yield SimpleNamespace(
            base_url=base_url, username=username, password=password,
            context=context, ca_file=ca_file, backend=backend, temp=temp,
            config=config, env=env, seen_headers=seen_headers,
        )
