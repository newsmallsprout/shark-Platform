import json
import os
from .models import MonitorConfig

CONFIG_DIR = "configs"
CONFIG_FILE = os.path.join(CONFIG_DIR, "monitor.json")

def load_monitor_config() -> MonitorConfig:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return MonitorConfig(**data)
        except Exception:
            return MonitorConfig()
    legacy = "monitor_config.json"
    if os.path.exists(legacy):
        try:
            with open(legacy, "r", encoding="utf-8") as f:
                data = json.load(f)
                return MonitorConfig(**data)
        except Exception:
            return MonitorConfig()
    try:
        return MonitorConfig()
    except Exception:
        return MonitorConfig()

def save_monitor_config(cfg: MonitorConfig):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        f.write(cfg.model_dump_json(indent=2))
