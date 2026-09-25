"""Run browser QA against an isolated build; requires Caddy, Playwright and Chrome."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from support import protected_stack, ROOT


def main():
    caddy = os.environ.get("CADDY_BIN") or shutil.which("caddy")
    if not caddy or not (ROOT / "frontend/dist/index.html").is_file():
        raise RuntimeError("Set CADDY_BIN and build frontend first.")
    with protected_stack(caddy, ROOT / "frontend/dist") as stack:
        result = subprocess.run(
            [os.environ.get("QA_NODE", "node"), str(Path(__file__).with_name("browser_check.cjs"))],
            input=json.dumps({
                "baseURL": stack.base_url, "username": stack.username,
                "password": stack.password, "screenshot": os.environ.get("QA_SCREENSHOT"),
            }), text=True,
        )
        if result.returncode:
            raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
