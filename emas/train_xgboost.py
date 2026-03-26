import argparse
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score, accuracy_score
from xgboost import XGBClassifier, XGBRegressor


PRIORITY_LEVELS = ["low", "medium", "high", "urgent"]


def _to_dt(v):
    if v is None or v == "":
        return None
    # Accept RFC3339-ish strings produced by Go (may include offset)
    return pd.to_datetime(v, utc=True, errors="coerce")


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def build_features(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    def _col(name: str) -> pd.Series:
        if name in df.columns:
            return df[name]
        return pd.Series([None] * len(df))

    # Time-aware features
    df["scheduled_start_dt"] = pd.to_datetime(_col("scheduled_start"), utc=True, errors="coerce")
    df["scheduled_end_dt"] = pd.to_datetime(_col("scheduled_end"), utc=True, errors="coerce")
    df["actual_end_dt"] = pd.to_datetime(_col("actual_end"), utc=True, errors="coerce")

    # Optional job_deadline if present (future-proof)
    df["job_deadline_dt"] = pd.to_datetime(_col("job_deadline"), utc=True, errors="coerce")

    # If no explicit job_deadline, approximate with scheduled_end + 0 for now
    # (Your Phase 1.5 JSONL currently does not include job_deadline)
    # This still allows learning from queue/material shortage signals.
    df["minutes_to_deadline"] = 0.0
    mask_deadline = df["job_deadline_dt"].notna() & df["scheduled_start_dt"].notna()
    df.loc[mask_deadline, "minutes_to_deadline"] = (
        (df.loc[mask_deadline, "job_deadline_dt"] - df.loc[mask_deadline, "scheduled_start_dt"]).dt.total_seconds()
        / 60.0
    )

    df["minutes_after_deadline_at_plan"] = 0.0
    mask_deadline2 = df["job_deadline_dt"].notna() & df["scheduled_end_dt"].notna()
    df.loc[mask_deadline2, "minutes_after_deadline_at_plan"] = np.maximum(
        0.0,
        (
            (df.loc[mask_deadline2, "scheduled_end_dt"] - df.loc[mask_deadline2, "job_deadline_dt"])
            .dt.total_seconds()
            / 60.0
        ),
    )

    # Snapshot vectors → aggregate features (keep inference fast)
    df["max_queue_len"] = df["queue_lengths_vector"].apply(lambda v: int(max(v)) if isinstance(v, list) and len(v) else 0)
    df["mean_util_24h"] = df["machine_utilization_vector"].apply(
        lambda v: float(np.mean(v)) if isinstance(v, list) and len(v) else 0.0
    )

    # Machine-specific queue length (already included by simulator)
    df["queue_length"] = _col("queue_length").fillna(0).astype(int)

    # Readiness proxy
    df["material_shortage_count"] = _col("material_shortage_count").fillna(0).astype(int)

    # Priority (optional in simulator output)
    df["priority"] = _col("job_priority").fillna("").astype(str).str.lower()
    for p in PRIORITY_LEVELS:
        df[f"priority_{p}"] = (df["priority"] == p).astype(int)

    feature_cols = [
        "material_shortage_count",
        "queue_length",
        "max_queue_len",
        "mean_util_24h",
        "minutes_to_deadline",
        "minutes_after_deadline_at_plan",
        *[f"priority_{p}" for p in PRIORITY_LEVELS],
    ]
    X = df[feature_cols].copy()
    schema = {
        "feature_cols": feature_cols,
        "priority_levels": PRIORITY_LEVELS,
        "version": "xgb-v1",
    }
    return X, schema


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="simulator_output/simulated_training.jsonl")
    ap.add_argument("--out", default="ml_artifacts")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    in_path = Path(args.input)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = load_jsonl(in_path)
    if not rows:
        raise SystemExit(f"no rows found in {in_path}")

    df = pd.DataFrame(rows)
    if "delay_minutes" not in df.columns:
        raise SystemExit("input data missing delay_minutes")

    # Targets
    df["delay_minutes"] = df["delay_minutes"].fillna(0).astype(int)
    y_delay = (df["delay_minutes"] > 0).astype(int)
    # If synthetic data ended up with only one class, fall back to a quantile-based label
    # so the classifier can still be trained (probability becomes "risk of higher delay").
    if y_delay.nunique() < 2:
        q = float(df["delay_minutes"].quantile(0.5))
        y_delay = (df["delay_minutes"] > q).astype(int)
    y_delay_mins = df["delay_minutes"].astype(float)

    X, schema = build_features(df)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y_delay, test_size=0.2, random_state=args.seed, stratify=y_delay
    )
    clf = XGBClassifier(
        n_estimators=250,
        max_depth=4,
        learning_rate=0.08,
        subsample=0.9,
        colsample_bytree=0.9,
        reg_lambda=1.0,
        objective="binary:logistic",
        n_jobs=0,
        random_state=args.seed,
        tree_method="hist",
    )
    clf.fit(X_train, y_train)
    p = clf.predict_proba(X_test)[:, 1]
    auc = float(roc_auc_score(y_test, p))
    acc = float(accuracy_score(y_test, (p >= 0.5).astype(int)))

    # Regressor for delay minutes (simple; helps derive severity buckets)
    Xr_train, Xr_test, yr_train, yr_test = train_test_split(
        X, y_delay_mins, test_size=0.2, random_state=args.seed
    )
    reg = XGBRegressor(
        n_estimators=250,
        max_depth=4,
        learning_rate=0.08,
        subsample=0.9,
        colsample_bytree=0.9,
        reg_lambda=1.0,
        objective="reg:squarederror",
        n_jobs=0,
        random_state=args.seed,
        tree_method="hist",
    )
    reg.fit(Xr_train, yr_train)

    # Save artifacts
    (out_dir / "model_delay.json").write_text(clf.get_booster().save_raw("json").decode("utf-8"), encoding="utf-8")
    (out_dir / "model_delay_minutes.json").write_text(reg.get_booster().save_raw("json").decode("utf-8"), encoding="utf-8")
    (out_dir / "feature_schema.json").write_text(json.dumps(schema, indent=2), encoding="utf-8")

    meta = {
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "input": str(in_path),
        "rows": int(len(df)),
        "metrics": {"delay_auc": auc, "delay_acc": acc},
        "model_version": schema["version"],
    }
    (out_dir / "metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()

