"""New-process checks and aggregate diagnostics for the completed v4 study."""

import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from ml.artifact import submission_preflight
from ml.data import load_organizer_labels
from ml.factors import add_official_calendar_features
from ml.score_improvement import guardrail, metrics
from ml.score_v4 import attach_origin_features, internal_origins, origin_grid_audit, official_day_type, sha256_file
from ml.score_v4_study import _load_baseline, _outer_components
from ml.settings import KEY_COLUMNS, MODELED_ROUTES, TARGET_COLUMN


def run(dataset: Path, root: Path, baseline_root: Path, champion_root: Path) -> dict:
    config = json.loads(Path("ml/experiments/score-v4.json").read_text(encoding="utf-8"))
    result = json.loads((root / "complete.json").read_text(encoding="utf-8"))
    labels = load_organizer_labels(dataset, "2025-01-01", "2025-10-31", routes=MODELED_ROUTES)
    baseline = _load_baseline(baseline_root)
    model_checks, coverage, grids, components = [], {}, {}, {}
    ab_root = root / "protocol-repair" if (root / "protocol-repair").exists() else root
    with threadpool_limits(limits=4):
        for fold in config["folds"]:
            history = labels[labels.date.le(fold["train_end"])].copy()
            outer = _outer_components(baseline, fold["id"])
            calendar = add_official_calendar_features(history)
            coverage[fold["id"]] = {
                "day_type_hour_rows": official_day_type(history).value_counts().to_dict(),
                "working_saturday_hour_rows": int(calendar.is_working_weekend.sum()),
                "zero_calendar_columns": [name for name in ("is_working_weekend",) if not calendar[name].any()],
            }
            grids[fold["id"]] = {"A": origin_grid_audit(internal_origins(history, config["internal_oof"]), 61, history.date.max())}
            for experiment_id in ("A1", "A2", "B1", "B2-cal", "D1", "D2"):
                model_root = (root / "direct-full" if experiment_id.startswith("D") else ab_root) / "folds" / experiment_id / fold["id"]
                model_path = model_root / "model.joblib"
                record = json.loads((model_root / "record.json").read_text(encoding="utf-8"))
                if sha256_file(model_path) != record["model_sha256"]:
                    raise ValueError(f"Model checksum failed: {model_path}")
                model = joblib.load(model_path)
                saved = pd.read_csv(model_root / "oof.csv", parse_dates=["date"], float_precision="round_trip")
                if experiment_id in ("A1", "A2"):
                    # Full labels deliberately supplied: helper must discard dates after origin.
                    featured = attach_origin_features(outer, labels, down=config["a1"]["state_down"], up=config["a1"]["state_up"])
                    prediction = featured.b2.to_numpy(float) * model.predict_factor(featured) if experiment_id == "A1" else model.predict(featured)
                else:
                    forecast = model.predict(fold["start"], fold["end"])
                    aligned = saved[list(KEY_COLUMNS)].merge(forecast[[*KEY_COLUMNS, "prediction"]], on=list(KEY_COLUMNS), validate="one_to_one")
                    prediction = aligned.prediction.to_numpy(float)
                    if experiment_id.startswith("D"):
                        grid = origin_grid_audit(model._origins(history), 61, history.date.max())
                        grid["weighting"] = getattr(model, "horizon_weight_audit_", None)
                        grids[fold["id"]][experiment_id] = grid
                    else:
                        rows = saved[list(KEY_COLUMNS)].copy()
                        for component in ("calendar", "interaction"):
                            part = saved.copy()
                            part["prediction"] = model._predict_component(rows, component)
                            components.setdefault(f"{experiment_id}/{component}", []).append(part)
                max_difference = float(np.abs(prediction - saved.prediction.to_numpy(float)).max())
                if max_difference > 1e-10:
                    raise ValueError(f"Serialized inference mismatch: {experiment_id}/{fold['id']} = {max_difference}")
                model_checks.append({"id": experiment_id, "fold": fold["id"], "model_sha256": record["model_sha256"], "max_abs_difference": max_difference})
    component_metrics = {key: metrics(pd.concat(parts, ignore_index=True)) for key, parts in components.items()}
    for component, control in (("calendar", "B0"), ("interaction", "B1")):
        component_metrics[f"incumbent/{component}"] = metrics(baseline[control])

    best = {**result["standalone"], **result["fixed_blends"]}[result["selection"]["best_measured_new_id"]]
    best_frame = pd.read_csv(best["oof_path"], parse_dates=["date"], float_precision="round_trip")
    without_route = {}
    for route in MODELED_ROUTES:
        mask = best_frame.route.ne(route)
        without_route[str(route)] = metrics(best_frame[mask])["score"] - metrics(baseline["B2"][mask])["score"]

    # Reproduce the six already observed, out-of-budget blends for disclosure.
    # These were evaluated by an ad-hoc command before choosing B2-cal/C1.
    # They are not eligible and are not a new search.
    deviations = {}
    for candidate in ("N1", "D2"):
        frame = pd.read_csv(result["standalone"][candidate]["oof_path"], parse_dates=["date"], float_precision="round_trip")
        for weight in config["blend_weights"]:
            blend = baseline["B2"].copy()
            blend["prediction"] = (1 - weight) * blend.prediction + weight * frame.prediction
            deviations[f"B2+{weight:g}-{candidate}"] = {
                "metrics": metrics(blend), "admission": guardrail(blend, baseline["B2"], config["thresholds"]),
                "status": "protocol_deviation_excluded_from_selection",
            }
    champion_hashes = {name: sha256_file(champion_root / name) for name in ("champion.csv", "forecast-float.csv", "model/model.joblib")}
    if champion_hashes["champion.csv"] != result["baseline"]["competition_csv_sha256"]:
        raise ValueError("Champion CSV changed")
    preflight = submission_preflight(champion_root / "champion.csv", dataset / "test_submission.csv", scope="sample")
    audit = {
        "schema": "score-v4-audit", "new_process_serialization": model_checks,
        "origin_grids": grids, "calendar_coverage": coverage,
        "isolated_component_metrics": component_metrics,
        "best_blend_delta_excluding_each_route": without_route,
        "extra_blends_protocol_deviation": deviations,
        "champion_hashes": champion_hashes, "champion_preflight": preflight,
        "D_and_stress_not_evaluated_in_v4": True,
    }
    (root / "audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return audit


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--study-root", type=Path, default=Path("artifacts/score-v4-20260926-r01"))
    parser.add_argument("--baseline-root", type=Path, default=Path("artifacts/score-v3-20260926-r02"))
    parser.add_argument("--champion-root", type=Path, default=Path("artifacts/champion-b2-g0-g2-20260926-final-v2"))
    args = parser.parse_args()
    result = run(args.dataset_dir, args.study_root, args.baseline_root, args.champion_root)
    print(json.dumps({"model_checks": len(result["new_process_serialization"]), "champion_hashes": result["champion_hashes"]}))
