import requests
import json
import os
import datetime
from datetime import datetime, timezone, timedelta
from .models import InspectionConfig, InspectionReport

from core.logging import log

class InspectionEngine:
    def __init__(self):
        self._config = None

    @property
    def config(self):
        if self._config is None:
            try:
                self._config = InspectionConfig.load()
            except Exception as e:
                print(f"Warning: Failed to load InspectionConfig: {e}")
                # Return a dummy config or handle gracefully during migration
                self._config = InspectionConfig()
        return self._config

    @config.setter
    def config(self, value):
        self._config = value

    def _get_base_url(self):
        url = self.config.prometheus_url
        if not url:
            return ""
        if not url.startswith("http://") and not url.startswith("https://"):
            url = "http://" + url
        return url.rstrip('/')

    def _query_prometheus(self, query):
        if not self.config.prometheus_url:
            return []
        try:
            url = f"{self._get_base_url()}/api/v1/query"
            log("inspection", f"Querying Prometheus: {query}")
            resp = requests.get(url, params={'query': query}, timeout=10)
            if resp.ok:
                return resp.json().get('data', {}).get('result', [])
        except Exception as e:
            print(f"Prometheus query error: {e}")
            log("inspection", f"Prometheus query error: {e}")
        return []

    def _get_targets(self):
        if not self.config.prometheus_url:
            return []
        try:
            url = f"{self._get_base_url()}/api/v1/targets"
            resp = requests.get(url, timeout=5)
            if resp.ok:
                return resp.json().get('data', {}).get('activeTargets', [])
        except:
            pass
        return []

    def _get_alerts(self):
        if not self.config.prometheus_url:
            return []
        try:
            url = f"{self._get_base_url()}/api/v1/alerts"
            resp = requests.get(url, timeout=5)
            if resp.ok:
                return resp.json().get('data', {}).get('alerts', [])
        except:
            pass
        return []

    def _call_gemini_api(self, prompt, system_prompt):
        """Call Google Gemini API (REST)"""
        api_key = self.config.ark_api_key
        model = self.config.ark_model_id or "gemini-1.5-flash"
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        
        payload = {
            "contents": [{
                "parts": [{"text": prompt}]
            }],
            "systemInstruction": {
                "parts": [{"text": system_prompt}]
            }
        }
        
        try:
            resp = requests.post(url, json=payload, timeout=60)
            if resp.ok:
                data = resp.json()
                # Gemini response structure
                try:
                    return data['candidates'][0]['content']['parts'][0]['text']
                except (KeyError, IndexError):
                    return f"Gemini response parsing failed: {json.dumps(data)}"
            else:
                return f"Gemini API failed: {resp.status_code} {resp.text}"
        except Exception as e:
            return f"Gemini connection error: {e}"

    def _call_openai_compatible_api(self, prompt, system_prompt):
        """Call OpenAI/Ark/Doubao compatible API"""
        url = f"{self.config.ark_base_url.rstrip('/')}/chat/completions"
        
        payload = {
            "model": self.config.ark_model_id,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ]
        }
        
        try:
            resp = requests.post(
                url,
                headers={
                    "Authorization": f"Bearer {self.config.ark_api_key}",
                    "Content-Type": "application/json"
                },
                json=payload,
                timeout=300
            )
            if resp.ok:
                return resp.json()['choices'][0]['message']['content']
            else:
                return f"AI analysis failed: {resp.status_code} {resp.text}"
        except Exception as e:
            return f"AI analysis error: {e}"

    def _calculate_health_score(self, down_targets, firing_alerts, servers):
        """
        Calculate dynamic health score (0-100) based on current metrics.
        Base score: 100
        Deductions:
          - Down Target: -20 each
          - Critical Alert: -15 each
          - Warning Alert: -5 each
          - Resource Usage (CPU/Mem): >90% -> -10, >80% -> -5
          - Disk Usage: >95% -> -15, >85% -> -5
        """
        score = 100.0
        reasons = []

        # 1. Down Targets
        if down_targets:
            deduction = len(down_targets) * 20
            score -= deduction
            reasons.append(f"Down Targets ({len(down_targets)}): -{deduction}")

        # 2. Alerts
        for alert in firing_alerts:
            severity = alert.get('severity', 'warning').lower()
            if severity in ['critical', 'high']:
                score -= 15
                reasons.append(f"Critical Alert ({alert.get('name')}): -15")
            else:
                score -= 5
                reasons.append(f"Warning Alert ({alert.get('name')}): -5")

        # 3. Resource Usage
        if servers:
            max_cpu = max((float(s.get('cpu_pct') or 0) for s in servers), default=0)
            max_mem = max((float(s.get('mem_pct') or 0) for s in servers), default=0)
            max_disk = max((float(s.get('disk_pct') or 0) for s in servers), default=0)

            if max_cpu > 95:
                score -= 10
                reasons.append(f"CPU热点(最高{round(max_cpu,1)}%): -10")
            elif max_cpu > 85:
                score -= 5
                reasons.append(f"CPU偏高(最高{round(max_cpu,1)}%): -5")

            if max_mem > 95:
                score -= 10
                reasons.append(f"内存热点(最高{round(max_mem,1)}%): -10")
            elif max_mem > 85:
                score -= 5
                reasons.append(f"内存偏高(最高{round(max_mem,1)}%): -5")

            if max_disk > 95:
                score -= 15
                reasons.append(f"磁盘临界(最高{round(max_disk,1)}%): -15")
            elif max_disk > 90:
                score -= 5
                reasons.append(f"磁盘偏高(最高{round(max_disk,1)}%): -5")

        score = max(0.0, score)
        level = "ok"
        if score < 60:
            level = "critical"
        elif score < 85:
            level = "warning"
            
        if not reasons:
            reasons.append("System Healthy")
            
        return round(score, 1), level, reasons

    def _predict_future_scores(self, current_score):
        """
        Simple prediction based on last 7 days history.
        Uses simple linear trend or moving average.
        """
        # Get last 7 reports
        today = datetime.now().date()
        history_scores = []
        
        try:
            # We want reports before today
            for i in range(1, 8):
                d = (today - timedelta(days=i)).strftime('%Y-%m-%d')
                report = InspectionReport.objects.filter(report_id=d).first()
                if report and report.content:
                    s = report.content.get('health_summary', {}).get('score') or report.content.get('risk_summary', {}).get('score')
                    if s is not None:
                        history_scores.append(float(s))
        except Exception:
            pass
            
        # Add current score as the latest data point
        history_scores.insert(0, current_score)
        
        # Simple Logic: 
        # If we have enough history, calculate trend.
        # Otherwise assume stable.
        
        predictions = {}
        
        if len(history_scores) < 3:
            # Not enough data, assume stable with slight random variance or just current
            predictions = {
                "7d": {"risk_score": current_score},
                "15d": {"risk_score": current_score},
                "30d": {"risk_score": current_score}
            }
        else:
            # Calculate simple trend (average daily change)
            # scores are [today, yesterday, day_before...]
            # daily_change = (today - oldest) / days
            oldest = history_scores[-1]
            days = len(history_scores) - 1
            daily_change = (current_score - oldest) / days if days > 0 else 0
            
            # Predict
            pred_7 = max(0, min(100, current_score + (daily_change * 7)))
            pred_15 = max(0, min(100, current_score + (daily_change * 15)))
            pred_30 = max(0, min(100, current_score + (daily_change * 30)))
            
            predictions = {
                "7d": {"risk_score": round(pred_7, 1)},
                "15d": {"risk_score": round(pred_15, 1)},
                "30d": {"risk_score": round(pred_30, 1)}
            }
            
        return predictions

    def run(self):
        log("inspection", "Starting inspection run...")
        report_id = datetime.now().strftime('%Y-%m-%d')
        
        # 1. Collect Data
        metrics_summary = []
        
        # Targets
        log("inspection", "Fetching targets...")
        targets = self._get_targets()
        total_targets = len(targets)
        raw_down = [t for t in targets if t.get('health') != 'up']
        
        # Transform for frontend display
        down_targets = []
        for t in raw_down:
            labels = t.get('labels', {})
            down_targets.append({
                "job": labels.get('job', 'unknown'),
                "instance": labels.get('instance', 'unknown'),
                "last_error": t.get('lastError', '')
            })
            
        log("inspection", f"Targets fetched: {total_targets} total, {len(down_targets)} down")
        
        metrics_summary.append({
            "category": "prometheus", "name": "targets_total", "display": "Targets Total",
            "labels": {}, "value": total_targets, "unit": "count", "level": "ok", "status": "success"
        })
        metrics_summary.append({
            "category": "prometheus", "name": "down_targets", "display": "Down Targets",
            "labels": {}, "value": len(down_targets), "unit": "count", "level": "ok" if not down_targets else "critical", "status": "success"
        })

        # Alerts
        log("inspection", "Fetching alerts...")
        alerts = self._get_alerts()
        raw_firing = [a for a in alerts if a.get('state') == 'firing']
        
        # Transform for frontend display
        firing = []
        for a in raw_firing:
            labels = a.get('labels', {})
            annotations = a.get('annotations', {})
            firing.append({
                "name": labels.get('alertname', 'Unknown Alert'),
                "severity": labels.get('severity', 'warning'),
                "summary": annotations.get('summary', 'No summary available')
            })
            
        log("inspection", f"Alerts fetched: {len(alerts)} total, {len(firing)} firing")
        metrics_summary.append({
            "category": "prometheus", "name": "alerts_total", "display": "Alerts Total",
            "labels": {}, "value": len(alerts), "unit": "count", "level": "ok", "status": "success"
        })
        metrics_summary.append({
            "category": "prometheus", "name": "firing_alerts", "display": "Firing Alerts",
            "labels": {}, "value": len(firing), "unit": "count", "level": "ok" if not firing else "warning", "status": "success"
        })

        log("inspection", "Querying node resource usage...")
        cpu_query = '(100 - (avg by (instance) (irate(node_cpu_seconds_total{mode="idle"}[5m])) * 100))'
        mem_query = '((1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100)'
        disk_query = '((1 - (node_filesystem_avail_bytes{mountpoint="/",fstype!~"tmpfs|overlay"} / node_filesystem_size_bytes{mountpoint="/",fstype!~"tmpfs|overlay"})) * 100)'
        load1_query = 'node_load1'
        uptime_h_query = '((time() - node_boot_time_seconds) / 3600)'

        cpu_results = self._query_prometheus(cpu_query)
        mem_results = self._query_prometheus(mem_query)
        disk_results = self._query_prometheus(disk_query)
        load1_results = self._query_prometheus(load1_query)
        uptime_results = self._query_prometheus(uptime_h_query)

        by_instance = {}
        def _set(inst, k, v):
            if not inst:
                return
            if inst not in by_instance:
                by_instance[inst] = {"instance": inst}
            by_instance[inst][k] = v

        for r in cpu_results:
            inst = (r.get('metric') or {}).get('instance') or ''
            try:
                _set(inst, 'cpu_pct', round(float(r['value'][1]), 2))
            except Exception:
                pass
        for r in mem_results:
            inst = (r.get('metric') or {}).get('instance') or ''
            try:
                _set(inst, 'mem_pct', round(float(r['value'][1]), 2))
            except Exception:
                pass
        for r in disk_results:
            inst = (r.get('metric') or {}).get('instance') or ''
            try:
                _set(inst, 'disk_pct', round(float(r['value'][1]), 2))
            except Exception:
                pass
        for r in load1_results:
            inst = (r.get('metric') or {}).get('instance') or ''
            try:
                _set(inst, 'load1', round(float(r['value'][1]), 2))
            except Exception:
                pass
        for r in uptime_results:
            inst = (r.get('metric') or {}).get('instance') or ''
            try:
                _set(inst, 'uptime_hours', round(float(r['value'][1]), 1))
            except Exception:
                pass

        servers = list(by_instance.values())
        servers.sort(key=lambda x: float(x.get('cpu_pct') or 0), reverse=True)

        def _avg(key):
            vals = [float(s.get(key) or 0) for s in servers if s.get(key) is not None]
            return round(sum(vals) / len(vals), 2) if vals else 0.0

        fleet_summary = {
            "server_count": len(servers),
            "avg_cpu_pct": _avg('cpu_pct'),
            "avg_mem_pct": _avg('mem_pct'),
            "avg_disk_pct": _avg('disk_pct'),
            "top_cpu": servers[:10],
            "top_mem": sorted(servers, key=lambda x: float(x.get('mem_pct') or 0), reverse=True)[:10],
            "top_disk": sorted(servers, key=lambda x: float(x.get('disk_pct') or 0), reverse=True)[:10],
        }

        metrics_summary.append({
            "category": "fleet", "name": "server_count", "display": "Servers",
            "labels": {}, "value": len(servers), "unit": "count", "level": "ok", "status": "success"
        })
        metrics_summary.append({
            "category": "fleet", "name": "avg_cpu_pct", "display": "Avg CPU",
            "labels": {}, "value": fleet_summary["avg_cpu_pct"], "unit": "%", "level": "ok", "status": "success", "query": cpu_query
        })
        metrics_summary.append({
            "category": "fleet", "name": "avg_mem_pct", "display": "Avg Memory",
            "labels": {}, "value": fleet_summary["avg_mem_pct"], "unit": "%", "level": "ok", "status": "success", "query": mem_query
        })
        metrics_summary.append({
            "category": "fleet", "name": "avg_disk_pct", "display": "Avg Disk(/)",
            "labels": {}, "value": fleet_summary["avg_disk_pct"], "unit": "%", "level": "ok", "status": "success", "query": disk_query
        })

        # 2. AI Analysis
        log("inspection", "Starting AI analysis...")
        ai_analysis = "AI analysis failed or not configured."
        
        if self.config.ark_api_key:
            prompt = json.dumps({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "targets": {"total": total_targets, "down": down_targets},
                "alerts": {"firing": firing},
                "fleet": fleet_summary,
            }, ensure_ascii=False, indent=2)
            system_prompt = (
                "你是一名专业资深的系统运维工程师（偏 SRE）。"
                "请基于我提供的巡检数据，输出一份可执行的中文巡检报告，聚焦：服务器资源使用状况、告警分析、影响面、处置建议与优先级。"
                "不要输出安全漏洞/CVE/风险扫描相关内容。"
                "输出结构必须包含：\n"
                "1) 总览（健康评分/关键结论）\n"
                "2) 资源热点（按CPU/内存/磁盘列出最需要关注的主机与原因）\n"
                "3) 告警分析（按严重度统计、Top告警、可能根因）\n"
                "4) 处置建议（P0/P1/P2，给出具体操作方向）\n"
                f"\n报告生成时间：{datetime.now().strftime('%Y-%m-%d')}\n"
            )
            
            # Detect provider
            model_id = self.config.ark_model_id.lower()
            if 'gemini' in model_id:
                log("inspection", f"Using Google Gemini API with model: {self.config.ark_model_id}")
                ai_analysis = self._call_gemini_api(prompt, system_prompt)
            elif self.config.ark_base_url:
                log("inspection", f"Using OpenAI compatible API with model: {self.config.ark_model_id}")
                ai_analysis = self._call_openai_compatible_api(prompt, system_prompt)
            else:
                log("inspection", "AI config missing Base URL for non-Gemini model")
                ai_analysis = "AI configuration error: Missing Base URL."
        else:
            log("inspection", "AI analysis skipped (not configured)")

        # 3. Comparison with yesterday
        log("inspection", "Comparing with yesterday's report...")
        yesterday_id = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        # yesterday_path = os.path.join(self.reports_dir, f"{yesterday_id}.json") # Deprecated
        compare_data = {"yesterday_id": yesterday_id, "delta": {"risk_score": 0.0, "down_targets": 0, "firing_alerts": 0}}
        
        # Define these variables early to avoid UnboundLocalError
        down_count = len(down_targets)
        firing_count = len(firing)

        try:
            # Try to load from DB first
            y_report = InspectionReport.objects.filter(report_id=yesterday_id).first()
            if y_report:
                y_data = y_report.content
                y_risk = y_data.get('risk_summary', {}).get('score', 0.0)
                y_reasons = y_data.get('risk_summary', {}).get('reasons', [])
                y_down = len(y_data.get('down_targets', []))
                y_firing = len(y_data.get('firing_alerts', []))
                
                # Compat Logic
                is_legacy = False
                if y_reasons and isinstance(y_reasons, list):
                    if "resource_max=OK" in y_reasons or "alerts_or_targets_down" in y_reasons:
                        is_legacy = True
                        
                y_health = y_risk
                if is_legacy:
                    y_health = 100 - y_risk
                
                compare_data["delta"] = {
                    "risk_score": round(health_score - y_health, 2),
                    "down_targets": down_count - y_down,
                    "firing_alerts": firing_count - y_firing
                }
        except:
            pass

        # 4. Calculate Dynamic Score
        health_score, health_level, health_reasons = self._calculate_health_score(down_targets, firing, servers)
        
        # 5. Predict Future
        forecast_data = self._predict_future_scores(health_score)

        critical_count = sum(1 for a in firing if str(a.get('severity') or '').lower() in ['critical', 'high'])
        warning_count = sum(1 for a in firing if str(a.get('severity') or '').lower() not in ['critical', 'high'])

        top_alerts = {}
        for a in firing:
            k = a.get('name') or 'Unknown'
            top_alerts[k] = top_alerts.get(k, 0) + 1
        top_alert_list = [{"name": k, "count": v} for k, v in sorted(top_alerts.items(), key=lambda x: x[1], reverse=True)[:10]]

        trend = []
        try:
            for i in range(6, -1, -1):
                d = (datetime.now().date() - timedelta(days=i)).strftime('%Y-%m-%d')
                r = InspectionReport.objects.filter(report_id=d).first()
                if r and r.content:
                    hs = r.content.get('health_summary', {}).get('score')
                    if hs is None:
                        hs = r.content.get('risk_summary', {}).get('score')
                    a_sum = r.content.get('alerts_summary', {})
                    f_total = a_sum.get('firing_total')
                    c_total = a_sum.get('critical_total')
                    fleet = r.content.get('fleet_summary', {})
                    trend.append({
                        "date": d,
                        "score": hs,
                        "firing": f_total,
                        "critical": c_total,
                        "avg_cpu": fleet.get('avg_cpu_pct'),
                        "avg_mem": fleet.get('avg_mem_pct'),
                        "avg_disk": fleet.get('avg_disk_pct'),
                    })
        except Exception:
            pass

        # 6. Final Report
        report = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "prometheus_status": "ok" if total_targets > 0 else "error",
            "down_targets": down_targets,
            "firing_alerts": firing,
            "alerts_summary": {
                "firing_total": len(firing),
                "critical_total": critical_count,
                "warning_total": warning_count,
                "top_alerts": top_alert_list,
            },
            "servers": servers,
            "fleet_summary": fleet_summary,
            "metrics_summary": metrics_summary,
            "ai_analysis": ai_analysis,
            "report_id": report_id,
            "score": health_score,
            "level": health_level,
            "health_summary": {
                "score": health_score,
                "level": health_level,
                "reasons": health_reasons
            },
            "compare_with_yesterday": compare_data,
            "forecast_7_15_30": {
                "predictions": forecast_data
            },
            "trend_7d": trend,
        }
        
        # Save to DB
        InspectionReport.objects.update_or_create(
            report_id=report_id,
            defaults={"content": report}
        )

        try:
            from ops_tickets.services import ensure_auto_tickets_from_inspection

            ensure_auto_tickets_from_inspection(report_id, report)
        except Exception as exc:
            log("inspection", f"Auto ops ticket creation skipped/failed: {exc}")
        
        log("inspection", "Inspection run completed.")
        return report

inspection_engine = InspectionEngine()
