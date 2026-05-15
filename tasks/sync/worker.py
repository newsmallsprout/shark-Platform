# app/sync/worker.py
import time
import random
import threading
import zlib
from typing import Optional, Dict, List, Any
import ssl as _ssl
from datetime import datetime as dt

import pymysql
from pymysql.cursors import SSDictCursor
from pymysql.err import OperationalError as MySQLOperationalError

from pymongo import MongoClient
from pymongo.write_concern import WriteConcern
from pymongo.operations import InsertOne, ReplaceOne, UpdateOne, UpdateMany
from bson import ObjectId

from pymysqlreplication import BinLogStreamReader
from pymysqlreplication.row_event import WriteRowsEvent, UpdateRowsEvent, DeleteRowsEvent

from tasks.schemas import SyncTaskRequest
from core.logging import log
from core.uri import build_mongo_uri
from tasks.utils import load_state, save_state
from .convert import Converter
from .mongo_writer import MongoWriter
from .mysql_introspector import MySQLIntrospector
from .flush_buffer import FlushBuffer
from queue import Queue
from .rate_limiter import RateLimiter


class SyncWorker:
    def __init__(self, cfg: SyncTaskRequest):
        self.cfg = cfg
        self.stop_event = threading.Event()
        self.stream: Optional[BinLogStreamReader] = None

        # --- mysql settings ---
        self.mysql_settings = {
            "host": cfg.mysql_conf.host,
            "port": int(cfg.mysql_conf.port or 3306),
            "user": cfg.mysql_conf.user,
            "passwd": cfg.mysql_conf.password,
            "db": cfg.mysql_conf.database,
            "charset": cfg.mysql_conf.charset,
            "cursorclass": SSDictCursor,
            "connect_timeout": int(cfg.mysql_connect_timeout or 10),
            "read_timeout": int(cfg.mysql_read_timeout or 60),
            "write_timeout": int(cfg.mysql_write_timeout or 60),
        }

        if cfg.mysql_conf.use_ssl:
            ssl_args = {}
            # If explicit certs provided, use them
            if cfg.mysql_conf.ssl_ca:
                ssl_args["ca"] = cfg.mysql_conf.ssl_ca
            if cfg.mysql_conf.ssl_cert:
                ssl_args["cert"] = cfg.mysql_conf.ssl_cert
            if cfg.mysql_conf.ssl_key:
                ssl_args["key"] = cfg.mysql_conf.ssl_key
            # If no certs provided, enable TLS without verification (server enforces secure transport)
            if not ssl_args:
                ssl_args = {}
            self.mysql_settings["ssl"] = ssl_args
        else:
            try:
                _kw = {k: v for k, v in self.mysql_settings.items() if k != "cursorclass"}
                c = pymysql.connect(**_kw)
                c.close()
            except Exception as e:
                s = str(e)
                if ("require_secure_transport" in s) or ("3159" in s) or ("Bad handshake" in s) or ("1043" in s):
                    self.mysql_settings["ssl"] = {}
        # Final fallback: ensure TLS handshake succeeds
        try:
            _kw = {k: v for k, v in self.mysql_settings.items() if k != "cursorclass"}
            c = pymysql.connect(**_kw)
            c.close()
        except Exception as e1:
            msg = str(e1)
            if ("require_secure_transport" in msg) or ("3159" in msg) or ("Bad handshake" in msg) or ("1043" in msg):
                for ssl_opt in ({}, {"fake_flag_to_enable_tls": True}, {"check_hostname": False, "verify_mode": _ssl.CERT_NONE}):
                    try:
                        self.mysql_settings["ssl"] = ssl_opt
                        _kw = {k: v for k, v in self.mysql_settings.items() if k != "cursorclass"}
                        c = pymysql.connect(**_kw)
                        c.close()
                        break
                    except Exception:
                        continue

        # --- mongo ---
        mongo_uri = build_mongo_uri(cfg.mongo_conf)
        self.mongo = MongoClient(
            mongo_uri,
            maxPoolSize=int(cfg.mongo_max_pool_size or 50),
            minPoolSize=0,
            connect=False,
            retryWrites=True,
            socketTimeoutMS=int(cfg.mongo_socket_timeout_ms or 20000),
            connectTimeoutMS=int(cfg.mongo_connect_timeout_ms or 10000),
            compressors=cfg.mongo_compressors or None,
        )
        self.mongo_db = self.mongo[cfg.mongo_conf.database or "sync_db"]

        # --- helper objects ---
        self.converter = Converter(cfg.pk_field, cfg.use_pk_as_mongo_id, dec_scale=18)
        self.mysql_introspector = MySQLIntrospector(
            task_id=cfg.task_id,
            mysql_settings=self.mysql_settings,
            pk_field=cfg.pk_field,
            unknown_col_fix_enabled=cfg.unknown_col_fix_enabled,
            unknown_col_schema_cache_sec=cfg.unknown_col_schema_cache_sec,
            auto_discover_only_base_table=cfg.auto_discover_only_base_table,
            converter=self.converter,
        )
        self.mongo_writer = MongoWriter(cfg.task_id, self.stop_event)
        self.rate = RateLimiter(cfg)
        self.shard_total = max(1, int(getattr(cfg, "shard_total", 1) or 1))
        self.shard_index = int(getattr(cfg, "shard_index", 0) or 0)

        # Redis fan-out: in Turbo multi-shard mode, one reader + N consumers
        self._sync_role = "default"  # default | reader | consumer
        self._redis_client = None
        if self.shard_total > 1:
            try:
                redis_url = os.environ.get("REDIS_URL") or os.environ.get("TRAFFIC_REDIS_URL") or ""
                if redis_url:
                    from .redis_bus import make_redis_client
                    self._redis_client = make_redis_client(redis_url)
                    self._sync_role = "reader" if self.shard_index == 0 else "consumer"
            except Exception:
                pass

        self._last_state_save_ts = 0.0
        self._last_progress_ts = 0.0

        self._auto_mode = (not bool(cfg.table_map))
        self._table_refresh_ts_holder = {"ts": 0.0}

        # Status tracking
        self._status = "initializing"
        self._metrics = {
            "phase": "init",
            "current_table": "",
            "processed_count": 0,
            "speed": 0,
            "binlog_file": "",
            "binlog_pos": 0,
            "last_update": time.time(),
            "insert_count": 0,
            "full_insert_count": 0,
            "inc_insert_count": 0,
            "update_count": 0,
            "delete_count": 0
        }

    def get_status(self) -> Dict[str, Any]:
        return {
            "task_id": self.cfg.task_id,
            "status": self._status,
            "metrics": self._metrics,
            "config": {
                "mysql": f"{self.cfg.mysql_conf.host}:{self.cfg.mysql_conf.port}",
                "mongo": f"{self.cfg.mongo_conf.host}:{self.cfg.mongo_conf.port}",
                "tables": list(self.cfg.table_map.keys()) if self.cfg.table_map else ["*"]
            }
        }

    def stop(self):
        self.stop_event.set()
        try:
            if self.stream is not None:
                self.stream.close()
        except Exception:
            pass

    # -------------------------
    # basic helpers
    # -------------------------
    def _maybe_save_state(self, log_file, log_pos):
        now = time.time()
        interval = max(1, int(self.cfg.state_save_interval_sec or 2))
        if now - self._last_state_save_ts >= interval:
            save_state(
                self.cfg.task_id,
                log_file,
                log_pos,
                self._metrics,
                shard_total=self.shard_total,
                shard_index=self.shard_index,
            )
            self._last_state_save_ts = now

    def _maybe_progress_log(self, msg: str):
        now = time.time()
        interval = max(1, int(self.cfg.progress_interval or 10))
        if now - self._last_progress_ts >= interval:
            log(self.cfg.task_id, msg)
            self._last_progress_ts = now

    def _auto_build_table_map_if_needed(self):
        # 修复逻辑：如果 table_map 包含 '*'，也应该强制进行自动发现
        is_wildcard = False
        if self.cfg.table_map:
            if "*" in self.cfg.table_map:
                is_wildcard = True
                log(self.cfg.task_id, "Found wildcard '*' in table_map, triggering auto-discovery...")
        
        if self.cfg.table_map and not is_wildcard:
            log(self.cfg.task_id, f"Using provided table_map size={len(self.cfg.table_map)}")
            return
            
        log(self.cfg.task_id, "Auto-building table map...")
        tables = self.mysql_introspector.list_tables()
        self.cfg.table_map = {t: t + self.cfg.collection_suffix for t in tables}
        log(self.cfg.task_id, f"Auto table_map built size={len(self.cfg.table_map)} tables={list(self.cfg.table_map.keys())[:5]}...")

    def _maybe_refresh_table_map(self, reason: str = ""):
        self.mysql_introspector.refresh_table_map_if_needed(
            table_map=self.cfg.table_map,
            collection_suffix=self.cfg.collection_suffix,
            auto_mode=self._auto_mode,
            auto_discover_new_tables=self.cfg.auto_discover_new_tables,
            auto_discover_interval_sec=self.cfg.auto_discover_interval_sec,
            last_refresh_ts_holder=self._table_refresh_ts_holder,
            reason=reason,
        )

    def _shard_match(self, pk_val: Any) -> bool:
        if self.shard_total <= 1:
            return True
        if pk_val is None:
            return False
        h = zlib.crc32(str(pk_val).encode("utf-8")) & 0xFFFFFFFF
        return (h % self.shard_total) == self.shard_index

    # =========================
    # 主流程
    # =========================
    def run(self):
        log(self.cfg.task_id, f"Task started (HardDelete={self.cfg.hard_delete})")
        self._status = "running"
        try:
            self._auto_build_table_map_if_needed()
            state = load_state(
                self.cfg.task_id, self.shard_total, self.shard_index
            )

            # Sharded turbo workers: one shard (0) runs full sync first,
            # then all shards start incremental from the captured binlog position.
            if self.shard_total > 1:
                has_position = bool(state and state.get("log_file"))
                if not has_position:
                    if self.shard_index == 0:
                        log(self.cfg.task_id, "Turbo shard=0: running full sync before incremental")
                        self._metrics["phase"] = "full_sync"
                        self.do_full_sync()
                        # Reload the position captured during full sync
                        state = load_state(
                            self.cfg.task_id, self.shard_total, self.shard_index
                        )
                        _bf = state.get("log_file")
                        _bp = state.get("log_pos")
                    else:
                        # Wait for shard 0 to finish full sync and save position
                        self._metrics["phase"] = "waiting_full_sync"
                        log(self.cfg.task_id, f"Turbo shard={self.shard_index}: waiting for shard 0 full sync...")
                        deadline = time.time() + max(300, int(self.cfg.inc_reconnect_backoff_max_sec or 300))
                        while not self.stop_event.is_set() and time.time() < deadline:
                            time.sleep(2)
                            state = load_state(
                                self.cfg.task_id, self.shard_total, self.shard_index
                            )
                            if state and state.get("log_file"):
                                break
                        if self.stop_event.is_set():
                            return
                        if not (state and state.get("log_file")):
                            log(self.cfg.task_id, "Turbo shard full-sync wait timed out; starting from latest binlog")
                        _bf = state.get("log_file") if state else None
                        _bp = state.get("log_pos") if state else None
                else:
                    _bf = self.cfg.binlog_filename or state.get("log_file")
                    _bp = self.cfg.binlog_position
                    if _bp is None:
                        _bp = state.get("log_pos")

                self._metrics["phase"] = "inc_sync"
                if self._sync_role == "consumer":
                    self.do_inc_sync_from_redis()
                else:
                    self.do_inc_sync_with_reconnect(_bf, _bp)
                return

            if not state or not state.get("log_file") or state.get("metrics", {}).get("phase") == "full_sync":
                # Check if specific binlog position provided in config
                if self.cfg.binlog_filename:
                    log(self.cfg.task_id, f"Starting IncSync from config: {self.cfg.binlog_filename}:{self.cfg.binlog_position}")
                    self._metrics["phase"] = "inc_sync"
                    self.do_inc_sync_with_reconnect(self.cfg.binlog_filename, self.cfg.binlog_position)
                else:
                    self._metrics["phase"] = "full_sync"
                    self.do_full_sync()
                    self._metrics["phase"] = "inc_sync"
                    self.do_inc_sync_with_reconnect(None, None)
            else:
                # Restore metrics if available
                if "metrics" in state and isinstance(state["metrics"], dict):
                    saved_metrics = state["metrics"]
                    for k in ["processed_count", "full_insert_count", "inc_insert_count", "update_count", "delete_count"]:
                        if k in saved_metrics:
                            self._metrics[k] = saved_metrics[k]

                self._metrics["phase"] = "inc_sync"
                self.do_inc_sync_with_reconnect(state.get("log_file"), state.get("log_pos"))
        except Exception as e:
            self._status = "error"
            self._metrics["error"] = str(e)
            log(self.cfg.task_id, f"CRASH {type(e).__name__}: {str(e)[:300]}")

    def do_full_sync(self):
        """
        全量同步写入 base 文档（_id=pk），使用 upsert，避免重复跑 11000。
        注意：全量阶段不会写 version 文档（version 只在 UPDATE 事件时产生）。
        """
        mysql_batch = int(self.cfg.mysql_fetch_batch or 2000)
        mongo_batch = int(self.cfg.mongo_bulk_batch or 2000)
        pk = self.cfg.pk_field
        write_concern = WriteConcern(w=int(self.cfg.mongo_write_w or 1), j=bool(self.cfg.mongo_write_j))

        if not self.cfg.table_map:
            log(self.cfg.task_id, "FullSync: table_map is empty, nothing to sync.")
            return

        # Full sync uses a plain DictCursor (buffered, no server-side cursor issues
        # with repeated SELECTs on the same connection). Binlog streaming still uses
        # SSDictCursor via self.mysql_settings in do_inc_sync_once.
        _full_kw = {k: v for k, v in self.mysql_settings.items() if k != "cursorclass"}
        conn = pymysql.connect(**_full_kw)
        try:
            # --- Diagnostic: verify which database we're connected to ---
            try:
                with conn.cursor() as c_diag:
                    c_diag.execute("SELECT DATABASE() AS db")
                    row = c_diag.fetchone()
                    actual_db = row.get("db", "UNKNOWN") if row else "UNKNOWN"
                    log(self.cfg.task_id,
                        f"FullSync MySQL: host={self.mysql_settings.get('host')}:{self.mysql_settings.get('port')} "
                        f"db_cfg={self.mysql_settings.get('db')!r} actual_db={actual_db}")
            except Exception as e:
                log(self.cfg.task_id, f"FullSync DB diag failed: {e}")

            # --- Capture Master Status at start of full sync ---
            start_log_file = None
            start_log_pos = None
            try:
                with conn.cursor() as c_status:
                    c_status.execute("SHOW MASTER STATUS")
                    ms = c_status.fetchone()
                    if ms:
                        start_log_file = ms.get("File")
                        start_log_pos = ms.get("Position")
                        self._metrics["full_sync_start_pos"] = f"{start_log_file}:{start_log_pos}"
                        log(self.cfg.task_id, f"FullSync started at binlog {start_log_file}:{start_log_pos}")
            except Exception as e:
                log(self.cfg.task_id, f"Warning: failed to get master status: {e}")

            with conn.cursor() as c:
                for table, coll_name in self.cfg.table_map.items():
                    if self.stop_event.is_set():
                        break

                    coll = self.mongo_db.get_collection(coll_name, write_concern=write_concern)
                    
                    if self.cfg.drop_target_before_full_sync:
                        try:
                            log(self.cfg.task_id, f"Dropping collection {coll_name} before full sync...")
                            coll.drop()
                        except Exception as e:
                            log(self.cfg.task_id, f"Drop collection {coll_name} failed: {e}")

                    processed = 0
                    last_id = None
                    ops: List = []
                    start = time.time()
                    log(self.cfg.task_id, f"FullSync table={table} -> collection={coll_name}")
                    
                    self._metrics["current_table"] = table
                    
                    # --- Auto Detect PK for this table ---
                    real_pk = self.cfg.pk_field
                    try:
                        detected_pk = self.mysql_introspector.get_primary_key(table)
                        if detected_pk:
                            real_pk = detected_pk
                    except Exception as e:
                        log(self.cfg.task_id, f"Auto detect PK failed for {table}: {e}")

                    log(self.cfg.task_id, f"FullSync table={table} pk={real_pk} -> collection={coll_name}")

                    q = Queue(maxsize=max(1, int(self.cfg.prefetch_queue_size or 2)))
                    def _producer():
                        nonlocal last_id
                        try:
                            while not self.stop_event.is_set():
                                if last_id is None:
                                    c.execute(f"SELECT * FROM `{table}` ORDER BY `{real_pk}` LIMIT %s", (mysql_batch,))
                                else:
                                    c.execute(
                                        f"SELECT * FROM `{table}` WHERE `{real_pk}` > %s ORDER BY `{real_pk}` LIMIT %s",
                                        (last_id, mysql_batch),
                                    )
                                rs = c.fetchall()
                                if not rs:
                                    break
                                q.put(rs)
                                last_id_local = last_id
                                for r in rs:
                                    if real_pk in r:
                                        last_id_local = r[real_pk]
                                last_id = last_id_local
                            q.put(None)
                        except Exception as e:
                            log(self.cfg.task_id, f"FullSync producer CRASH table={table} pk={real_pk}: {type(e).__name__}: {str(e)[:300]}")
                            try:
                                q.put(None)
                            except Exception:
                                pass
                    t = threading.Thread(target=_producer, daemon=True)
                    t.start()
                    fast_insert = False
                    if bool(self.cfg.full_sync_fast_insert_if_empty):
                        try:
                            fast_insert = coll.estimated_document_count() == 0
                        except Exception:
                            fast_insert = False
                    while not self.stop_event.is_set():
                        rows = q.get()
                        if rows is None:
                            break
                        if fast_insert and not self.cfg.use_pk_as_mongo_id:
                            docs = []
                            for r in rows:
                                d = self.converter.row_to_base_doc(r)
                                docs.append(d)
                                processed += 1
                                self._metrics["full_insert_count"] += 1
                            if docs:
                                try:
                                    _s = time.time()
                                    coll.insert_many(docs, ordered=False, bypass_document_validation=True)
                                    self.rate.update_write_stats(time.time() - _s, len(docs))
                                    self.rate.sleep_if_needed()
                                except Exception:
                                    for d in docs:
                                        ops.append(InsertOne(d))
                        else:
                            for r in rows:
                                if real_pk in r:
                                    last_id = r[real_pk]

                                doc = self.converter.row_to_base_doc(r)
                                if self.cfg.use_pk_as_mongo_id:
                                    pk_val = r.get(real_pk)
                                    if pk_val is None:
                                        for kk, vv in r.items():
                                            if isinstance(kk, str) and kk.lower() == str(real_pk).lower():
                                                pk_val = vv
                                                break
                                    if pk_val is not None:
                                        doc["_id"] = self.converter.convert_value(pk_val)
                                        ops.append(ReplaceOne({"_id": doc["_id"]}, doc, upsert=True))
                                    else:
                                        ops.append(InsertOne(doc))
                                else:
                                    ops.append(InsertOne(doc))

                                processed += 1
                                self._metrics["full_insert_count"] += 1
                                if len(ops) >= mongo_batch:
                                    _s = time.time()
                                    self.mongo_writer.safe_bulk_write(coll, ops, table, coll_name)
                                    self.rate.update_write_stats(time.time() - _s, len(ops))
                                    self.rate.sleep_if_needed()
                                    ops.clear()

                        self._metrics["processed_count"] = processed
                        self._maybe_progress_log(f"FullSync prog table={table} done={processed}")
                        if start_log_file and start_log_pos is not None:
                            self._maybe_save_state(start_log_file, start_log_pos)

                    if ops:
                        _s = time.time()
                        self.mongo_writer.safe_bulk_write(coll, ops, table, coll_name)
                        self.rate.update_write_stats(time.time() - _s, len(ops))
                        self.rate.sleep_if_needed()
                        ops.clear()

                    elapsed = max(1e-6, time.time() - start)
                    speed = int(processed / elapsed)
                    log(self.cfg.task_id, f"FullSync done table={table} count={processed} speed={speed}/s")
        finally:
            conn.close()

    def do_inc_sync_from_redis(self):
        """Turbo consumer mode: read binlog events from Redis queue (fan-out from shard 0 reader).

        This avoids N x MySQL binlog connections — only shard 0 connects to MySQL
        and publishes to Redis; all consumers read from Redis and apply shard filtering.
        """
        if not self._redis_client:
            log(self.cfg.task_id, "Consumer: no Redis client, falling back to direct MySQL binlog")
            self._sync_role = "reader"
            state = load_state(self.cfg.task_id, self.shard_total, self.shard_index) or {}
            self.do_inc_sync_with_reconnect(state.get("log_file"), state.get("log_pos"))
            return

        write_concern = WriteConcern(w=int(self.cfg.mongo_write_w or 1), j=bool(self.cfg.mongo_write_j))
        inc_batch = int(self.cfg.inc_flush_batch or 2000)
        flush_interval = max(1, int(self.cfg.inc_flush_interval_sec or 2))

        log(self.cfg.task_id,
            f"Turbo consumer shard={self.shard_index}/{self.shard_total}: "
            f"reading from Redis queue, batch={inc_batch} flush={flush_interval}s")

        def writer_func(coll_name: str, ops: List):
            coll = self.mongo_db.get_collection(coll_name, write_concern=write_concern)
            _s = time.time()
            self.mongo_writer.safe_bulk_write(coll, ops, table="*", coll_name=coll_name)
            self.rate.update_write_stats(time.time() - _s, len(ops))
            self.rate.sleep_if_needed()

        def on_flush_done():
            try:
                state = load_state(self.cfg.task_id, self.shard_total, self.shard_index) or {}
                lf = self._metrics.get("binlog_file") or state.get("log_file")
                lp = self._metrics.get("binlog_pos") or state.get("log_pos")
                self._maybe_save_state(lf, lp)
            except Exception:
                pass

        buf = FlushBuffer(
            batch_size=inc_batch,
            flush_interval_sec=flush_interval,
            writer_func=writer_func,
            on_flush_done=on_flush_done,
            stop_event=self.stop_event,
        )
        buf.start()

        try:
            from .redis_bus import consume_events, load_reader_position
            for ev in consume_events(self._redis_client, self.cfg.task_id, self.stop_event):
                ev_type = ev.get("type", "")
                table = ev.get("table", "")
                lf = ev.get("log_file")
                lp = ev.get("log_pos")

                self._metrics["binlog_file"] = lf or self._metrics.get("binlog_file", "")
                self._metrics["binlog_pos"] = lp or 0
                self._metrics["last_update"] = time.time()
                self._metrics["current_table"] = table or ""

                if self.cfg.debug_binlog_events:
                    log(self.cfg.task_id, f"REDIS-EV {ev_type} table={table}")

                if table not in self.cfg.table_map:
                    self._maybe_refresh_table_map(reason=f"unknown:{table}")
                    if table not in self.cfg.table_map:
                        continue

                coll_name = self.cfg.table_map[table]

                if ev_type == "WriteRowsEvent":
                    for row in ev.get("rows", []):
                        data = row.get("values")
                        if not data:
                            continue
                        data = self.mysql_introspector.maybe_fix_row_unknown_cols(table, data)
                        if not data:
                            continue
                        pk_val = self.mysql_introspector.extract_pk(table, data)
                        if not self._shard_match(pk_val):
                            continue
                        self._metrics["inc_insert_count"] += 1

                        doc = self.converter.row_to_base_doc(data)
                        if self.cfg.use_pk_as_mongo_id:
                            if pk_val is not None:
                                doc["_id"] = pk_val
                                buf.add(coll_name, ReplaceOne({"_id": doc["_id"]}, doc, upsert=True))
                            else:
                                buf.add(coll_name, InsertOne(doc))
                        else:
                            buf.add(coll_name, InsertOne(doc))

                elif ev_type == "UpdateRowsEvent":
                    for row in ev.get("rows", []):
                        data = row.get("after_values")
                        if not data:
                            continue
                        data = self.mysql_introspector.maybe_fix_row_unknown_cols(table, data)
                        if not data:
                            continue
                        pk_val = self.mysql_introspector.extract_pk(table, data)
                        if pk_val is None:
                            continue
                        if not self._shard_match(pk_val):
                            continue
                        self._metrics["update_count"] += 1

                        base_id = pk_val
                        if self.cfg.handle_updates_as_insert and not self.cfg.update_insert_new_doc:
                            doc = self.converter.row_to_base_doc(data)
                            buf.add(coll_name, InsertOne(doc))
                        else:
                            if self.cfg.update_insert_new_doc:
                                vdoc = self.converter.row_to_version_doc(data, pk_val=pk_val, base_id=base_id)
                                buf.add(coll_name, InsertOne(vdoc))
                            else:
                                doc = self.converter.row_to_base_doc(data)
                                if self.cfg.use_pk_as_mongo_id and "_id" in doc:
                                    buf.add(coll_name, ReplaceOne({"_id": doc["_id"]}, doc, upsert=True))
                                else:
                                    pk_field = self.cfg.pk_field
                                    buf.add(
                                        coll_name,
                                        UpdateOne(
                                            {pk_field: pk_val},
                                            {
                                                "$set": doc,
                                                "$setOnInsert": {"_id": ObjectId()},
                                                "$unset": {"_is_version": "", "_op": "", "_base_id": "", "_ts": ""},
                                            },
                                            upsert=True,
                                        ),
                                    )

                elif ev_type == "DeleteRowsEvent" and self.cfg.handle_deletes:
                    for row in ev.get("rows", []):
                        data = row.get("values")
                        if not data:
                            continue
                        data = self.mysql_introspector.maybe_fix_row_unknown_cols(table, data)
                        if not data:
                            continue
                        pk_val = self.mysql_introspector.extract_pk(table, data)
                        if pk_val is None:
                            continue
                        if not self._shard_match(pk_val):
                            continue
                        self._metrics["delete_count"] += 1

                        if self.cfg.delete_append_new_doc:
                            vdoc = self.converter.row_to_delete_doc(data, pk_val=pk_val, base_id=pk_val)
                            buf.add(coll_name, InsertOne(vdoc))
                        else:
                            set_doc = {
                                self.cfg.delete_flag_field: True,
                                self.cfg.delete_time_field: dt.utcnow(),
                                "_op": "delete",
                                "_ts": dt.utcnow(),
                            }
                            if self.cfg.delete_mark_only_base_doc:
                                buf.add(
                                    coll_name,
                                    UpdateOne({"_id": pk_val}, {"$set": set_doc}, upsert=self.cfg.delete_upsert_tombstone),
                                )
                            else:
                                buf.add(coll_name, UpdateMany({self.cfg.pk_field: pk_val}, {"$set": set_doc}, upsert=False))
                                buf.add(
                                    coll_name,
                                    UpdateOne({"_id": pk_val}, {"$set": set_doc}, upsert=self.cfg.delete_upsert_tombstone),
                                )

                try:
                    self._metrics["processed_count"] = (
                        int(self._metrics.get("full_insert_count") or 0)
                        + int(self._metrics.get("inc_insert_count") or 0)
                        + int(self._metrics.get("update_count") or 0)
                        + int(self._metrics.get("delete_count") or 0)
                    )
                except Exception:
                    pass

                buf.flush_if_reach_batch()
                buf.flush(force=False)

        finally:
            try:
                buf.stop()
            except Exception:
                pass
            log(self.cfg.task_id, "Turbo consumer IncSync stopped (redis)")

    def do_inc_sync_with_reconnect(self, log_file, log_pos):
        retry = 0
        backoff = float(self.cfg.inc_reconnect_backoff_base_sec or 1.0)
        backoff_max = float(self.cfg.inc_reconnect_backoff_max_sec or 30.0)

        state = (
            load_state(self.cfg.task_id, self.shard_total, self.shard_index) or {}
        )
        cur_log_file = log_file or state.get("log_file")
        cur_log_pos = log_pos if log_pos is not None else state.get("log_pos")

        while not self.stop_event.is_set():
            try:
                self.do_inc_sync_once(cur_log_file, cur_log_pos)
                break
            except MySQLOperationalError as e:
                # Treat operational errors (connection lost) as retriable
                retry += 1
                state = (
                    load_state(self.cfg.task_id, self.shard_total, self.shard_index)
                    or {}
                )
                cur_log_file = state.get("log_file", cur_log_file)
                cur_log_pos = state.get("log_pos", cur_log_pos)
                log(self.cfg.task_id, f"MySQL OpErr. retry={retry} err={str(e)[:200]}")
            except Exception as e:
                # For critical errors (e.g. invalid config, permission denied), STOP immediately
                s = str(e).lower()
                if self.stop_event.is_set() or "already closed" in s or "closed" in s:
                    log(self.cfg.task_id, "IncSync stopped by user or stream closed")
                    break
                
                # Check for non-recoverable SSL/Auth errors
                if ("access denied" in s) or ("password" in s) or ("ssl" in s and "handshake" in s):
                    log(self.cfg.task_id, f"CRITICAL ERROR: {str(e)} - Stopping task to avoid infinite loop.")
                    self._status = "error"
                    self._metrics["error"] = f"Critical error: {str(e)}"
                    break
                
                retry += 1
                state = (
                    load_state(self.cfg.task_id, self.shard_total, self.shard_index)
                    or {}
                )
                cur_log_file = state.get("log_file", cur_log_file)
                cur_log_pos = state.get("log_pos", cur_log_pos)
                log(self.cfg.task_id, f"IncSync crash. retry={retry} {type(e).__name__}: {str(e)[:200]}")

            max_retry = int(self.cfg.inc_reconnect_max_retry or 0)
            if max_retry > 0 and retry >= max_retry:
                log(self.cfg.task_id, "IncSync stopped after max retries")
                self._status = "error"
                break

            sleep_sec = min(backoff_max, backoff) + random.random() * 0.2
            log(self.cfg.task_id, f"Reconnect after {sleep_sec:.2f}s from {cur_log_file}:{cur_log_pos}")
            time.sleep(sleep_sec)
            backoff = min(backoff_max, backoff * 2)

    def do_inc_sync_once(self, log_file, log_pos):
        """
        增量语义（按你需求）：
        - INSERT：写 base 文档（_id=pk），用 upsert（幂等）
        - UPDATE：新增 version 文档（新 _id），不改 base
        - DELETE：只给 base 打删除标识（软删除）
        并且定时 flush：即使没有新事件，也会落库。
        """
        write_concern = WriteConcern(w=int(self.cfg.mongo_write_w or 1), j=bool(self.cfg.mongo_write_j))

        only_events = [WriteRowsEvent]
        if not self.cfg.insert_only:
            only_events.append(UpdateRowsEvent)
        if self.cfg.handle_deletes:
            only_events.append(DeleteRowsEvent)

        self.stream = BinLogStreamReader(
            connection_settings={k: v for k, v in self.mysql_settings.items() if k != "cursorclass"},
            server_id=100 + int(time.time() % 100) + random.randint(0, 1000),
            log_file=log_file,
            log_pos=log_pos,
            blocking=True,
            resume_stream=True,
            only_events=only_events,
        )

        inc_batch = int(self.cfg.inc_flush_batch or 2000)
        flush_interval = max(1, int(self.cfg.inc_flush_interval_sec or 2))

        log(self.cfg.task_id, f"IncSync connecting to MySQL {self.mysql_settings.get('host')}:{self.mysql_settings.get('port')}...")
        log(self.cfg.task_id, f"IncSync started events={[e.__name__ for e in only_events]} from={log_file}:{log_pos}")
        log(
            self.cfg.task_id,
            f"Mode: UPDATE->newDoc={self.cfg.update_insert_new_doc}, DELETE->softMarkBaseOnly={self.cfg.delete_mark_only_base_doc}, hard_delete={self.cfg.hard_delete}",
        )

        def writer_func(coll_name: str, ops: List):
            coll = self.mongo_db.get_collection(coll_name, write_concern=write_concern)
            _s = time.time()
            self.mongo_writer.safe_bulk_write(coll, ops, table="*", coll_name=coll_name)
            self.rate.update_write_stats(time.time() - _s, len(ops))
            self.rate.sleep_if_needed()

        def on_flush_done():
            try:
                self._maybe_save_state(getattr(self.stream, "log_file", None), getattr(self.stream, "log_pos", None))
            except Exception:
                pass

        buf = FlushBuffer(
            batch_size=inc_batch,
            flush_interval_sec=flush_interval,
            writer_func=writer_func,
            on_flush_done=on_flush_done,
            stop_event=self.stop_event,
        )
        buf.start()

        try:
            for ev in self.stream:
                if self.stop_event.is_set():
                    break
                
                # update metrics
                self._metrics["binlog_file"] = self.stream.log_file
                self._metrics["binlog_pos"] = self.stream.log_pos
                self._metrics["last_update"] = time.time()

                table = ev.table
                self._metrics["current_table"] = table or ""
                if self.cfg.debug_binlog_events:
                    log(self.cfg.task_id, f"EV {type(ev).__name__} table={table}")

                # Fan-out to Redis consumers (reader mode only)
                if self._sync_role == "reader" and self._redis_client:
                    try:
                        from .redis_bus import publish_event, save_reader_position
                        lf = self.stream.log_file
                        lp = self.stream.log_pos
                        save_reader_position(self._redis_client, self.cfg.task_id, lf, lp)
                        publish_event(
                            self._redis_client, self.cfg.task_id,
                            type(ev).__name__, table, lf, lp, ev.rows,
                        )
                    except Exception:
                        pass

                if table not in self.cfg.table_map:
                    self._maybe_refresh_table_map(reason=f"unknown:{table}")
                    if table not in self.cfg.table_map:
                        continue

                coll_name = self.cfg.table_map[table]

                # ---------------- Insert: base upsert ----------------
                if isinstance(ev, WriteRowsEvent):
                    for row in ev.rows:
                        data = row.get("values")
                        data = self.mysql_introspector.maybe_fix_row_unknown_cols(table, data)
                        if not data:
                            continue
                        pk_val = self.mysql_introspector.extract_pk(table, data)
                        if not self._shard_match(pk_val):
                            continue
                        self._metrics["inc_insert_count"] += 1

                        doc = self.converter.row_to_base_doc(data)
                        if self.cfg.use_pk_as_mongo_id:
                            if pk_val is not None:
                                doc["_id"] = pk_val
                                buf.add(coll_name, ReplaceOne({"_id": doc["_id"]}, doc, upsert=True))
                            else:
                                buf.add(coll_name, InsertOne(doc))
                        else:
                            buf.add(coll_name, InsertOne(doc))

                # ---------------- Update: new version doc ----------------
                elif isinstance(ev, UpdateRowsEvent):
                    for row in ev.rows:
                        data = row.get("after_values")
                        data = self.mysql_introspector.maybe_fix_row_unknown_cols(table, data)
                        if not data:
                            continue

                        pk_val = self.mysql_introspector.extract_pk(table, data)
                        if pk_val is None:
                            log(self.cfg.task_id, f"Update skipped (no pk) table={table} keys={list(data.keys())[:8]}")
                            continue
                        if not self._shard_match(pk_val):
                            continue
                        self._metrics["update_count"] += 1

                        base_id = pk_val  # use_pk_as_mongo_id 下 base _id=pk
                        if self.cfg.handle_updates_as_insert and not self.cfg.update_insert_new_doc:
                            # 兼容旧配置：update 当 insert（不推荐）
                            doc = self.converter.row_to_base_doc(data)
                            buf.add(coll_name, InsertOne(doc))
                        else:
                            if self.cfg.update_insert_new_doc:
                                vdoc = self.converter.row_to_version_doc(data, pk_val=pk_val, base_id=base_id)
                                buf.add(coll_name, InsertOne(vdoc))
                            else:
                                doc = self.converter.row_to_base_doc(data)
                                if self.cfg.use_pk_as_mongo_id and "_id" in doc:
                                    buf.add(coll_name, ReplaceOne({"_id": doc["_id"]}, doc, upsert=True))
                                else:
                                    # _id 保持 ObjectId，按 id 字段定位并原地更新（镜像模式）
                                    pk_field = self.cfg.pk_field
                                    buf.add(
                                        coll_name,
                                        UpdateOne(
                                            {pk_field: pk_val},
                                            {
                                                "$set": doc,
                                                "$setOnInsert": {"_id": ObjectId()},
                                                "$unset": {"_is_version": "", "_op": "", "_base_id": "", "_ts": ""},
                                            },
                                            upsert=True,
                                        ),
                                    )

                # ---------------- Delete: soft mark base doc only ----------------
                elif isinstance(ev, DeleteRowsEvent) and self.cfg.handle_deletes:
                    for row in ev.rows:
                        data = row.get("values")
                        data = self.mysql_introspector.maybe_fix_row_unknown_cols(table, data)
                        if not data:
                            continue

                        pk_val = self.mysql_introspector.extract_pk(table, data)
                        if pk_val is None:
                            log(self.cfg.task_id, f"Delete skipped (no pk) table={table} keys={list(data.keys())[:8]}")
                            continue
                        if not self._shard_match(pk_val):
                            continue
                        self._metrics["delete_count"] += 1

                        if self.cfg.delete_append_new_doc:
                            vdoc = self.converter.row_to_delete_doc(data, pk_val=pk_val, base_id=pk_val)
                            buf.add(coll_name, InsertOne(vdoc))
                        else:
                            set_doc = {
                                self.cfg.delete_flag_field: True,
                                self.cfg.delete_time_field: dt.utcnow(),
                                "_op": "delete",
                                "_ts": dt.utcnow(),
                            }
                            if self.cfg.delete_mark_only_base_doc:
                                buf.add(
                                    coll_name,
                                    UpdateOne({"_id": pk_val}, {"$set": set_doc}, upsert=self.cfg.delete_upsert_tombstone),
                                )
                            else:
                                buf.add(coll_name, UpdateMany({self.cfg.pk_field: pk_val}, {"$set": set_doc}, upsert=False))
                                buf.add(
                                    coll_name,
                                    UpdateOne({"_id": pk_val}, {"$set": set_doc}, upsert=self.cfg.delete_upsert_tombstone),
                                )

                try:
                    self._metrics["processed_count"] = (
                        int(self._metrics.get("full_insert_count") or 0)
                        + int(self._metrics.get("inc_insert_count") or 0)
                        + int(self._metrics.get("update_count") or 0)
                        + int(self._metrics.get("delete_count") or 0)
                    )
                except Exception:
                    pass

                buf.flush_if_reach_batch()
                buf.flush(force=False)

        finally:
            try:
                buf.stop()
            except Exception:
                pass

            try:
                if self.stream is not None:
                    try:
                        self._maybe_save_state(getattr(self.stream, "log_file", None), getattr(self.stream, "log_pos", None))
                    except Exception:
                        pass
                    self.stream.close()
            except Exception:
                pass

            log(self.cfg.task_id, "IncSync stopped (once)")
