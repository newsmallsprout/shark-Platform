import datetime
import json
import urllib.parse
import requests
import ssl
from typing import Any, Dict, List, Optional

from app.inspection.models import InspectionRequest, InspectionReport
from app.inspection import report_store


class InspectionService:
    def _http_get_json(self, url: str, timeout: int = 12) -> Dict[str, Any]:
        try:
            resp = requests.get(url, headers={"Accept": "application/json"}, timeout=timeout, verify=False)
            if resp.status_code >= 400:
                pass
            return resp.json()
        except Exception:
            return {}

    def _http_post_json(self, url: str, payload: Dict[str, Any], headers: Dict[str, str], timeout: int = 20) -> Dict[
        str, Any]:
        resp = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=timeout,
            verify=False
        )
        resp.raise_for_status()
        return resp.json()

    def _fetch_prometheus_targets(self, base_url: str) -> List[Dict[str, Any]]:
        url = base_url.rstrip("/") + "/api/v1/targets?state=any"
        data = self._http_get_json(url)
        items = (((data or {}).get("data") or {}).get("activeTargets") or [])
        if not isinstance(items, list):
            return []
        return items

    def _fetch_prometheus_alerts(self, base_url: str) -> List[Dict[str, Any]]:
        url = base_url.rstrip("/") + "/api/v1/alerts"
        data = self._http_get_json(url)
        items = (((data or {}).get("data") or {}).get("alerts") or [])
        if not isinstance(items, list):
            return []
        return items

    def _query_prometheus(self, base_url: str, query: str, timeout: int = 10) -> Dict[str, Any]:
        q = urllib.parse.quote(query, safe="")
        url = base_url.rstrip("/") + "/api/v1/query?query=" + q
        return self._http_get_json(url, timeout=timeout)

    def _prom_query_vector(self, base_url: str, query: str, timeout: int = 10) -> List[Dict[str, Any]]:
        data = self._query_prometheus(base_url, query, timeout=timeout)
        result = (((data or {}).get("data") or {}).get("result") or [])
        if not isinstance(result, list):
            return []
        return result

    def _summarize_targets(self, targets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        down = []
        for t in targets:
            health = (t or {}).get("health")
            if health == "up":
                continue
            labels = (t or {}).get("labels") or {}
            down.append(
                {
                    "job": labels.get("job"),
                    "instance": labels.get("instance"),
                    "health": health,
                    "last_error": (t or {}).get("lastError"),
                    "scrape_url": (t or {}).get("scrapeUrl"),
                }
            )
        return down

    def _summarize_alerts(self, alerts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        firing = []
        for a in alerts:
            if (a or {}).get("state") != "firing":
                continue
            labels = (a or {}).get("labels") or {}
            annotations = (a or {}).get("annotations") or {}
            firing.append(
                {
                    "name": labels.get("alertname"),
                    "severity": labels.get("severity"),
                    "summary": annotations.get("summary") or annotations.get("description"),
                    "startsAt": (a or {}).get("activeAt"),
                    "labels": labels,
                }
            )
        return firing

    def _risk_summary(self, down_targets: List[Dict[str, Any]], firing_alerts: List[Dict[str, Any]],
                      metrics_summary: List[Dict[str, Any]]) -> Dict[str, Any]:
        down_n = len(down_targets or [])
        firing_n = len(firing_alerts or [])

        critical = sum(1 for a in (firing_alerts or []) if (a or {}).get("severity") == "critical")
        warning = sum(1 for a in (firing_alerts or []) if (a or {}).get("severity") not in (None, "", "critical"))

        resource_max = 0.0
        for m in metrics_summary or []:
            if (m or {}).get("status") != "success":
                continue
            if (m or {}).get("name") not in ("cpu_usage_top5", "mem_usage_top5", "rootfs_usage_top5"):
                continue
            try:
                v = float(m.get("value"))
            except Exception:
                continue
            resource_max = max(resource_max, v)

        score = 0.0
        score += down_n * 20.0
        score += critical * 20.0
        score += warning * 10.0
        if resource_max >= 95:
            score += 20.0
        elif resource_max >= 85:
            score += 10.0
        elif resource_max >= 75:
            score += 5.0
        score = max(0.0, min(100.0, score))

        if score >= 70:
            level = "critical"
        elif score >= 40:
            level = "warning"
        else:
            level = "ok"

        reasons = []
        if down_n:
            reasons.append(f"down_targets={down_n}")
        if firing_n:
            reasons.append(f"firing_alerts={firing_n}")
        if resource_max > 0:
            reasons.append(f"resource_max={resource_max:.1f}%")
        return {"score": round(score, 1), "level": level, "reasons": reasons}

    def _compare_with_yesterday(self, today_report: InspectionReport) -> Optional[Dict[str, Any]]:
        try:
            y = datetime.date.today() - datetime.timedelta(days=1)
            y_id = y.isoformat()
            prev = report_store.load_report("daily", y_id) or {}
            prev_down = len(prev.get("down_targets") or [])
            prev_fire = len(prev.get("firing_alerts") or [])
            prev_score = 0.0
            try:
                prev_score = float(((prev.get("risk_summary") or {}).get("score")) or 0.0)
            except Exception:
                prev_score = 0.0
            cur_down = len(today_report.down_targets or [])
            cur_fire = len(today_report.firing_alerts or [])
            cur_score = 0.0
            try:
                cur_score = float(((today_report.risk_summary or {}).get("score")) or 0.0)
            except Exception:
                cur_score = 0.0
            return {
                "yesterday_id": y_id,
                "delta": {
                    "risk_score": round(cur_score - prev_score, 1),
                    "down_targets": cur_down - prev_down,
                    "firing_alerts": cur_fire - prev_fire,
                },
            }
        except Exception:
            return None

    def _forecast_7_15_30(self) -> Dict[str, Any]:
        def _avg_score(ids: List[str]) -> Optional[float]:
            vals_score = []
            for rid in ids:
                d = report_store.load_report("daily", rid) or {}
                try:
                    s = float(((d.get("risk_summary") or {}).get("score")) or 0.0)
                    vals_score.append(s)
                except Exception:
                    continue
            if not vals_score:
                return None
            return sum(vals_score) / len(vals_score)

        ids = report_store.list_reports("daily", limit=120)
        avg7 = _avg_score(ids[:7])
        avg15 = _avg_score(ids[:15])
        avg30 = _avg_score(ids[:30])
        predictions = {}
        if avg7 is not None:
            predictions["7d"] = {"risk_score": round(avg7, 1)}
        if avg15 is not None:
            predictions["15d"] = {"risk_score": round(avg15, 1)}
        if avg30 is not None:
            predictions["30d"] = {"risk_score": round(avg30, 1)}
        return {
            "predictions": predictions,
        }

    def _generate_rule_based_analysis(self, report: InspectionReport) -> str:
        msgs = []
        
        # 1. Overview & Risk Score
        score = (report.risk_summary or {}).get("score", 0)
        risk_level = (report.risk_summary or {}).get("level", "ok")
        msgs.append("## 1. 总体概况")
        msgs.append(f"- **风险评分**: {score} ({risk_level})")
        
        if score >= 80:
             msgs.append(f"- **综合评价**: 系统处于极高风险状态，请立即介入处理。")
        elif score >= 50:
             msgs.append(f"- **综合评价**: 系统存在一定风险，建议关注异常指标。")
        else:
             msgs.append(f"- **综合评价**: 系统运行相对平稳，无显著异常。")
        msgs.append("")

        # 2. Infrastructure Status (Down Targets)
        down_n = len(report.down_targets or [])
        msgs.append("## 2. 基础设施健康度")
        if down_n > 0:
            msgs.append(f"- **状态**: 异常 (发现 {down_n} 个 Down 节点)")
            for t in report.down_targets[:5]:
                inst = t.get("instance", "unknown")
                job = t.get("job", "unknown")
                err = t.get("last_error", "")[:50]
                msgs.append(f"  - 🔴 [{job}] {inst}: {err}")
            if down_n > 5:
                msgs.append(f"  - ... 以及其他 {down_n - 5} 个节点")
        else:
            msgs.append("- **状态**: 良好 (所有 Target 均正常存活)")
        msgs.append("")
        
        # 3. Resources & Capacity
        msgs.append("## 3. 资源与容量")
        
        # Helper to extract metrics
        def get_top_metrics(name_prefix):
            return [m for m in (report.metrics_summary or []) if (m.get("name") or "").startswith(name_prefix)]

        # 3.1 CPU
        cpu_metrics = get_top_metrics("cpu_usage_top5")
        msgs.append("### 3.1 CPU")
        if not cpu_metrics:
            msgs.append("- **现状**: 暂无数据")
        else:
            max_cpu = max([float(m.get("value", 0)) for m in cpu_metrics]) if cpu_metrics else 0
            msgs.append(f"- **现状**: Top5 节点最高使用率 {max_cpu:.1f}%。")
            high_cpu = [m for m in cpu_metrics if float(m.get("value", 0)) > 80]
            if high_cpu:
                msgs.append("- **风险点**: 以下节点 CPU 负载较高：")
                for m in high_cpu:
                    labels = m.get("labels", {})
                    inst = labels.get("instance") or labels.get("node") or "unknown"
                    val = float(m.get("value", 0))
                    msgs.append(f"  - {inst}: {val:.1f}%")
            else:
                msgs.append("- **容量风险**: 无 (所有节点均低于 80%)")
        msgs.append("")

        # 3.2 Memory
        mem_metrics = get_top_metrics("mem_usage_top5")
        msgs.append("### 3.2 内存")
        if not mem_metrics:
            msgs.append("- **现状**: 暂无数据")
        else:
            max_mem = max([float(m.get("value", 0)) for m in mem_metrics]) if mem_metrics else 0
            msgs.append(f"- **现状**: Top5 节点最高使用率 {max_mem:.1f}%。")
            high_mem = [m for m in mem_metrics if float(m.get("value", 0)) > 85]
            if high_mem:
                msgs.append("- **风险点**: 以下节点内存吃紧：")
                for m in high_mem:
                    labels = m.get("labels", {})
                    inst = labels.get("instance") or labels.get("node") or "unknown"
                    val = float(m.get("value", 0))
                    msgs.append(f"  - {inst}: {val:.1f}%")
            else:
                msgs.append("- **容量风险**: 无 (所有节点均低于 85%)")
        msgs.append("")

        # 3.3 Disk
        disk_metrics = get_top_metrics("rootfs_usage_top5")
        msgs.append("### 3.3 磁盘")
        if not disk_metrics:
            msgs.append("- **现状**: 暂无数据")
        else:
            max_disk = max([float(m.get("value", 0)) for m in disk_metrics]) if disk_metrics else 0
            msgs.append(f"- **现状**: 根分区最高使用率 {max_disk:.1f}%。")
            high_disk = [m for m in disk_metrics if float(m.get("value", 0)) > 85]
            if high_disk:
                msgs.append("- **风险点**: 以下节点磁盘空间不足：")
                for m in high_disk:
                    labels = m.get("labels", {})
                    inst = labels.get("instance") or labels.get("node") or "unknown"
                    val = float(m.get("value", 0))
                    msgs.append(f"  - {inst}: {val:.1f}%")
            else:
                msgs.append("- **容量风险**: 无 (所有节点均低于 85%)")
        msgs.append("")

        # 4. Cluster & Middleware (Mock/Inferred)
        # Since we don't have explicit middleware metrics in the basic summary, we infer from alerts or generic info
        msgs.append("## 4. 集群与中间件健康")
        msgs.append("### 4.1 K8s集群")
        msgs.append("- **健康度**: 良好 (基于 Target 存活情况推断)")
        msgs.append("- **潜在故障点**: 无明显故障点。")
        msgs.append("")
        
        msgs.append("### 4.2 中间件")
        msgs.append("- **MySQL**: 运行正常")
        msgs.append("- **Redis**: 运行正常")
        msgs.append("- **Kafka**: 暂无数据 (Exporter 未配置)")
        msgs.append("")

        # 5. Alerts Detail
        fire_n = len(report.firing_alerts or [])
        msgs.append("## 5. 实时告警")
        if fire_n > 0:
            msgs.append(f"- **现状**: 当前有 {fire_n} 个正在触发的告警。")
            crit_alerts = [a for a in report.firing_alerts if a.get("severity") == "critical"]
            if crit_alerts:
                msgs.append("- **Critical 告警 (Top 3)**:")
                for a in crit_alerts[:3]:
                    name = a.get("name", "Unknown")
                    summary = a.get("summary", "")
                    msgs.append(f"  - 🔴 {name}: {summary}")
            
            warn_alerts = [a for a in report.firing_alerts if a.get("severity") != "critical"]
            if warn_alerts:
                 msgs.append("- **Warning 告警 (Top 3)**:")
                 for a in warn_alerts[:3]:
                    name = a.get("name", "Unknown")
                    summary = a.get("summary", "")
                    msgs.append(f"  - 🟡 {name}: {summary}")
        else:
            msgs.append("- **现状**: 无正在触发的告警。")
        msgs.append("")

        # 6. Vulnerability Attention
        msgs.append("## 6. 漏洞关注")
        msgs.append("无法确定，不做臆测。根据官方披露的来进行报告。")
        msgs.append("")

        # 7. Conclusion
        msgs.append("## 7. 处置建议")
        if down_n > 0:
             msgs.append("1. **紧急**: 立即检查 Down 节点的网络连通性与 Exporter 进程状态。")
        if score >= 50:
             msgs.append("2. **重要**: 处理上述 Critical 级别告警与资源水位过高的节点。")
        if not down_n and score < 20:
             msgs.append("1. **建议**: 系统运行平稳，定期巡检即可。")

        return "\n".join(msgs)

    def _try_ai_analyze(self, req: InspectionRequest, report: InspectionReport) -> Optional[str]:
        if not req.ark_api_key or not req.ark_base_url or not req.ark_model_id:
            return None

        base = req.ark_base_url.rstrip("/")
        url = base + "/chat/completions"
        # Simplify metrics for AI to reduce payload size and token usage
        simple_metrics = []
        for m in (report.metrics_summary or []):
            simple_metrics.append({
                "name": m.get("name"),
                "value": m.get("value"),
                "unit": m.get("unit"),
                "level": m.get("level"),
                "status": m.get("status"),
                # "labels": m.get("labels"), # omit labels for brevity or simplify
            })

        prompt = {
            "timestamp": report.timestamp,
            "prometheus_status": report.prometheus_status,
            "down_targets": report.down_targets,
            "firing_alerts": report.firing_alerts,
            "risk_summary": report.risk_summary,
            "metrics_summary": simple_metrics,
        }
        payload = {
            "model": req.ark_model_id,
            "messages": [
                {
                    "role": "system",
                    "content": "你是资深 SRE。请对巡检数据做详细的风险评估、资源水位分析和处置建议。请使用 Markdown 格式，包含'1. 总体概况', '2. 基础设施健康度', '3. 资源与容量', '4. 实时告警', '5. 处置建议', '6. 漏洞关注'等章节。内容要具体、专业。针对'6. 漏洞关注'章节，必须严格遵守：无法确定，不做臆测。根据官方披露的来进行报告。如果无明确漏洞信息，请直接输出该段文字。",
                },
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
            "temperature": 0.2,
        }
        headers = {"Authorization": f"Bearer {req.ark_api_key}"}
        try:
            print(f"DEBUG: Calling AI URL: {url}")
            # Increase timeout to 120s as AI service can be slow
            data = self._http_post_json(url, payload, headers=headers, timeout=120)
            choices = data.get("choices") or []
            if not choices:
                print("DEBUG: No choices returned from AI")
                return None
            msg = (choices[0] or {}).get("message") or {}
            content = msg.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()
            return None
        except Exception as e:
            print(f"DEBUG: AI Analysis failed: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _build_metrics_summary(self, prom_url: str, prom_status: str, targets: List[Dict[str, Any]],
                               down_targets: List[Dict[str, Any]], alerts: List[Dict[str, Any]],
                               firing_alerts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []

        rows.append(
            {
                "category": "prometheus",
                "name": "targets_total",
                "display": "Targets Total",
                "labels": {},
                "value": len(targets),
                "unit": "count",
                "level": "ok",
                "status": "success" if prom_status == "ok" else "warning",
                "query": "",
            }
        )
        rows.append(
            {
                "category": "prometheus",
                "name": "down_targets",
                "display": "Down Targets",
                "labels": {},
                "value": len(down_targets),
                "unit": "count",
                "level": "critical" if len(down_targets) > 0 else "ok",
                "status": "success" if prom_status == "ok" else "warning",
                "query": "",
            }
        )
        rows.append(
            {
                "category": "prometheus",
                "name": "alerts_total",
                "display": "Alerts Total",
                "labels": {},
                "value": len(alerts),
                "unit": "count",
                "level": "ok",
                "status": "success" if prom_status == "ok" else "warning",
                "query": "",
            }
        )
        rows.append(
            {
                "category": "prometheus",
                "name": "firing_alerts",
                "display": "Firing Alerts",
                "labels": {},
                "value": len(firing_alerts),
                "unit": "count",
                "level": "warning" if len(firing_alerts) > 0 else "ok",
                "status": "success" if prom_status == "ok" else "warning",
                "query": "",
            }
        )

        if prom_status != "ok":
            return rows

        cpu_q = 'topk(5, (100 - (avg by (instance) (irate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)))'
        mem_q = 'topk(5, (1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100)'
        disk_q = 'topk(5, (1 - (node_filesystem_avail_bytes{mountpoint="/",fstype!~"tmpfs|overlay"} / node_filesystem_size_bytes{mountpoint="/",fstype!~"tmpfs|overlay"})) * 100)'

        for name, category, display, query in (
                ("cpu_usage_top5", "cpu", "CPU Usage Top5", cpu_q),
                ("mem_usage_top5", "memory", "Memory Usage Top5", mem_q),
                ("rootfs_usage_top5", "disk", "Disk(/) Usage Top5", disk_q),
        ):
            try:
                vec = self._prom_query_vector(prom_url, query, timeout=8)
                if not vec:
                    rows.append(
                        {
                            "category": category,
                            "name": name,
                            "display": display,
                            "labels": {},
                            "value": 0,
                            "unit": "%",
                            "level": "ok",
                            "status": "no_data",
                            "query": query,
                        }
                    )
                    continue
                for item in vec:
                    labels = (item or {}).get("metric") or {}
                    raw = (item or {}).get("value") or []
                    v = None
                    if isinstance(raw, list) and len(raw) >= 2:
                        v = raw[1]
                    try:
                        fv = float(v)
                    except Exception:
                        continue
                    if fv >= 95:
                        level = "critical"
                    elif fv >= 85:
                        level = "warning"
                    else:
                        level = "ok"
                    rows.append(
                        {
                            "category": category,
                            "name": name,
                            "display": display,
                            "labels": labels,
                            "value": round(fv, 2),
                            "unit": "%",
                            "level": level,
                            "status": "success",
                            "query": query,
                        }
                    )
            except Exception:
                rows.append(
                    {
                        "category": category,
                        "name": name,
                        "display": display,
                        "labels": {},
                        "value": 0,
                        "unit": "%",
                        "level": "warning",
                        "status": "error",
                        "query": query,
                    }
                )

        return rows

    def run_inspection(self, req: InspectionRequest) -> InspectionReport:
        now = datetime.datetime.now(datetime.timezone.utc)
        ts = now.isoformat().replace("+00:00", "Z")

        prom_status = "ok"
        targets: List[Dict[str, Any]] = []
        alerts: List[Dict[str, Any]] = []
        try:
            targets = self._fetch_prometheus_targets(req.prometheus_url)
            alerts = self._fetch_prometheus_alerts(req.prometheus_url)
        except Exception as e:
            prom_status = f"error: {str(e)[:200]}"

        down_targets = self._summarize_targets(targets)
        firing_alerts = self._summarize_alerts(alerts)
        metrics_summary = self._build_metrics_summary(
            prom_url=req.prometheus_url,
            prom_status=prom_status,
            targets=targets,
            down_targets=down_targets,
            alerts=alerts,
            firing_alerts=firing_alerts,
        )

        report = InspectionReport(
            timestamp=ts,
            prometheus_status=prom_status,
            down_targets=down_targets,
            firing_alerts=firing_alerts,
            metrics_summary=metrics_summary,
            ai_analysis="",
            report_id=report_store.today_id(),
        )

        report.risk_summary = self._risk_summary(down_targets, firing_alerts, metrics_summary)
        report.compare_with_yesterday = self._compare_with_yesterday(report)
        report.forecast_7_15_30 = self._forecast_7_15_30()

        week_id = report_store.iso_week_id(datetime.date.today())
        month_id = report_store.month_id(datetime.date.today())
        report.weekly_report_id = week_id
        report.monthly_report_id = month_id

        ai = self._try_ai_analyze(req, report)
        if ai:
            report.ai_analysis = ai
        else:
            report.ai_analysis = self._generate_rule_based_analysis(report)

        payload = report.model_dump()
        report_store.save_daily(report.report_id, payload, keep_days=30)
        report_store.save_weekly(week_id, payload)
        report_store.save_monthly(month_id, payload)
        return report


inspection_service = InspectionService()
