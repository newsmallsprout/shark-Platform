# app/main.py
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from app.api.routes import router
from app.api.monitor_routes import router as monitor_router
from app.sync.task_manager import task_manager
from app.monitor.engine import monitor_engine
from app.core.cdn_cache import ensure_vendor_assets

app = FastAPI(title="MySQL to Mongo Syncer (Versioning + SoftDelete, Package Layout)")

app.mount("/ui", StaticFiles(directory="static"), name="static")

@app.get("/")
async def root():
    return RedirectResponse(url="/ui/index.html")

app.include_router(router)
app.include_router(monitor_router, prefix="/monitor", tags=["monitor"])

@app.on_event("startup")
def startup_restore_tasks():
    ensure_vendor_assets()
    # 启动时恢复 configs/ 下的任务
    task_manager.restore_from_disk()
    # 启动监控
    monitor_engine.start()

@app.on_event("shutdown")
def shutdown_event():
    monitor_engine.stop()
