from fastapi import APIRouter, HTTPException, Query
from typing import Literal
from app.inspection.models import InspectionRequest, InspectionReport, InspectionConfig
from app.inspection.service import inspection_service
from app.inspection import report_store
from app.inspection.store import load_inspection_config, save_inspection_config

router = APIRouter()

@router.get("/config")
def get_inspection_config():
    cfg = load_inspection_config()
    # Mask sensitive
    if cfg.ark_api_key:
        cfg.ark_api_key = "" 
    return cfg

@router.post("/config")
def update_inspection_config(cfg: InspectionConfig):
    old_cfg = load_inspection_config()
    # Merge sensitive if empty
    if not cfg.ark_api_key and old_cfg.ark_api_key:
        cfg.ark_api_key = old_cfg.ark_api_key
        
    save_inspection_config(cfg)
    return {"status": "ok"}

@router.post("/run", response_model=InspectionReport)
def run_inspection(req: InspectionRequest):
    """
    Trigger a system inspection using Prometheus data and AI analysis.
    """
    return inspection_service.run_inspection(req)


@router.get("/reports")
def list_reports(kind: Literal["daily", "weekly", "monthly"] = Query(default="daily"), limit: int = Query(default=30, ge=1, le=365)):
    items = report_store.list_reports(kind, limit=limit)
    return {"kind": kind, "items": items}


@router.get("/reports/{report_id}")
def get_report(report_id: str, kind: Literal["daily", "weekly", "monthly"] = Query(default="daily")):
    data = report_store.load_report(kind, report_id)
    if not data:
        raise HTTPException(status_code=404, detail="report not found")
    return data
