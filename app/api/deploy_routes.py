from fastapi import APIRouter, HTTPException
from typing import Dict, Any, Optional
from app.deploy.models import ServerConfig, DeployRequest
from app.deploy.store import save_server, list_servers, load_server, save_plan, list_plans, load_plan
from app.deploy.engine import deploy_engine

router = APIRouter()

@router.get("/servers")
def get_servers():
    return {"servers": list_servers()}

@router.post("/servers")
def save_server_config(cfg: ServerConfig):
    if cfg.auth_method == "key" and not cfg.key_path:
        raise HTTPException(status_code=400, detail="key_path is required for key auth")
    if cfg.auth_method == "password" and not cfg.password:
        raise HTTPException(status_code=400, detail="password is required for password auth")
    save_server(cfg)
    return {"status":"ok","id":cfg.id}

@router.get("/plans")
def get_plans():
    return {"plans": list_plans()}

@router.get("/plans/{plan_id}")
def get_plan(plan_id: str):
    p = load_plan(plan_id)
    if not p:
        raise HTTPException(status_code=404, detail="plan not found")
    return p

@router.post("/run")
def run_deploy(req: DeployRequest):
    if not req.server_ids:
        raise HTTPException(status_code=400, detail="server_ids required")
    for sid in req.server_ids:
        if not load_server(sid):
            raise HTTPException(status_code=404, detail=f"server {sid} not found")
    plan = deploy_engine.run(req)
    save_plan(plan)
    return {"status": plan.status, "plan": plan.model_dump()}
