from fastapi import APIRouter, HTTPException, BackgroundTasks
from app.monitor.models import MonitorConfig
from app.monitor.store import load_monitor_config, save_monitor_config
from app.monitor.engine import monitor_engine

router = APIRouter()

@router.get("/status")
def get_monitor_status():
    return monitor_engine.get_status()

@router.get("/config")
def get_monitor_config():
    cfg = load_monitor_config()
    # Mask sensitive fields so they must be re-entered on save
    cfg.es_password = ""
    cfg.slack_webhook_url = ""
    return cfg

@router.post("/config")
def update_monitor_config(cfg: MonitorConfig):
    # Load existing config to merge sensitive fields if empty
    old_cfg = load_monitor_config()

    if not cfg.slack_webhook_url and old_cfg.slack_webhook_url:
        cfg.slack_webhook_url = old_cfg.slack_webhook_url
    
    if not cfg.es_password and old_cfg.es_password:
        cfg.es_password = old_cfg.es_password

    # Optional: Enforce requirement only if truly empty
    # if not cfg.slack_webhook_url:
    #     raise HTTPException(status_code=400, detail="Slack Webhook URL is required")
        
    save_monitor_config(cfg)
    # Restart if running to apply changes
    monitor_engine.restart()
    return {"status": "ok", "message": "Config updated and monitor restarted"}

@router.post("/start")
def start_monitor():
    monitor_engine.start()
    return {"status": "ok", "message": "Monitor started"}

@router.post("/stop")
def stop_monitor():
    monitor_engine.stop()
    return {"status": "ok", "message": "Monitor stopped"}
