"""Measure the unchanged ML CLI inside Linux; reject any Python fit call.

Used only by the acceptance runner. The image's normal entry point is python -m ml.
"""

import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import resource
import runpy
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("command", choices=("forecast", "submission"))
    args, remainder = parser.parse_known_args()
    # Reserve the report before inference; never overwrite an existing report.
    with args.report.open("x", encoding="utf-8") as report_file:
        fit_attempts = []
        inference_calls = []
        started = time.perf_counter()

        def profile(frame, event, arg):
            module = frame.f_globals.get("__name__", "")
            function = frame.f_code.co_name
            if event == "call" and function in {"fit", "partial_fit", "fit_transform"} and module.startswith(("ml.", "sklearn.")):
                fit_attempts.append(f"{module}.{function}")
                raise RuntimeError("Training is forbidden during inference acceptance")
            if module == "ml.artifact" and function == "predict_artifact":
                if event == "call":
                    inference_calls.append({"started": time.perf_counter()})
                elif event == "return":
                    inference_calls[-1]["seconds"] = time.perf_counter() - inference_calls[-1].pop("started")

        exit_code = 1
        try:
            sys.argv = ["ml", args.command, *remainder]
            sys.setprofile(profile)
            try:
                runpy.run_module("ml", run_name="__main__")
                exit_code = 0
            except SystemExit as exc:
                exit_code = exc.code if isinstance(exc.code, int) else int(exc.code is not None)
                if exit_code:
                    raise
        finally:
            sys.setprofile(None)
            cgroup = {}
            for name in ("cpu.max", "memory.max", "memory.peak", "memory.swap.max", "memory.events"):
                path = Path("/sys/fs/cgroup") / name
                cgroup[name] = path.read_text().strip() if path.exists() else None
            report = {
                "exit_code": exit_code,
                "cli_wall_seconds": time.perf_counter() - started,
                "predict_artifact_calls": inference_calls,
                "process_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                "memory_method": "Linux getrusage ru_maxrss; cgroup v2 memory.peak separately (includes page cache)",
                "fit_attempts": fit_attempts,
                "python": platform.python_version(), "platform": platform.platform(),
                "machine": platform.machine(), "cpu_count_visible": os.cpu_count(),
                "thread_settings": {k: os.environ.get(k) for k in (
                    "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                    "NUMEXPR_NUM_THREADS", "LOKY_MAX_CPU_COUNT")},
                "dependencies": {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()},
                "cgroup": cgroup,
            }
            json.dump(report, report_file, indent=2, ensure_ascii=False)
            report_file.write("\n")


if __name__ == "__main__":
    main()
