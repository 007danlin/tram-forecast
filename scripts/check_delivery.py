"""Check that a Git checkout contains the complete, data-free source delivery.

Run before publishing and in CI. Untracked source files are errors: a successful
local build must not conceal files that a fresh clone will never receive.
"""

import argparse
from pathlib import Path, PurePosixPath
import re
import subprocess
from urllib.parse import unquote, urlsplit


REQUIRED = (
    "README.md", "INTEGRATION.md", ".gitignore", ".dockerignore", ".env.example",
    ".github/workflows/ci.yml", "compose.yaml", "compose.server.yaml",
    "compose.handoff.yaml", "backend/main.py", "backend/requirements.txt",
    "backend/Dockerfile", "backend/handoff/install.py", "backend/handoff/store.py",
    "backend/handoff/README.md", "ml/adapter.py", "ml/forecast.py",
    "ml/requirements.txt", "frontend/package.json", "frontend/package-lock.json",
    "frontend/Dockerfile", "frontend/src/main.tsx", "frontend/src/App.tsx",
    "frontend/src/useForecast.ts", "frontend/src/handoff.ts", "frontend/public/tram-icon.png",
    "frontend/public/map-local/network.json", "frontend/scripts/check-map.mjs",
    "deploy/README.md", "deploy/Caddyfile.https", "deploy/frontend.Dockerfile",
    "deploy/update.sh", "deploy/handoff.sh", "deploy/sync-source.sh", "scripts/package_ml_handoff.py",
    "scripts/check_delivery.py",
)
LOCAL_DIRECTORIES = {".venv", "venv", "node_modules", "dist", "__pycache__", "tmp", "output", "artifacts", "models"}
LOCAL_SUFFIXES = {".netrc", ".joblib", ".pkl", ".pickle", ".pt", ".pth", ".onnx", ".h5", ".parquet", ".arrow", ".zip"}


def git_files(root: Path, *args: str) -> set[str]:
    raw = subprocess.check_output(["git", "-C", str(root), "ls-files", "-z", *args])
    return {name.decode("utf-8") for name in raw.split(b"\0") if name}


def local_only(name: str) -> bool:
    path = PurePosixPath(name)
    if any(part in LOCAL_DIRECTORIES for part in path.parts):
        return True
    if path.name == ".env" or path.name.startswith(".env.") and path.name != ".env.example":
        return True
    if path.name in {"tramflow-users.caddy", "jury-access.txt"} or path.suffix in LOCAL_SUFFIXES:
        return True
    if name.startswith("data/") and name != "data/README.md" and not name.startswith("data/synthetic/"):
        return True
    return path.suffix == ".csv" and not name.startswith(("data/synthetic/", "ml/reports/"))


def check(root: Path) -> list[str]:
    root = root.resolve()
    tracked = git_files(root, "--cached")
    errors = []
    for name in sorted(git_files(root, "--others", "--exclude-standard")):
        errors.append(f"Not included in Git: {name}")
    for name in REQUIRED:
        if name not in tracked or not (root / name).is_file():
            errors.append(f"Required delivery file missing from Git or disk: {name}")
    for name in sorted(tracked):
        path = root / name
        if local_only(name):
            errors.append(f"Local data/artifact must not be in source delivery: {name}")
        if not path.is_file():
            errors.append(f"Tracked file missing from disk: {name}")
            continue
        if path.is_symlink():
            errors.append(f"Source delivery must not depend on a symlink: {name}")
            continue
        if path.suffix != ".md":
            continue
        for target in re.findall(r"\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
            target = target.strip().removeprefix("<").removesuffix(">")
            parts = urlsplit(target)
            if parts.scheme or parts.netloc or not parts.path or parts.path.startswith("/"):
                continue
            resolved = (path.parent / unquote(parts.path)).resolve()
            try:
                relative = resolved.relative_to(root).as_posix()
            except ValueError:
                errors.append(f"Documentation points outside delivery: {name} -> {target}")
                continue
            if relative not in tracked and not any(p.startswith(relative.rstrip("/") + "/") for p in tracked):
                errors.append(f"Documentation target not in Git: {name} -> {target}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    errors = check(args.root)
    if errors:
        print("Source delivery is incomplete:")
        print("\n".join(f"- {error}" for error in errors))
        return 1
    print("Source delivery complete: required files and documentation targets are in Git; local data/artifacts excluded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
