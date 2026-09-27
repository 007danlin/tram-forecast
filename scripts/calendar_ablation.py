"""One fixed, past-only B2 calendar ablation; never replaces the accepted model.

Run with the inference pins, e.g. python -m scripts.calendar_ablation
--dataset-dir /path/dataset --output-dir artifacts/calendar-ablation-new.
Both arms retain hour/dow/month/week, weekend, seasonal sin/cos and interactions.
Only the seven external holiday/transfer columns are removed in the off arm.
"""
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import time
from unittest.mock import patch

import numpy as np
import pandas as pd
import sklearn
from threadpoolctl import threadpool_limits

from ml import model
from ml.data import load_organizer_labels
from ml.factors import HOLIDAY_MODEL_COLUMNS, official_calendar_2025
from ml.settings import MODELED_ROUTES, RANDOM_SEED


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def metrics(frame, column):
    y = frame.boardings.to_numpy(dtype=np.int64)
    pred = np.floor(frame[column].to_numpy(dtype=float) + 0.5).astype(np.int64)
    sae, total = int(np.abs(y - pred).sum()), int(y.sum())
    return {"rows": len(frame), "sae": sae, "sum_y": total,
            "score": max(0., 1 - sae / total) if total else None}


def summarize(frame):
    groups = {"all": frame}
    for key in ("fold", "route", "day_type", "horizon"):
        groups.update({f"{key}/{name}": part for name, part in frame.groupby(key)})
    result = {}
    for name, part in groups.items():
        on, off = metrics(part, "calendar_on"), metrics(part, "calendar_off")
        result[name] = {"on": on, "off": off, "delta_on_minus_off":
                        on["score"] - off["score"] if on["score"] is not None else None}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=False)
    config = json.loads(Path("ml/experiments/score-v3.json").read_text())
    folds = [*config["folds"], config["diagnostic"]]
    source_paths = [Path("scripts/calendar_ablation.py"), *sorted(Path("ml").glob("*.py")), Path("ml/experiments/score-v3.json"), Path("ml/requirements-inference.txt")]
    protocol = {"registered_at_utc": datetime.now(timezone.utc).isoformat(),
                "kind": "new_controlled_fit_not_original_training_provenance",
                "folds": folds, "removed_features": list(HOLIDAY_MODEL_COLUMNS),
                "retained": "hour/dow/month/week/is_weekend, route interactions, day_of_year_sin/cos",
                "seed": RANDOM_SEED, "threads": 2,
                "parameters": model.CalendarInteractionEnsembleModel().parameter_manifest,
                "component_early_stopping": "auto (unchanged)",
                "rounding": "floor(float + 0.5) once after fixed ensemble",
                "decision": "Report both signs and all slices; no model selection, no new submission; S overlap and D is reused.",
                "source_hashes": {str(p): sha(p) for p in source_paths},
                "input_hashes": {str(p.relative_to(args.dataset_dir)): sha(p) for p in [args.dataset_dir / "README.md", *sorted((args.dataset_dir / "labels").glob("*.csv"))]},
                "environment": {"python": platform.python_version(), "sklearn": sklearn.__version__, "numpy": np.__version__, "pandas": pd.__version__}}
    (out / "protocol.json").write_text(json.dumps(protocol, indent=2) + "\n")
    history = load_organizer_labels(args.dataset_dir, "2025-01-01", "2025-10-31")
    calendar = official_calendar_2025()
    calendar["day_type"] = np.select(
        [calendar.is_public_holiday.eq(1) | calendar.is_transferred_day_off.eq(1), calendar.is_working_weekend.eq(1), calendar.is_day_off.eq(1)],
        ["holiday_or_transfer", "working_weekend", "weekend"], default="workday")
    all_rows = []
    with threadpool_limits(limits=2):
        for fold in folds:
            train = history[history.date.between(fold["train_start"], fold["train_end"])].copy()
            target = history[history.date.between(fold["start"], fold["end"]) & history.route.isin(MODELED_ROUTES)].copy()
            assert train.timestamp.max() < target.timestamp.min()
            rows = target[["route", "date", "hour", "boardings"]].copy()
            for arm in ("on", "off"):
                started = time.perf_counter()
                with ExitStack() as context:
                    if arm == "off":
                        context.enter_context(patch.object(model, "HOLIDAY_MODEL_COLUMNS", ()))
                        context.enter_context(patch.object(model, "INTERACTION_NUMERIC_COLUMNS", ("day_of_year_sin", "day_of_year_cos")))
                    fitted = model.CalendarInteractionEnsembleModel().fit(train)
                    pred = fitted.predict(fold["start"], fold["end"])
                    # The off arm has no holiday input to either estimator.
                    if arm == "off":
                        assert not set(HOLIDAY_MODEL_COLUMNS) & set(fitted.interaction_model_.pipeline_.feature_names_in_)
                        assert not set(HOLIDAY_MODEL_COLUMNS) & set(fitted.calendar_model_.pipeline_.named_steps["preprocessing"].transformers_[1][2])
                    pred = pred[pred.route.isin(MODELED_ROUTES)]
                    assert np.isfinite(pred.prediction).all() and pred.prediction.ge(0).all()
                    rows = rows.merge(pred[["route", "date", "hour", "prediction"]].rename(columns={"prediction": f"calendar_{arm}"}), on=["route", "date", "hour"], validate="one_to_one")
                print(f"{fold['id']} calendar_{arm}: {time.perf_counter() - started:.2f}s", flush=True)
            assert len(rows) == 9 * 61 * 24
            rows["fold"], rows["origin"] = fold["id"], fold["train_end"]
            rows["h"] = (rows.date - pd.Timestamp(fold["train_end"])).dt.days
            rows["horizon"] = np.where(rows.h <= 30, "1-30", "31-61")
            rows = rows.merge(calendar[["date", "day_type"]], on="date", validate="many_to_one")
            assert len(rows) == 13176
            rows.to_csv(out / f"{fold['id']}-oof.csv", index=False)
            all_rows.append(rows)
    combined = pd.concat(all_rows, ignore_index=True)
    assert not combined.duplicated(["fold", "route", "date", "hour"]).any()
    result = {"protocol_sha256": sha(out / "protocol.json"),
              "selection": summarize(combined[combined.fold.ne("D")]),
              "reused_diagnostic": summarize(combined[combined.fold.eq("D")]),
              "unchanged_source": all(sha(p) == digest for p, digest in protocol["source_hashes"].items()),
              "oof_sha256": {p.name: sha(p) for p in out.glob("*-oof.csv")}}
    assert result["unchanged_source"]
    (out / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"selection": result["selection"]["all"], "D": result["reused_diagnostic"]["all"]}), flush=True)


if __name__ == "__main__":
    main()
