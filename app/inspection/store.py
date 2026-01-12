import json
import os
from app.inspection.models import InspectionConfig

CONFIG_FILE = os.path.join("configs", "inspection.json")

def load_inspection_config() -> InspectionConfig:
    if not os.path.exists(CONFIG_FILE):
        return InspectionConfig()
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return InspectionConfig(**data)
    except Exception:
        return InspectionConfig()

def save_inspection_config(cfg: InspectionConfig):
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        f.write(cfg.model_dump_json(indent=2))
