"""B2 acceptance: prepare verified inputs, run isolated Docker CLI, then compare.

Only the Python standard library and the Docker CLI are needed on the host.
The run subcommand cannot receive reference forecasts. Comparison is a separate
process after all inference containers have exited and been removed.
"""

import argparse
import csv
from datetime import date, timedelta
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time


MODEL_FILES = {"model.joblib", "metadata.json", "feature-schema.json", "manifest.json"}
MODEL_SHA = "39edd75e265102f5973d14acd94bd4ae75a0473f12b7d07e47e2dc8b32eb9942"
SAMPLE_SHA = "71c8126bb51068c936462a170da885bad860fc91a58b3d2ac731876d324d7ec3"
SUBMISSION_SHA = "505039c95a6c7d9acfb84f9822be9c1427707a9e82ac8e1b03e0cadad8054e94"
FORECAST_SHA = "f60caf48d1ce5d5066eaa4c6e74dc34454648b372d715efb1ad2b735dbf3ac4c"
KEYS = ["route", "date", "hour"]
VALUES = ["prediction", "reference_value", "lower_90", "upper_90", "priority_score"]
FLOAT_COLUMNS = [*KEYS, *VALUES, "status"]
ROUTES = (1, 5, 7, 11, 12, 17, 25, 26, 28, 50)
DAYS = ("2025-11-01", "2025-11-15", "2025-12-31")


def sha(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8") as target:
        json.dump(value, target, ensure_ascii=False, indent=2, allow_nan=False)
        target.write("\n")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def regular(path):
    require(path.is_file() and not path.is_symlink(), f"Required regular file: {path}")
    return path


def inventory(root):
    return {p.relative_to(root).as_posix(): sha(regular(p))
            for p in sorted(root.rglob("*")) if not p.is_dir()}


def validate_model(root):
    require(root.is_dir() and not root.is_symlink(), "Model must be a regular directory")
    require({p.name for p in root.iterdir()} == MODEL_FILES, "Model directory must contain exactly four model files")
    manifest = json.loads(regular(root / "manifest.json").read_text())
    require(manifest.get("schema_version") == "tramflow-hourly-v1", "Unexpected model schema")
    require(set(manifest.get("files", {})) == MODEL_FILES - {"manifest.json"}, "Unexpected model manifest")
    for name, expected in manifest["files"].items():
        require(sha(regular(root / name)) == expected, f"Model checksum mismatch: {name}")
    require(sha(root / "model.joblib") == MODEL_SHA, "This protocol accepts only the documented B2")
    return inventory(root)


def prepare(args, report):
    root = args.g0.resolve()
    manifest = json.loads(regular(root / "bundle-manifest.json").read_text())
    require(isinstance(manifest.get("files"), dict) and manifest["files"], "Missing G0 file manifest")
    for name, expected in manifest["files"].items():
        path = root / name
        require(not Path(name).is_absolute() and ".." not in Path(name).parts
                and path.resolve().is_relative_to(root), "Unsafe G0 manifest path")
        require(sha(regular(path)) == expected, f"G0 checksum mismatch: {name}")
    report["g0_manifest_sha256"] = sha(root / "bundle-manifest.json")
    report["g0_files_verified"] = len(manifest["files"])
    validate_model(root / "model")
    for name, expected in (("template.csv", SAMPLE_SHA), ("champion.csv", SUBMISSION_SHA),
                           ("forecast-float.csv", FORECAST_SHA)):
        require(sha(regular(root / name)) == expected, f"B2 input/reference mismatch: {name}")
    out = args.output_dir
    shutil.copytree(root / "model", out / "model")
    (out / "input").mkdir()
    shutil.copyfile(root / "template.csv", out / "input/test_submission.csv")
    (out / "references").mkdir()
    for src, dst in (("champion.csv", "submission.csv"), ("forecast-float.csv", "forecast.csv")):
        shutil.copyfile(root / src, out / "references" / dst)
    report["files"] = inventory(out)


def read_csv(path, columns):
    with Path(path).open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter=";")
        require(reader.fieldnames == columns, f"Unexpected CSV columns: {path}")
        rows = list(reader)
    require(all(set(row) == set(columns) and all(v is not None for v in row.values()) for row in rows), "Malformed CSV rows")
    keys = [tuple(row[k] for k in KEYS) for row in rows]
    require(len(keys) == len(set(keys)), f"Duplicate keys: {path}")
    return rows


def write_csv(path, columns, rows):
    with path.open("x", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=columns, delimiter=";", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class DockerRunner:
    def __init__(self, root, image, report):
        self.root, self.image, self.report = root, image, report
        self.events = root / "commands"
        self.events.mkdir()
        report["commands"] = []
        report["containers"] = []

    def command(self, argv, *, check=True):
        number = len(self.report["commands"])
        prefix = self.events / f"{number:03d}"
        started = time.perf_counter()
        with prefix.with_suffix(".stdout").open("x") as stdout, prefix.with_suffix(".stderr").open("x") as stderr:
            result = subprocess.run(argv, stdout=stdout, stderr=stderr, timeout=300)
        record = {"argv": argv, "exit_code": result.returncode,
                  "wall_seconds": time.perf_counter() - started,
                  "stdout": prefix.with_suffix(".stdout").relative_to(self.root).as_posix(),
                  "stderr": prefix.with_suffix(".stderr").relative_to(self.root).as_posix()}
        self.report["commands"].append(record)
        write_json(prefix.with_suffix(".json"), record)
        if check:
            require(result.returncode == 0, f"Command failed ({result.returncode}): {argv}; see {prefix}.stderr")
        return record, prefix.with_suffix(".stdout").read_text(), prefix.with_suffix(".stderr").read_text()

    def infer(self, label, model, sample=None, *, day=None, failure=None, output=None):
        output = output or (self.root / label)
        # Every successful computation sees a fresh, empty leaf directory. Even
        # the forecast from the preceding call must not be visible to submission.
        output.mkdir(parents=True, exist_ok=failure is not None)
        is_submission = sample is not None
        command = "submission" if is_submission else "forecast"
        mounts = [(model, "/model", True), (output, "/output", False)]
        if sample is not None:
            mounts.append((sample, "/input/test_submission.csv", True))
        cli = [command, "--artifact-dir", "/model", "--output", f"/output/{command}.csv"]
        if is_submission:
            cli += ["--template", "/input/test_submission.csv", "--scope", "sample",
                    "--preflight-output", "/output/submission.preflight.json"]
        else:
            cli += ["--start", day or "2025-11-01", "--end", day or "2025-12-31"]
        argv = ["docker", "create", "--network", "none", "--cpus", "2", "--memory", "4g",
                "--memory-swap", "4g", "--read-only", "--tmpfs", "/tmp:rw,nosuid,size=64m",
                "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--entrypoint", "python"]
        for host, guest, readonly in mounts:
            require("," not in str(host), "Docker bind paths cannot contain commas")
            argv += ["--mount", f"type=bind,src={host},dst={guest}" + (",readonly" if readonly else "")]
        argv += [self.image, "-m", "ml.inference.measure", "--report", f"/output/{label}.metrics.json", *cli]
        created, stdout, _ = self.command(argv)
        cid = stdout.strip()
        try:
            _, before, _ = self.command(["docker", "inspect", cid])
            inspect = json.loads(before)[0]
            config = inspect["HostConfig"]
            actual_mounts = {(m["Source"], m["Destination"], not m["RW"]) for m in inspect["Mounts"]}
            require(actual_mounts == {(str(p), guest, ro) for p, guest, ro in mounts}, "Unexpected Docker mounts")
            require(config["NetworkMode"] == "none" and config["NanoCpus"] == 2_000_000_000
                    and config["Memory"] == config["MemorySwap"] == 4 * 1024**3, "Incorrect isolation/resource limits")
            started, stdout, stderr = self.command(["docker", "start", "--attach", cid], check=False)
            _, after, _ = self.command(["docker", "inspect", cid])
            state = json.loads(after)[0]["State"]
            measurement = json.loads((output / f"{label}.metrics.json").read_text())
            record = {"label": label, "id": cid, "cli": cli, "state": state,
                      "mounts": inspect["Mounts"], "host_config": config,
                      "create_seconds": created["wall_seconds"],
                      "start_attach_seconds": started["wall_seconds"], "metrics": measurement}
            self.report["containers"].append(record)
            require(not state["OOMKilled"] and not measurement["fit_attempts"], "OOM or forbidden training")
            if failure is None:
                require(started["exit_code"] == state["ExitCode"] == measurement["exit_code"] == 0, f"Inference failed: {label}; {stderr}")
            else:
                require(started["exit_code"] != 0 and state["ExitCode"] != 0 and measurement["exit_code"] != 0
                        and failure in stderr, f"Expected specific input rejection: {label}; {stderr}")
                preflight = output / "submission.preflight.json"
                if preflight.exists() and "exists" not in failure:
                    require(not json.loads(preflight.read_text()).get("passed"), "Invalid input produced successful preflight")
            print(f"{label}: accepted {'rejection' if failure else 'calculation'}", flush=True)
        finally:
            self.command(["docker", "rm", "--force", cid])
        return output


def run(args, report):
    original = args.model_dir.resolve()
    template = regular(args.template.resolve())
    before = {"model": validate_model(original), "template": sha(template)}
    require(before["template"] == SAMPLE_SHA, "Run requires the original organizer sample")
    root = args.output_dir.resolve()
    inputs = root / "inputs"
    inputs.mkdir()
    shutil.copytree(original, inputs / "model")
    shutil.copyfile(template, inputs / "test_submission.csv")
    model, sample = inputs / "model", inputs / "test_submission.csv"
    report["inputs_before"] = before
    runner = DockerRunner(root, args.image, report)
    _, image_info, _ = runner.command(["docker", "image", "inspect", args.image])
    report["image"] = json.loads(image_info)[0]
    # Resolve the mutable tag once; every computation uses the same immutable ID.
    runner.image = report["image"]["Id"]
    _, docker_info, _ = runner.command(["docker", "info", "--format", "{{json .}}"])
    report["docker_info"] = json.loads(docker_info)
    try:
        for number in (1, 2):
            runner.infer(f"forecast-{number}", model, output=root / f"run-{number}/forecast")
            runner.infer(f"submission-{number}", model, sample, output=root / f"run-{number}/submission")
        for day in DAYS:
            runner.infer(f"day-{day}", model, day=day)
        columns = [*KEYS, "prediction"]
        rows = read_csv(sample, columns)
        poisoned = inputs / "poisoned-sample.csv"
        write_csv(poisoned, columns, [dict(row, prediction=str(900000 + i)) for i, row in enumerate(rows)])
        runner.infer("poisoned-sample", model, poisoned)
        for name, mutation, message in (
            ("missing-model", "missing", "No such file"),
            ("corrupt-model", "model", "Artifact checksum mismatch"),
            ("corrupt-checksum", "manifest", "Artifact checksum mismatch"),
        ):
            broken = inputs / name
            shutil.copytree(model, broken)
            if mutation == "missing":
                (broken / "model.joblib").unlink()
            elif mutation == "model":
                with (broken / "model.joblib").open("ab") as f:
                    f.write(b"corruption test")
            else:
                manifest = json.loads((broken / "manifest.json").read_text())
                manifest["files"]["model.joblib"] = "0" * 64
                (broken / "manifest.json").write_text(json.dumps(manifest))
            runner.infer(name, broken, failure=message)
            require(not (root / name / "forecast.csv").exists(), "Invalid model produced a forecast")
        invalid = inputs / "invalid-sample.csv"
        write_csv(invalid, columns, [*rows, rows[0]])
        runner.infer("invalid-sample", model, invalid, failure="duplicate keys")
        require(not (root / "invalid-sample/submission.csv").exists(), "Invalid sample produced a submission")
        # Existing forecast, submission and preflight must all be protected.
        for kind in ("forecast", "submission", "preflight"):
            output = root / f"existing-{kind}"
            output.mkdir()
            protected = output / ("submission.preflight.json" if kind == "preflight" else f"{kind}.csv")
            protected.write_text('{"sentinel": true}\n')
            protected_sha = sha(protected)
            runner.infer(f"existing-{kind}", model, sample if kind != "forecast" else None,
                         output=output, failure="exists; choose")
            require(sha(protected) == protected_sha, "Existing output was modified")
        report["checks"] = {"two_full_runs": True, "three_days": True, "poisoned_template": True,
                            "invalid_model_and_sample_rejected": True, "outputs_protected": True}
    finally:
        report["inputs_after"] = {"model": validate_model(original), "template": sha(template)}
        report["staged_inputs_after"] = {"model": validate_model(model), "template": sha(sample)}
        report["outputs"] = {p.relative_to(root).as_posix(): sha(p) for p in sorted(root.rglob("*"))
                             if p.is_file() and p.suffix in {".csv", ".json"} and "commands" not in p.parts}
        require(before == report["inputs_after"] == report["staged_inputs_after"], "Model/sample changed during inference")


def compare_rows(actual, expected, values):
    def key(row):
        return tuple(row[k] for k in KEYS)
    left, right = {key(r): r for r in actual}, {key(r): r for r in expected}
    common = left.keys() & right.keys()
    numeric = {}
    examples = []
    for column in values:
        count, max_abs, max_rel, zero_reference_differences = 0, Decimal(0), Decimal(0), 0
        for k in sorted(common):
            a, b = Decimal(left[k][column]), Decimal(right[k][column])
            require(a.is_finite() and b.is_finite(), "Non-finite forecast")
            if a != b:
                count += 1
                error = abs(a - b)
                max_abs = max(max_abs, error)
                if b:
                    max_rel = max(max_rel, error / abs(b))
                else:
                    zero_reference_differences += 1
                if len(examples) < 20:
                    examples.append({"key": k, "column": column, "actual": str(a), "reference": str(b)})
        numeric[column] = {"different": count, "max_absolute_error": str(max_abs),
                           "max_relative_error_nonzero_reference": str(max_rel),
                           "zero_reference_differences": zero_reference_differences}
    statuses = sum(left[k].get("status") != right[k].get("status") for k in common)
    keys_match = left.keys() == right.keys()
    return {"actual_rows": len(actual), "expected_rows": len(expected), "keys_equal": keys_match,
            "order_equal": [key(r) for r in actual] == [key(r) for r in expected],
            "status_differences": statuses, "numeric": numeric, "examples": examples,
            "numeric_equal": keys_match and statuses == 0 and all(v["different"] == 0 for v in numeric.values())}


def compare(args, report):
    root = args.run_dir.resolve()
    receipt = json.loads((root / "report.json").read_text())
    require(receipt.get("passed") is True and receipt.get("stage") == "run", "Inference run did not pass")
    for name, expected in receipt["outputs"].items():
        path = root / name
        require(path.resolve().is_relative_to(root) and sha(regular(path)) == expected, f"Output changed since inference: {name}")
    reference_forecast, reference_submission = args.reference_forecast, args.reference_submission
    require(sha(reference_forecast) == FORECAST_SHA, "Reference float is not accepted B2")
    require(sha(reference_submission) == SUBMISSION_SHA, "Reference submission is not accepted B2")
    report["references"] = {"forecast": FORECAST_SHA, "submission": SUBMISSION_SHA, "model": MODEL_SHA}
    expected_float = read_csv(reference_forecast, FLOAT_COLUMNS)
    expected_ds = read_csv(reference_submission, [*KEYS, "prediction"])
    comparisons = {}
    passed = True
    for number in (1, 2):
        for filename, columns, expected, values in (
            ("forecast", FLOAT_COLUMNS, expected_float, VALUES),
            ("submission", [*KEYS, "prediction"], expected_ds, ["prediction"]),
        ):
            path = root / f"run-{number}/{filename}/{filename}.csv"
            item = compare_rows(read_csv(path, columns), expected, values)
            item.update(sha256=sha(path), byte_equal=sha(path) == (FORECAST_SHA if filename == "forecast" else SUBMISSION_SHA))
            comparisons[f"run-{number}/{filename}"] = item
            passed &= item["byte_equal"] and item["numeric_equal"] and item["order_equal"]
        preflight = json.loads((root / f"run-{number}/submission/submission.preflight.json").read_text())
        require(preflight["passed"] and preflight["sha256"] == sha(root / f"run-{number}/submission/submission.csv"), "Preflight failed or stale")
    full = read_csv(root / "run-1/forecast/forecast.csv", FLOAT_COLUMNS)
    grid = {(str(route), (date(2025, 11, 1) + timedelta(days=d)).isoformat(), str(h))
            for route in ROUTES for d in range(61) for h in range(24)}
    require({tuple(r[k] for k in KEYS) for r in full} == grid, "Incomplete full forecast grid")
    report["rows"] = len(full)
    zeros = [r for r in full if r["route"] == "5"]
    require(len(zeros) == 1464 and all(float(r["prediction"]) == 0 and r["status"] == "cold_start_zero_baseline" for r in zeros), "Route 5 fallback mismatch")
    report["route_5_zero_rows"] = len(zeros)
    ds = read_csv(root / "run-1/submission/submission.csv", [*KEYS, "prediction"])
    by_key = {tuple(r[k] for k in KEYS): r for r in full}
    rounding_differences = sum(Decimal(r["prediction"]) != math.floor(float(by_key[tuple(r[k] for k in KEYS)]["prediction"]) + 0.5) for r in ds)
    report["rounding_differences"] = rounding_differences
    passed &= rounding_differences == 0
    for day in DAYS:
        rows = read_csv(root / f"day-{day}/forecast.csv", FLOAT_COLUMNS)
        item = compare_rows(rows, [r for r in full if r["date"] == day], VALUES)
        comparisons[f"day-{day}"] = item
        passed &= len(rows) == 240 and item["numeric_equal"] and item["order_equal"]
    report["repeat_hashes_equal"] = all(sha(root / f"run-1/{n}/{n}.csv") == sha(root / f"run-2/{n}/{n}.csv") for n in ("forecast", "submission"))
    report["poisoned_sample_submission_equal"] = sha(root / "poisoned-sample/submission.csv") == sha(root / "run-1/submission/submission.csv")
    report["poisoned_sample_preflight_passed"] = json.loads((root / "poisoned-sample/submission.preflight.json").read_text())["passed"]
    report["comparisons"] = comparisons
    report["float_tolerance"] = "none: exact bytes and exact numeric values required"
    require(passed and report["repeat_hashes_equal"] and report["poisoned_sample_submission_equal"]
            and report["poisoned_sample_preflight_passed"], "B2 reproduction differs; see comparisons (no tolerance applied)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="stage", required=True)
    p = sub.add_parser("prepare", help="Validate all G0 hashes and separate inputs from references")
    p.add_argument("--g0", required=True, type=Path)
    p = sub.add_parser("run", help="Isolated inference and negative checks; no reference input")
    p.add_argument("--image", required=True)
    p.add_argument("--model-dir", required=True, type=Path)
    p.add_argument("--template", required=True, type=Path)
    p = sub.add_parser("compare", help="Independent exact comparison after inference")
    p.add_argument("--run-dir", required=True, type=Path)
    p.add_argument("--reference-forecast", required=True, type=Path)
    p.add_argument("--reference-submission", required=True, type=Path)
    for p in sub.choices.values():
        p.add_argument("--output-dir", required=True, type=Path, help="New directory; never overwritten")
    args = parser.parse_args()
    # A reused output path is rejected before any writes, including report writes.
    args.output_dir.mkdir(parents=True, exist_ok=False)
    report = {"schema": "tramflow-container-inference-v1", "stage": args.stage,
              "passed": False, "argv": sys.argv, "host": platform.platform()}
    try:
        {"prepare": prepare, "run": run, "compare": compare}[args.stage](args, report)
        report["passed"] = True
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        report["error"] = str(exc)
        print(str(exc), file=sys.stderr)
    finally:
        write_json(args.output_dir / "report.json", report)
    print(json.dumps({"stage": args.stage, "passed": report["passed"], "report": str(args.output_dir / "report.json")}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
