# app/sync/mysql_introspector.py
import time
from typing import Dict, List, Optional, Any

import pymysql
from core.logging import log
from .convert import Converter


class MySQLIntrospector:
    def __init__(
        self,
        task_id: str,
        mysql_settings: dict,
        pk_field: str,
        unknown_col_fix_enabled: bool,
        unknown_col_schema_cache_sec: int,
        auto_discover_only_base_table: bool,
        converter,  # Converter，用于 convert_value
    ):
        self.task_id = task_id
        self.mysql_settings = mysql_settings
        self.pk_field = pk_field
        self._pk_lower = pk_field.lower()
        self.unknown_col_fix_enabled = unknown_col_fix_enabled
        self.unknown_col_schema_cache_sec = unknown_col_schema_cache_sec
        self.auto_discover_only_base_table = auto_discover_only_base_table
        self.converter = converter

        self._table_columns_cache: Dict[str, List[str]] = {}
        self._table_columns_cache_ts: Dict[str, float] = {}
        self._pk_index_cache: Dict[str, int] = {}
        self._pk_by_table: Dict[str, str] = {}
        self._pk_index_by_table: Dict[str, int] = {}

    def get_effective_pk(self, table: str) -> str:
        if table in self._pk_by_table:
            return self._pk_by_table[table]
        pk = None
        try:
            pk = self.get_primary_key(table)
        except Exception:
            pk = None
        pk = pk or self.pk_field
        self._pk_by_table[table] = pk
        return pk

    def _get_pk_index(self, table: str, pk_lower: str) -> Optional[int]:
        cache_key = f"{table}:{pk_lower}"
        if cache_key in self._pk_index_by_table:
            return self._pk_index_by_table[cache_key]
        cols = self.get_table_columns(table)
        if not cols:
            return None
        try:
            idx = [cc.lower() for cc in cols].index(pk_lower)
            self._pk_index_by_table[cache_key] = idx
            return idx
        except ValueError:
            return None

    def _connect(self):
        # introspector 读取 schema 不需要 SSDictCursor
        settings = {k: v for k, v in self.mysql_settings.items() if k != "cursorclass"}
        return pymysql.connect(**settings)

    def list_tables(self) -> List[str]:
        conn = self._connect()
        try:
            with conn.cursor() as c:
                if self.auto_discover_only_base_table:
                    c.execute("SHOW FULL TABLES WHERE Table_type='BASE TABLE'")
                    rows = c.fetchall()
                    log(self.task_id, f"Introspector list_tables(BASE): found {len(rows)} tables")
                    return [r[0] for r in rows]
                c.execute("SHOW TABLES")
                rows = c.fetchall()
                log(self.task_id, f"Introspector list_tables(ALL): found {len(rows)} tables")
                return [r[0] for r in rows]
        except Exception as e:
            log(self.task_id, f"Introspector list_tables failed: {e}")
            raise
        finally:
            conn.close()

    def get_primary_key(self, table: str) -> str:
        """
        Detects the primary key column name for the given table.
        If no primary key, returns None.
        If composite key, returns the first column (limitation).
        """
        conn = self._connect()
        try:
            with conn.cursor() as c:
                c.execute(f"SHOW KEYS FROM `{table}` WHERE Key_name = 'PRIMARY'")
                rows = c.fetchall()
                if rows:
                    # Column_name is usually the 5th column (index 4) in SHOW KEYS output
                    # But it's safer to map by description if possible.
                    # Standard SHOW KEYS returns: Table, Non_unique, Key_name, Seq_in_index, Column_name, ...
                    # Let's rely on index 4 for Column_name
                    return rows[0][4]
        except Exception:
            pass
        finally:
            conn.close()
        return None

    def get_table_columns(self, table: str) -> Optional[List[str]]:
        now = time.time()
        cache_sec = max(1, int(self.unknown_col_schema_cache_sec or 30))
        if table in self._table_columns_cache and now - self._table_columns_cache_ts.get(table, 0) < cache_sec:
            return self._table_columns_cache[table]

        conn = self._connect()
        try:
            with conn.cursor() as c:
                c.execute(f"SHOW COLUMNS FROM `{table}`")
                rows = c.fetchall()
                cols = [r[0] for r in rows]
                if cols:
                    self._table_columns_cache[table] = cols
                    self._table_columns_cache_ts[table] = now
                return cols
        finally:
            conn.close()

    def fix_unknown_cols(self, table: str, row: dict) -> dict:
        if not self.unknown_col_fix_enabled:
            return row
        cols = self.get_table_columns(table)
        if not cols:
            return row
        new_row = {}
        for k, v in row.items():
            if isinstance(k, str) and k.startswith("UNKNOWN_COL"):
                try:
                    idx = int(k.replace("UNKNOWN_COL", ""))
                    if 0 <= idx < len(cols):
                        new_row[cols[idx]] = v
                    else:
                        new_row[k] = v
                except Exception:
                    new_row[k] = v
            else:
                new_row[k] = v
        return new_row

    def maybe_fix_row_unknown_cols(self, table: str, data: Optional[dict]) -> Optional[dict]:
        if not data or not self.unknown_col_fix_enabled:
            return data
        for k in data.keys():
            if isinstance(k, str) and k.startswith("UNKNOWN_COL"):
                return self.fix_unknown_cols(table, data)
        return data

    def extract_pk(self, table: str, data: dict) -> Optional[Any]:
        pk_field = self.get_effective_pk(table)
        pk_lower = pk_field.lower()
        for kk, vv in data.items():
            if isinstance(kk, str) and kk.lower() == pk_lower:
                return self.converter.convert_value(vv)

        # 2) UNKNOWN_COL + pk index 兜底
        pk_idx = self._get_pk_index(table, pk_lower)
        if pk_idx is None:
            return None

        for kk, vv in data.items():
            if isinstance(kk, str) and kk.startswith("UNKNOWN_COL"):
                try:
                    idx = int(kk.replace("UNKNOWN_COL", ""))
                    if idx == pk_idx:
                        return self.converter.convert_value(vv)
                except Exception:
                    continue
        return None

    def refresh_table_map_if_needed(
        self,
        table_map: Dict[str, str],
        collection_suffix: str,
        auto_mode: bool,
        auto_discover_new_tables: bool,
        auto_discover_interval_sec: int,
        last_refresh_ts_holder: Dict[str, float],
        reason: str = "",
    ) -> List[str]:
        """
        last_refresh_ts_holder: {"ts": float} 作为可变引用，避免 worker 里堆字段
        Returns: list of newly added table names (for immediate full sync).
        """
        if (not auto_mode) or (not auto_discover_new_tables):
            return []

        now = time.time()
        interval = max(1, int(auto_discover_interval_sec or 10))
        if now - last_refresh_ts_holder.get("ts", 0.0) < interval:
            return []

        try:
            tables = self.list_tables()
            added = 0
            added_names = []
            for t in tables:
                if t not in table_map:
                    table_map[t] = t + collection_suffix
                    added += 1
                    added_names.append(t)
                    self._table_columns_cache.pop(t, None)
                    self._table_columns_cache_ts.pop(t, None)
                    self._pk_index_cache.pop(t, None)
                    self._pk_by_table.pop(t, None)
                    for k in list(self._pk_index_by_table.keys()):
                        if k.startswith(f"{t}:"):
                            self._pk_index_by_table.pop(k, None)
            last_refresh_ts_holder["ts"] = now
            if added > 0:
                log(self.task_id, f"Discovered new tables={added} reason={reason}: {added_names[:5]}...")
            return added_names
        except Exception as e:
            log(self.task_id, f"Refresh table_map failed: {str(e)[:180]}")
            return []
