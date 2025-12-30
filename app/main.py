import threading
import time
import json
import os
import glob
import pymysql
import datetime
from datetime import date, datetime as dt
from pymongo import MongoClient
from pymongo.write_concern import WriteConcern
from bson.decimal128 import Decimal128
from decimal import Decimal
from pymysql.cursors import SSDictCursor
from pymysqlreplication import BinLogStreamReader
from pymysqlreplication.row_event import (
    DeleteRowsEvent,
    UpdateRowsEvent,
    WriteRowsEvent,
)
from fastapi import FastAPI
from pydantic import BaseModel, Field
from typing import Optional, Dict, List
from urllib.parse import quote_plus


def log(task_id: str, msg: str):
    print(f"[{task_id}] {msg}", flush=True)


app = FastAPI(title="MySQL to Mongo Syncer (Insert-Only)")

STATE_DIR = "state"
TASK_CONFIG_DIR = "configs"
os.makedirs(STATE_DIR, exist_ok=True)
os.makedirs(TASK_CONFIG_DIR, exist_ok=True)

active_tasks = {}


# ---------------- Models ----------------
class DBConfig(BaseModel):
    host: Optional[str] = None
    port: Optional[int] = None
    user: str
    password: str
    database: Optional[str] = None
    replica_set: Optional[str] = None
    hosts: Optional[List[str]] = None


class SyncTaskRequest(BaseModel):
    task_id: str
    mysql_conf: DBConfig
    mongo_conf: DBConfig
    table_map: Dict[str, str] = Field(default_factory=dict)
    pk_field: str = "id"
    collection_suffix: str = ""
    progress_interval: int = 10


# ---------------- Persistence ----------------
def save_task_config(config: SyncTaskRequest):
    with open(os.path.join(TASK_CONFIG_DIR, f"{config.task_id}.json"), "w") as f:
        f.write(config.json())


def delete_task_config(task_id: str):
    p = os.path.join(TASK_CONFIG_DIR, f"{task_id}.json")
    if os.path.exists(p):
        os.remove(p)


def load_state(task_id: str):
    p = os.path.join(STATE_DIR, f"{task_id}.json")
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    return None


def save_state(task_id: str, log_file: str, log_pos: int):
    with open(os.path.join(STATE_DIR, f"{task_id}.json"), "w") as f:
        json.dump({"log_file": log_file, "log_pos": log_pos}, f)


# ---------------- Mongo URI ----------------
def build_mongo_uri(m: DBConfig) -> str:
    u = quote_plus(m.user)
    p = quote_plus(m.password)
    db = m.database or "sync_db"

    if m.hosts and m.replica_set:
        hosts = ",".join(m.hosts)
        rs = quote_plus(m.replica_set)
        return (
            f"mongodb://{u}:{p}@{hosts}/{db}"
            f"?replicaSet={rs}&retryWrites=true"
            f"&authSource=admin&authMechanism=SCRAM-SHA-256"
        )

    host = m.host or "localhost"
    port = int(m.port or 27017)
    return (
        f"mongodb://{u}:{p}@{host}:{port}/{db}"
        f"?retryWrites=true&authSource=admin&authMechanism=SCRAM-SHA-256"
    )


# ================= Worker =================
class SyncWorker:
    def __init__(self, cfg: SyncTaskRequest):
        self.cfg = cfg
        self.running = True

        self.mysql_settings = {
            "host": cfg.mysql_conf.host,
            "port": int(cfg.mysql_conf.port or 3306),
            "user": cfg.mysql_conf.user,
            "passwd": cfg.mysql_conf.password,
            "db": cfg.mysql_conf.database,
            "ssl": {"ssl": True},
            "charset": "utf8mb4",
        }

        mongo_uri = build_mongo_uri(cfg.mongo_conf)
        self.mongo = MongoClient(mongo_uri)
        self.mongo_db = self.mongo[cfg.mongo_conf.database or "sync_db"]

    # ---------- helpers ----------
    def _convert_decimal(self, obj):
        if isinstance(obj, Decimal):
            return Decimal128(obj)
        if isinstance(obj, dt):
            return obj
        if isinstance(obj, date):
            return dt(obj.year, obj.month, obj.day)
        if isinstance(obj, dict):
            return {k: self._convert_decimal(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._convert_decimal(v) for v in obj]
        return obj

    def _strip_pk(self, row: dict):
        pk = self.cfg.pk_field.lower()
        return {k: v for k, v in row.items() if k.lower() != pk}

    def _count_table_rows(self, table: str) -> int:
        conn = pymysql.connect(**self.mysql_settings)
        try:
            with conn.cursor() as c:
                c.execute(f"SELECT COUNT(*) FROM `{table}`")
                return c.fetchone()[0]
        finally:
            conn.close()

    # ---------- lifecycle ----------
    def run(self):
        log(self.cfg.task_id, "Task started")
        try:
            self._auto_build_table_map_if_needed()
            state = load_state(self.cfg.task_id)

            if not state:
                log(self.cfg.task_id, "Run -> FullSync")
                self.do_full_sync()
            else:
                log(self.cfg.task_id, f"Run -> IncSync {state}")
                self.do_inc_sync(state["log_file"], state["log_pos"])
        except Exception as e:
            log(self.cfg.task_id, f"CRASH: {e}")

    def _auto_build_table_map_if_needed(self):
        if self.cfg.table_map:
            return
        conn = pymysql.connect(**self.mysql_settings)
        try:
            with conn.cursor() as c:
                c.execute("SHOW FULL TABLES WHERE Table_type='BASE TABLE'")
                tables = [r[0] for r in c.fetchall()]
                self.cfg.table_map = {
                    t: t + self.cfg.collection_suffix for t in tables
                }
        finally:
            conn.close()

    # ---------- Full Sync (BATCH WRITE) ----------
    def do_full_sync(self):
        batch = 1000          # MySQL batch
        mongo_batch = 1000    # Mongo insert_many size
        pk = self.cfg.pk_field

        conn = pymysql.connect(**self.mysql_settings, cursorclass=SSDictCursor)
        try:
            with conn.cursor() as c:
                for table, coll_name in self.cfg.table_map.items():
                    # FullSync 使用更快的 write concern
                    coll = self.mongo_db.get_collection(
                        coll_name,
                        write_concern=WriteConcern(w=1, j=False),
                    )

                    total = self._count_table_rows(table)
                    processed = 0
                    last_id = 0
                    buffer = []

                    start = time.time()
                    last_log = start

                    log(self.cfg.task_id, f"Table start: {table}, total={total}")

                    while self.running:
                        c.execute(
                            f"SELECT * FROM `{table}` "
                            f"WHERE `{pk}` > %s ORDER BY `{pk}` LIMIT %s",
                            (last_id, batch),
                        )
                        rows = c.fetchall()
                        if not rows:
                            break

                        for r in rows:
                            if pk in r:
                                last_id = r[pk]

                            doc = self._convert_decimal(self._strip_pk(r))
                            buffer.append(doc)
                            processed += 1

                            if len(buffer) >= mongo_batch:
                                coll.insert_many(buffer, ordered=False)
                                buffer.clear()

                        now = time.time()
                        if now - last_log >= self.cfg.progress_interval:
                            speed = int(processed / (now - start))
                            pct = round(processed * 100 / total, 2) if total else 0
                            log(
                                self.cfg.task_id,
                                f"Prog: t={table} "
                                f"done={processed}/{total} "
                                f"{pct}% sp={speed} row/s"
                            )
                            last_log = now

                    if buffer:
                        coll.insert_many(buffer, ordered=False)
                        buffer.clear()

                    log(
                        self.cfg.task_id,
                        f"Table done: {table}, inserted={processed}"
                    )
        finally:
            conn.close()

    # ---------- Incremental (SAFE) ----------
    def do_inc_sync(self, log_file, log_pos):
        stream = BinLogStreamReader(
            connection_settings=self.mysql_settings,
            server_id=100 + int(time.time() % 100),
            log_file=log_file,
            log_pos=log_pos,
            blocking=True,
            resume_stream=True,
            only_events=[WriteRowsEvent, UpdateRowsEvent, DeleteRowsEvent],
        )

        for ev in stream:
            if not self.running:
                break

            table = ev.table
            if table not in self.cfg.table_map:
                continue

            coll = self.mongo_db[self.cfg.table_map[table]]

            for row in ev.rows:
                if isinstance(ev, WriteRowsEvent):
                    data = row.get("values")
                elif isinstance(ev, UpdateRowsEvent):
                    data = row.get("after_values")
                else:
                    continue

                if data:
                    doc = self._convert_decimal(self._strip_pk(data))
                    coll.insert_one(doc)

            save_state(self.cfg.task_id, stream.log_file, stream.log_pos)

    def stop(self):
        self.running = False


# ---------------- API ----------------
def run_worker_thread(cfg: SyncTaskRequest):
    w = SyncWorker(cfg)
    active_tasks[cfg.task_id] = w
    threading.Thread(target=w.run, daemon=True).start()


@app.on_event("startup")
def startup_restore_tasks():
    for p in glob.glob(os.path.join(TASK_CONFIG_DIR, "*.json")):
        with open(p) as f:
            run_worker_thread(SyncTaskRequest(**json.load(f)))


@app.post("/tasks/start")
def start_task(cfg: SyncTaskRequest):
    save_task_config(cfg)
    run_worker_thread(cfg)
    return {"msg": "started"}


@app.post("/tasks/stop/{task_id}")
def stop_task(task_id: str):
    delete_task_config(task_id)
    if task_id in active_tasks:
        active_tasks[task_id].stop()
        del active_tasks[task_id]
    return {"msg": "stopped"}


@app.get("/")
def root():
    return {"tasks": list(active_tasks.keys())}