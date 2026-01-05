import os
import re
import json
import ssl
import certifi
import hashlib
import warnings
import urllib.request
import time
import threading
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List

from elasticsearch import Elasticsearch
from urllib3.exceptions import InsecureRequestWarning

from app.core.logging import log
from app.monitor.models import MonitorConfig
from app.monitor.store import load_monitor_config

warnings.filterwarnings("ignore", category=InsecureRequestWarning)
warnings.filterwarnings("ignore", category=UserWarning)

DEDUPE_FILE = "state/monitor_dedupe.json"

class MonitorEngine:
    def __init__(self):
        self._stop_event = threading.Event()
        self._thread = None
        self._status = "stopped"
        self._last_run_ts = 0
        self._total_alerts_sent = 0
        self._last_error = ""
        self.cfg = load_monitor_config()
        self._level_counts = {"error": 0, "warn": 0, "info": 0, "other": 0}
        
        # Pre-compile regex
        self.API_KEY_RE = re.compile(r"(API\s*Key|api[_-]?key)[：:=]\s*\S+", re.IGNORECASE)
        self.SENSITIVE_TOKEN_RE = re.compile(
            r"""(?<![A-Za-z0-9])(?=[A-Za-z0-9]{20,})(?=.*?[A-Z])(?=.*?[a-z])(?=.*?\d)[A-Za-z0-9]{20,}(?![A-Za-z0-9])""",
            re.VERBOSE
        )
        self.JAVA_EXCEPTION_LINE_RE = re.compile(
            r"(?:^|\b)(?:[a-zA-Z_][\w$]*\.)+(?:[A-Z][\w$]*Exception|Error)\b"
        )
        self.SLACK_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        
        self.cfg = load_monitor_config()
        if not self.cfg.enabled:
            log("monitor", "Monitor is disabled in config")
            self._status = "disabled"
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._status = "running"
        log("monitor", "Monitor engine started")

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
        self._status = "stopped"
        log("monitor", "Monitor engine stopped")

    def restart(self):
        self.stop()
        self.start()

    def get_status(self):
        return {
            "status": self._status,
            "last_run": datetime.fromtimestamp(self._last_run_ts).isoformat() if self._last_run_ts else None,
            "alerts_sent": self._total_alerts_sent,
            "last_error": self._last_error,
            "config": self.cfg.model_dump(),
            "levels": dict(self._level_counts)
        }

    def _run_loop(self):
        while not self._stop_event.is_set():
            try:
                # Reload config every loop to catch changes (or rely on restart)
                # For now, we rely on restart for major config changes, but let's re-read basic values if needed
                # Actually better to rely on self.restart() when config updates via API
                
                self._run_once()
            except Exception as e:
                self._last_error = str(e)
                log("monitor", f"Monitor crash: {e}")
            
            # Sleep in chunks to allow faster stop
            sleep_time = self.cfg.poll_interval_seconds
            for _ in range(sleep_time):
                if self._stop_event.is_set():
                    break
                time.sleep(1)

    def _create_es_client(self):
        return Elasticsearch(
            self.cfg.es_hosts,
            basic_auth=(self.cfg.es_username, self.cfg.es_password),
            verify_certs=False,
            request_timeout=60,
            max_retries=5,
            retry_on_timeout=True,
        )

    def _load_dedupe_state(self):
        try:
            if os.path.exists(DEDUPE_FILE):
                with open(DEDUPE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            log("monitor", f"Failed to load dedupe state: {e}")
        return {}

    def _save_dedupe_state(self, state: dict):
        os.makedirs(os.path.dirname(DEDUPE_FILE), exist_ok=True)
        tmp = DEDUPE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp, DEDUPE_FILE)

    def _prune_state(self, state: dict, now_ts: int):
        expired = []
        for k, v in state.items():
            if k == "_meta":
                continue
            last = v.get("last_seen_ts", 0)
            if now_ts - last > self.cfg.dedupe_ttl_seconds:
                expired.append(k)
        for k in expired:
            state.pop(k, None)
        return state

    def _mask_sensitive(self, text: str) -> str:
        if not text:
            return text
        safe_lines = []
        for line in text.splitlines():
            raw = line
            if raw.strip().startswith("- Location："):
                safe_lines.append(raw)
                continue
            if raw.strip().startswith("- API Key"):
                safe_lines.append(self.API_KEY_RE.sub(r"\1：****", raw))
                continue
            if raw.strip().startswith("- Exception"):
                masked = self.API_KEY_RE.sub(r"\1：****", raw)
                masked = self.SENSITIVE_TOKEN_RE.sub("****", masked)
                safe_lines.append(masked)
                continue
            safe_lines.append(self.API_KEY_RE.sub(r"\1：****", raw))
        return "\n".join(safe_lines)

    def _normalize_message(self, msg: str) -> str:
        if not msg:
            return ""
        msg = msg.strip()
        msg = re.sub(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?", "<TS>", msg)
        msg = re.sub(r"\b[0-9a-f]{16,}\b", "<HEX>", msg, flags=re.IGNORECASE)
        msg = re.sub(r"\b\d{5,}\b", "<NUM>", msg)
        return msg

    def _normalize_for_display(self, msg: str) -> str:
        text = self._normalize_message(msg or "")
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]
        lines = [ln for ln in lines if ln]
        if not lines:
            return ""
        
        key_substrings = [
            "Cannot deserialize value", "JSON parse error", "HttpMessageNotReadableException",
            "InvalidFormatException", "MismatchedInputException", "not one of the values",
            "values accepted for Enum class", "accepted for Enum class", "from String", "Enum class"
        ]
        picked = []
        seen = set()
        
        def pick_line(ln: str):
            if ln in seen: return
            seen.add(ln)
            picked.append(ln)

        for ln in lines:
            if any(s in ln for s in key_substrings):
                pick_line(ln)
        for ln in lines:
            if self.JAVA_EXCEPTION_LINE_RE.search(ln):
                pick_line(ln)
        
        if len(picked) < 2:
            for ln in lines:
                if "nested exception" in ln or "exception is" in ln:
                    pick_line(ln)
        
        if not picked:
            picked = lines[:6]
        
        picked = picked[:8]
        fp_text = "\n".join(picked)
        return re.sub(r"\n{3,}", "\n\n", fp_text).strip()

    def _build_dedupe_key(self, service: str, pod: str, message: str) -> str:
        # Fixed mode: service_pod_message
        norm = self._normalize_message(message)
        raw_key = f"{service}|{pod}|{norm}"
        return hashlib.sha1(raw_key.encode("utf-8")).hexdigest()

    def _send_slack(self, text: str):
        if not self.cfg.slack_webhook_url:
            return
        payload = {"text": text}
        req = urllib.request.Request(
            self.cfg.slack_webhook_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10, context=self.SLACK_SSL_CONTEXT) as resp:
            resp.read()

    def _run_once(self):
        es = self._create_es_client()
        now = datetime.utcnow()
        now_ts = int(now.timestamp())
        
        state = self._load_dedupe_state()
        state = self._prune_state(state, now_ts)
        
        last_run_ts = int(state.get("_meta", {}).get("last_run_ts", now_ts - self.cfg.poll_interval_seconds))
        start_ts = max(0, last_run_ts - self.cfg.window_overlap_seconds)
        start = datetime.fromtimestamp(start_ts, tz=timezone.utc).replace(tzinfo=None)
        
        body = {
            "size": 0,
            "query": {
                "bool": {
                    "must": [
                        {"range": {"timestamp": {"gte": start.isoformat(), "lte": now.isoformat()}}}
                    ],
                    "should": [
                        {
                            "query_string": {
                                "query": "ERROR OR WARN OR FATAL",
                                "fields": ["logMessage"],
                            }
                        },
                        *[{"match_phrase": {"logMessage": kw}} for kw in self.cfg.alert_keywords],
                    ],
                    "minimum_should_match": 1,
                    "must_not": [
                        *[{"match_phrase": {"logMessage": kw}} for kw in self.cfg.ignore_keywords]
                    ],
                }
            },
            "aggs": {
                "by_service": {
                    "terms": {"field": "serviceName.keyword", "size": 50},
                    "aggs": {
                        "by_pod": {
                            "terms": {"field": "podName.keyword", "size": 50},
                            "aggs": {
                                "logs": {
                                    "top_hits": {
                                        "size": 50,
                                        "_source": ["logMessage", "timestamp"],
                                        "sort": [{"timestamp": {"order": "asc"}}],
                                    }
                                }
                            },
                        }
                    },
                }
            },
        }

        try:
            resp = es.search(index=self.cfg.index_pattern, body=body)
        except Exception as e:
            log("monitor", f"ES Search failed: {e}")
            self._last_error = f"ES Search failed: {str(e)[:100]}"
            state.setdefault("_meta", {})
            state["_meta"]["last_run_ts"] = now_ts
            self._save_dedupe_state(state)
            self._last_run_ts = now_ts
            return

        new_alerts = []
        alerts_to_send = [] # Keys that met the alert criteria in this run
        total_seen_this_run = 0
        aggs = resp.get("aggregations", {})
        window_counts = {}  # (service, pod, level) -> count
        group_keys = {}     # (service, pod, level) -> [rec_keys]
        
        for s in aggs.get("by_service", {}).get("buckets", []):
            service = s.get("key", "unknown")
            for p in s.get("by_pod", {}).get("buckets", []):
                pod = p.get("key", "unknown")
                hits = p.get("logs", {}).get("hits", {}).get("hits", [])
                if not hits: continue
                
                for h in hits:
                    total_seen_this_run += 1
                    source = h.get("_source", {})
                    raw_msg = source.get("logMessage", "")
                    ts = source.get("timestamp") or now.isoformat()
                    # Try to parse timestamp from string to int for history tracking
                    # If not possible, use current time
                    try:
                        # Standard ISO format: 2023-01-01T12:00:00.000Z
                        # Simplification: use current loop time for tracking frequency
                        msg_ts = now_ts 
                    except:
                        msg_ts = now_ts

                    safe_msg = self._mask_sensitive(raw_msg)
                    key = self._build_dedupe_key(service, pod, safe_msg)
                    
                    # Check for immediate alert keywords
                    is_immediate = any(kw.lower() in raw_msg.lower() for kw in self.cfg.alert_keywords)

                    # classify log level and accumulate counts
                    lvl = self._classify_level(raw_msg)
                    if lvl in self._level_counts:
                        self._level_counts[lvl] += 1
                    else:
                        self._level_counts["other"] += 1
                    window_counts[(service, pod, lvl)] = window_counts.get((service, pod, lvl), 0) + 1
                    if lvl == "error":
                        try:
                            disp = self._normalize_for_display(safe_msg)
                        except Exception:
                            disp = safe_msg
                        log("monitor", f"[{service}/{pod}] ERROR {ts} {disp[:500]}")

                    rec = state.get(key)
                    if rec is None:
                        rec = {
                            "count": 0,
                            "first_seen": ts,
                            "last_seen": ts,
                            "last_seen_ts": now_ts,
                            "service": service,
                            "pod": pod,
                            "sample": safe_msg[:2000],
                            "history": [], # List of timestamps
                            "last_alert_ts": 0
                        }
                        state[key] = rec
                        # First time seeing this error
                        new_alerts.append(key)

                    # Update Stats
                    rec["count"] = int(rec.get("count", 0)) + 1
                    rec["last_seen"] = ts
                    rec["last_seen_ts"] = now_ts
                    
                    # Manage History (Sliding Window 60s)
                    history = rec.get("history", [])
                    history.append(now_ts)
                    # Prune old timestamps (> 60s ago)
                    history = [t for t in history if t > now_ts - 60]
                    rec["history"] = history
                    state[key] = rec
                    
                    # Track keys by service/pod/level for possible group alerts
                    lst = group_keys.get((service, pod, lvl))
                    if lst is None:
                        lst = []
                        group_keys[(service, pod, lvl)] = lst
                    lst.append(key)

                    # Alert Logic
                    should_alert = False
                    
                    # 1. Immediate Keyword Match
                    # Only alert immediately if the message contains specific alert keywords
                    if is_immediate:
                        should_alert = True
                    
                    # 2. Frequency Threshold (> 3 times in 60s)
                    # Otherwise, only alert if it occurs more than 3 times in 60 seconds
                    elif len(history) > 3:
                        should_alert = True
                    
                    # Check Cooldown (Don't alert more than once every 60s for the same key)
                    last_alert = rec.get("last_alert_ts", 0)
                    if should_alert and (now_ts - last_alert > 60):
                        rec["last_alert_ts"] = now_ts
                        alerts_to_send.append(key)
                        state[key] = rec

        # Group-based alert: if error level count > 3 within window, trigger using latest key
        for (svc, pod, lvl), cnt in window_counts.items():
            if lvl == "error" and cnt > 3:
                keys = group_keys.get((svc, pod, lvl)) or []
                if keys:
                    chosen = keys[-1]
                    rec = state.get(chosen, {})
                    last_alert = int(rec.get("last_alert_ts", 0))
                    if now_ts - last_alert > 60:
                        rec["last_alert_ts"] = now_ts
                        state[chosen] = rec
                        alerts_to_send.append(chosen)

        state.setdefault("_meta", {})
        state["_meta"]["last_run_ts"] = now_ts
        self._save_dedupe_state(state)
        self._last_run_ts = now_ts
        
        # Write scan summary to monitor logs
        error_run = sum(c for (svc, pod, lvl), c in window_counts.items() if lvl == "error")
        warn_run = sum(c for (svc, pod, lvl), c in window_counts.items() if lvl == "warn")
        info_run = sum(c for (svc, pod, lvl), c in window_counts.items() if lvl == "info")
        other_run = sum(c for (svc, pod, lvl), c in window_counts.items() if lvl == "other")
        log("monitor", f"Scan window {start.isoformat()} ~ {now.isoformat()} counts error={error_run} warn={warn_run} info={info_run} other={other_run} alerts={len(alerts_to_send)}")

        if alerts_to_send:
            # We filter alerts_to_send to unique keys just in case
            unique_alerts = list(set(alerts_to_send))
            self._process_alerts(unique_alerts, state, total_seen_this_run, start, now)
    
    def _classify_level(self, msg: str) -> str:
        m = (msg or "").lower()
        if "error" in m or "exception" in m or "fatal" in m or "traceback" in m:
            return "error"
        if "warn" in m or "warning" in m:
            return "warn"
        if "info" in m:
            return "info"
        return "other"

    def _process_alerts(self, alert_keys, state, total_seen, start, now):
        grouped = {}
        for k in alert_keys:
            rec = state.get(k, {})
            service = rec.get("service", "unknown")
            pod = rec.get("pod", "unknown")
            sample = rec.get("sample", "")
            fp_base = self._normalize_for_display(sample)
            fp = hashlib.sha1(fp_base.encode("utf-8")).hexdigest() if fp_base else "empty"
            
            svc_map = grouped.setdefault(service, {})
            g = svc_map.get(fp)
            if g is None:
                svc_map[fp] = {
                    "service": service,
                    "pods": {pod},
                    "alert_count": 1, # How many keys triggered alert
                    "total_count": int(rec.get("count", 1)),
                    "first_seen": rec.get("first_seen"),
                    "last_seen": rec.get("last_seen"),
                    "last_seen_ts": int(rec.get("last_seen_ts", 0)),
                    "sample": sample,
                }
            else:
                g["pods"].add(pod)
                g["alert_count"] += 1
                g["total_count"] += int(rec.get("count", 1))
                g["last_seen_ts"] = max(g["last_seen_ts"], int(rec.get("last_seen_ts", 0)))

        # Send Slack
        try:
            self._format_and_send_slack(grouped, len(alert_keys), total_seen, start, now)
            self._total_alerts_sent += 1
            log("monitor", f"Alert sent. triggered={len(alert_keys)} total_seen={total_seen}")
        except Exception as e:
            log("monitor", f"Slack send failed: {e}")
            self._last_error = f"Slack failed: {str(e)[:100]}"

    def _format_and_send_slack(self, grouped, triggered_count, total_count, start, now):
        MAX_SERVICES = 20
        MAX_SAMPLES = 3
        
        service_items = sorted(grouped.items(), key=lambda kv: len(kv[1]), reverse=True)
        lines = [":rotating_light: *Log Alert Triggered*"]
        lines.append(f"*Triggered Groups:* {triggered_count}")
        lines.append(f"*Total Logs Scanned:* {total_count}")
        lines.append(f"*Window:* {start.strftime('%H:%M:%S')} ~ {now.strftime('%H:%M:%S')}")
        lines.append("")

        shown_services = 0
        for service, fp_map in service_items:
            shown_services += 1
            if shown_services > MAX_SERVICES:
                break
            groups = list(fp_map.values())
            groups.sort(key=lambda g: g.get("last_seen_ts", 0), reverse=True)
            
            lines.append(f"*Service:* `{service}`")
            for g in groups[:MAX_SAMPLES]:
                pods_list = sorted(list(g["pods"]))
                pods_show = ", ".join(f"`{p}`" for p in pods_list[:5])
                if len(pods_list) > 5:
                    pods_show += f" ...(+{len(pods_list)-5})"
                lines.append(
                    f"• *Pods:* {pods_show}\n"
                    f"  *TotalOccurrences:* {g['total_count']}\n"
                    f"  ```{g['sample'][:500]}```"
                )
            if len(groups) > MAX_SAMPLES:
                lines.append(f"_...and {len(groups) - MAX_SAMPLES} more_")
            lines.append("")
        
        self._send_slack("\n".join(lines))

# Global singleton
monitor_engine = MonitorEngine()
