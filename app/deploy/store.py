import os
import json
from typing import Dict, Optional, List
from app.deploy.models import ServerConfig, DeployPlan

DEPLOY_DIR = "configs/deploy"
ARTIFACT_DIR = "deploy_artifacts"
os.makedirs(DEPLOY_DIR, exist_ok=True)
os.makedirs(ARTIFACT_DIR, exist_ok=True)

def _server_path(sid: str) -> str:
    return os.path.join(DEPLOY_DIR, f"server_{sid}.json")

def _plan_path(pid: str) -> str:
    return os.path.join(DEPLOY_DIR, f"plan_{pid}.json")

def save_server(cfg: ServerConfig):
    with open(_server_path(cfg.id), "w", encoding="utf-8") as f:
        f.write(cfg.model_dump_json(indent=2))

def load_server(sid: str) -> Optional[Dict]:
    p = _server_path(sid)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)

def list_servers() -> List[Dict]:
    res = []
    for name in os.listdir(DEPLOY_DIR):
        if name.startswith("server_") and name.endswith(".json"):
            with open(os.path.join(DEPLOY_DIR, name), encoding="utf-8") as f:
                res.append(json.load(f))
    return res

def save_plan(plan: DeployPlan):
    with open(_plan_path(plan.id), "w", encoding="utf-8") as f:
        f.write(plan.model_dump_json(indent=2))

def load_plan(pid: str) -> Optional[Dict]:
    p = _plan_path(pid)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)

def list_plans() -> List[Dict]:
    res = []
    for name in os.listdir(DEPLOY_DIR):
        if name.startswith("plan_") and name.endswith(".json"):
            with open(os.path.join(DEPLOY_DIR, name), encoding="utf-8") as f:
                res.append(json.load(f))
    return res

def artifact_path(task_id: str, filename: str) -> str:
    base = os.path.join(ARTIFACT_DIR, task_id)
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, filename)
