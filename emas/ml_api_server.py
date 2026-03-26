import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from xgboost import Booster


ARTIFACT_DIR = Path(os.getenv("ML_ARTIFACT_DIR", "ml_artifacts"))


class PredictRequest(BaseModel):
    job_id: str
    product_id: str
    job_priority: Optional[str] = None

    material_shortage_count: int = 0
    sub_product_shortage_count: int = 0
    can_start_now: Optional[bool] = None

    # Optional time features (RFC3339 strings)
    now: Optional[str] = None
    deadline: Optional[str] = None
    estimated_completion: Optional[str] = None

    snapshot_machine_ids: List[str] = Field(default_factory=list)
    queue_lengths_vector: List[int] = Field(default_factory=list)
    machine_utilization_vector: List[float] = Field(default_factory=list)


class PredictResponse(BaseModel):
    probability_of_delay: float
    delay_severity: str
    predicted_delay_minutes: int
    model_version: str
    latency_ms: float


def _severity_from_minutes(m: float) -> str:
    if m <= 0:
        return "Low"
    if m <= 60:
        return "Medium"
    return "High"


@dataclass
class FeatureSchema:
    feature_cols: list[str]
    priority_levels: list[str]
    version: str


def _load_schema() -> FeatureSchema:
    p = ARTIFACT_DIR / "feature_schema.json"
    if not p.exists():
        raise FileNotFoundError(f"missing {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    return FeatureSchema(
        feature_cols=data["feature_cols"],
        priority_levels=data.get("priority_levels", ["low", "medium", "high", "urgent"]),
        version=data.get("version", "xgb-unknown"),
    )


def _load_booster(path: Path) -> Booster:
    if not path.exists():
        raise FileNotFoundError(f"missing {path}")
    b = Booster()
    b.load_model(str(path))
    return b


def _vector_aggregates(queue_vec: list[int], util_vec: list[float]) -> tuple[int, float]:
    max_q = int(max(queue_vec)) if queue_vec else 0
    mean_u = float(np.mean(util_vec)) if util_vec else 0.0
    if not np.isfinite(mean_u) or mean_u < 0:
        mean_u = 0.0
    return max_q, mean_u


def _priority_one_hot(priority: str, levels: list[str]) -> dict[str, int]:
    p = (priority or "").strip().lower()
    return {f"priority_{lvl}": (1 if p == lvl else 0) for lvl in levels}


def build_feature_row(req: PredictRequest, schema: FeatureSchema) -> dict:
    # Minimal feature set aligned to training (keep inference fast).
    max_q, mean_u = _vector_aggregates(req.queue_lengths_vector, req.machine_utilization_vector)

    base = {
        "material_shortage_count": int(req.material_shortage_count or 0),
        "queue_length": int(max_q),  # job-level proxy: max queue length
        "max_queue_len": int(max_q),
        "mean_util_24h": float(mean_u),
        "minutes_to_deadline": 0.0,
        "minutes_after_deadline_at_plan": 0.0,
    }
    base.update(_priority_one_hot(req.job_priority or "", schema.priority_levels))

    # Ensure all expected columns exist
    for col in schema.feature_cols:
        base.setdefault(col, 0)
    return {k: base[k] for k in schema.feature_cols}


app = FastAPI(title="eMas ML Risk API", version="1.0")


@app.on_event("startup")
def _startup():
    global _schema, _delay_booster, _mins_booster
    _schema = _load_schema()
    _delay_booster = _load_booster(ARTIFACT_DIR / "model_delay.json")
    _mins_booster = _load_booster(ARTIFACT_DIR / "model_delay_minutes.json")


@app.get("/health")
def health():
    return {
        "ok": True,
        "model_version": getattr(_schema, "version", "unknown"),
        "artifact_dir": str(ARTIFACT_DIR),
    }


@app.post("/predict-delay-risk", response_model=PredictResponse)
def predict(req: PredictRequest):
    t0 = time.perf_counter()
    try:
        row = build_feature_row(req, _schema)
        x = np.array([[row[c] for c in _schema.feature_cols]], dtype=np.float32)
        # Booster expects DMatrix; use xgboost.DMatrix via Booster.inplace_predict
        p = float(_delay_booster.inplace_predict(x)[0])
        p = max(0.0, min(1.0, p))
        pred_mins = float(_mins_booster.inplace_predict(x)[0])
        if not np.isfinite(pred_mins):
            pred_mins = 0.0
        pred_mins = max(0.0, pred_mins)
        sev = _severity_from_minutes(pred_mins)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return PredictResponse(
            probability_of_delay=p,
            delay_severity=sev,
            predicted_delay_minutes=int(round(pred_mins)),
            model_version=_schema.version,
            latency_ms=latency_ms,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"prediction_failed: {e}")

