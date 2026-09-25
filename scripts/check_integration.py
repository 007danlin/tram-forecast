"""Read-only smoke check of frontend -> proxy -> API -> synthetic ML.

Run from the repository root: python -m scripts.check_integration --base-url URL
This checks wiring only, not model quality or real-data readiness.
"""
import argparse
import json
import sys
from urllib.error import URLError
from urllib.request import urlopen

from ml.adapter import predict_for_api_v1


def check(base_url: str) -> None:
    def get(path: str) -> bytes:
        with urlopen(base_url.rstrip("/") + path, timeout=10) as response:
            return response.read()

    if b'id="root"' not in get("/"):
        raise ValueError("Frontend HTML does not contain the React root")
    if json.loads(get("/api/v1/health")) != {"status": "ok"}:
        raise ValueError("Unexpected health response through frontend proxy")
    if json.loads(get("/api/v1/forecast")) != predict_for_api_v1():
        raise ValueError("Forecast through frontend proxy differs from this checkout's ML")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="Frontend URL, e.g. http://127.0.0.1:5173")
    args = parser.parse_args()
    try:
        check(args.base_url)
    except (URLError, OSError, ValueError) as exc:
        print(f"Integration smoke FAILED: {exc}", file=sys.stderr)
        return 1
    print("Frontend, proxy, API and ML agree. Synthetic mode only; real forecast readiness is unverified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
