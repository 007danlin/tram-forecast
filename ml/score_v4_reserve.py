"""Two recorded reserve hypotheses evaluated from existing component fits."""

import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from ml.score_improvement import assert_same_tasks
from ml.score_v4 import official_day_type, sha256_file
from ml.score_v4_study import _load_baseline
from ml.settings import KEY_COLUMNS


def run(root: Path, baseline_root: Path) -> None:
    config_path = Path("ml/experiments/score-v4-reserve.json")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    output = root / "reserve"
    output.mkdir(exist_ok=False)
    (output / "preregistered-config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    control = _load_baseline(baseline_root)
    baseline = control["B2"]
    fitted_root = root / "protocol-repair" if (root / "protocol-repair").exists() else root
    parts = []
    with threadpool_limits(limits=4):
        for fold, frame in baseline.groupby("fold", sort=True):
            model = joblib.load(fitted_root / "folds" / "B2-cal" / fold / "model.joblib")
            part = frame.copy()
            part["calendar_prediction"] = model._predict_component(frame[list(KEY_COLUMNS)], "calendar")
            parts.append(part)
    combined = pd.concat(parts, ignore_index=True)
    assert_same_tasks(combined, baseline)
    first = baseline.copy()
    first["prediction"] = .96 * (.425 * combined.calendar_prediction.to_numpy(float) + .575 * control["B1"].prediction.to_numpy(float))
    first["status"] = "reserve_calendar_only_day_type"
    second = baseline.copy()
    special = official_day_type(second).eq("holiday")
    second.loc[special, "prediction"] = first.loc[special, "prediction"]
    second["status"] = np.where(special, "reserve_calendar_holiday_only", "incumbent")
    hashes = {}
    for name, frame in (("R1", first), ("R2", second)):
        path = output / f"{name}-oof.csv"
        frame.to_csv(path, index=False, encoding="utf-8", lineterminator="\n")
        hashes[name] = sha256_file(path)
    (output / "record.json").write_text(json.dumps({"config_sha256": sha256_file(config_path), "oof_sha256": hashes}, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--study-root", type=Path, default=Path("artifacts/score-v4-20260926-r01"))
    parser.add_argument("--baseline-root", type=Path, default=Path("artifacts/score-v3-20260926-r02"))
    args = parser.parse_args()
    run(args.study_root, args.baseline_root)
