import json
import logging
from ..models import Incident, AnalysisReport
import datetime
from django.utils import timezone
import requests
from inspection.models import InspectionConfig

try:
    from kubernetes import client, config
    K8S_AVAILABLE = True
except ImportError:
    K8S_AVAILABLE = False

logger = logging.getLogger(__name__)

class DiagnosticStrategy:
    """
    Defines how to collect diagnostic data for different types of alerts
    """
    @staticmethod
    def get_queries(alert_name, labels):
        """
        Returns a dict of {metric_name: promql_query} based on alert type
        """
        queries = {}
        instance = labels.get('instance')
        node = labels.get('node') or labels.get('nodename')
        namespace = labels.get('namespace')
        pod = labels.get('pod')

        # Base filter
        # Prefer 'node' label if available for cAdvisor/Kubelet metrics, otherwise try instance
        # Note: instance in node_exporter is usually IP:Port, in cAdvisor it might be NodeName
        node_filter_cadvisor = f'node="{node}"' if node else (f'instance="{instance}"' if instance else "")
        node_filter_nodeexp = f'instance="{instance}"' if instance else (f'node="{node}"' if node else "")
        
        pod_filter = f'namespace="{namespace}", pod="{pod}"' if namespace and pod else ""

        if 'CPU' in alert_name:
            if pod_filter:
                # Pod level CPU
                queries['pod_cpu_usage'] = f'rate(container_cpu_usage_seconds_total{{{pod_filter}}}[5m])'
            else:
                # Node level CPU
                if node_filter_nodeexp:
                    queries['node_cpu_usage'] = f'100 - (avg by (instance) (rate(node_cpu_seconds_total{{mode="idle", {node_filter_nodeexp}}}[5m])) * 100)'
                
                # Top 5 Processes/Containers on the node
                # We use a broad regex for instance if we only have IP, or just rely on node label if present
                filter_str = node_filter_cadvisor if node_filter_cadvisor else 'id="/"' # Fallback
                queries['top10_cpu_containers'] = f'topk(10, sort_desc(rate(container_cpu_usage_seconds_total{{{filter_str}}}[5m])))'

        elif 'Memory' in alert_name:
            if pod_filter:
                queries['pod_memory_usage'] = f'container_memory_usage_bytes{{{pod_filter}}}'
            else:
                if node_filter_nodeexp:
                    queries['node_memory_usage'] = f'100 * (1 - node_memory_MemFree_bytes{{{node_filter_nodeexp}}} / node_memory_MemTotal_bytes{{{node_filter_nodeexp}}})'
                
                filter_str = node_filter_cadvisor if node_filter_cadvisor else 'id="/"'
                queries['top10_mem_containers'] = f'topk(10, sort_desc(container_memory_usage_bytes{{{filter_str}}}))'

        elif 'IO' in alert_name or 'Disk' in alert_name:
            if pod_filter:
                queries['pod_io_read'] = f'rate(container_fs_reads_bytes_total{{{pod_filter}}}[5m])'
                queries['pod_io_write'] = f'rate(container_fs_writes_bytes_total{{{pod_filter}}}[5m])'
            else:
                if node_filter_nodeexp:
                    queries['node_disk_read'] = f'rate(node_disk_read_bytes_total{{{node_filter_nodeexp}}}[5m])'
                    queries['node_disk_write'] = f'rate(node_disk_written_bytes_total{{{node_filter_nodeexp}}}[5m])'
                    queries['node_disk_util'] = f'rate(node_disk_io_time_seconds_total{{{node_filter_nodeexp}}}[5m])'
                
                filter_str = node_filter_cadvisor if node_filter_cadvisor else 'id="/"'
                queries['top10_io_containers'] = f'topk(10, sort_desc(rate(container_fs_writes_bytes_total{{{filter_str}}}[5m]) + rate(container_fs_reads_bytes_total{{{filter_str}}}[5m])))'

        return queries

class FaultAnalyzer:
    def __init__(self, incident: Incident):
        self.incident = incident
        self.config = InspectionConfig.load()

    def analyze(self):
        logger.info(f"Starting analysis for incident {self.incident.id}")
        self.incident.status = 'analyzing'
        self.incident.save(update_fields=['status'])

        try:
            # 1. Parse Alert & Gather Context
            context_data = self._gather_context()
            
            # 2. Check AI Switch
            from ..models import AIConfig
            ai_config = AIConfig.get_active_config()
            
            if ai_config.enable_ai_analysis:
                # Call AI
                ai_result = self._call_ai_service(context_data)
            else:
                # Self Analysis based on Prometheus metrics
                ai_result = self._analyze_without_ai(context_data)
            
            # 3. Save Report
            AnalysisReport.objects.create(
                incident=self.incident,
                phenomenon=ai_result.get('phenomenon', 'Unknown phenomenon'),
                root_cause=ai_result.get('root_cause', 'Unknown root cause'),
                mitigation=ai_result.get('mitigation', 'No immediate mitigation'),
                prevention=ai_result.get('prevention', 'No prevention strategy'),
                refactoring=ai_result.get('refactoring', 'No refactoring needed'),
                solutions=ai_result.get('solutions', []),
                related_metrics=context_data.get('metrics', {}),
                diagnosis_logs=context_data.get('logs', []),
                k8s_events=context_data.get('events', []),
                k8s_pod_status=context_data.get('pod_status', {}),
                raw_ai_response=json.dumps(ai_result)
            )
            
            self.incident.status = 'analyzed'
            self.incident.save(update_fields=['status'])
            logger.info(f"Analysis completed for incident {self.incident.id}")

        except Exception as e:
            logger.error(f"Analysis failed: {e}", exc_info=True)
            self.incident.status = 'open'
            self.incident.save(update_fields=['status'])

    def _analyze_without_ai(self, context):
        """
        Generate a report based on Prometheus metrics without calling LLM.
        """
        alert_name = self.incident.alert_name
        metrics = context.get('metrics', {})
        
        # Basic construction of report from metrics
        phenomenon = f"Detected {alert_name} alert."
        root_cause = "Automatic analysis disabled. Please check metrics below."
        
        # Try to find high resource consumers from metrics keys
        # The keys in DiagnosticStrategy are like 'top10_cpu_containers', 'top10_mem_containers'
        
        top_consumers = []
        for k, v in metrics.items():
            if 'top10' in k and v:
                # v is a list of results. Each result has 'metric' dict and 'value' list.
                for item in v[:3]: # Take top 3
                    metric_labels = item.get('metric', {})
                    pod = metric_labels.get('pod') or metric_labels.get('name') or metric_labels.get('id', 'unknown')
                    val = item.get('value', [0, 0])[1]
                    top_consumers.append(f"{k}: {pod} ({val})")
        
        if top_consumers:
            root_cause = f"Top resource consumers identified: {', '.join(top_consumers)}"
            
        return {
            "phenomenon": phenomenon,
            "root_cause": root_cause,
            "mitigation": "Check the highlighted pods/processes.",
            "prevention": "Adjust resource limits or scale out.",
            "refactoring": "Analyze application performance profiles.",
            "solutions": ["kubectl top pod", "kubectl get events"]
        }


    def _gather_context(self):
        raw = self.incident.raw_alert_data
        labels = raw.get('labels', {})
        alert_name = self.incident.alert_name
        
        context = {
            "alert": raw,
            "metrics": {},
            "logs": [], # Placeholder for future command outputs (e.g. top/iotop)
            "events": [],
            "pod_status": {}
        }

        # 1. Metric Collection Strategy
        queries = DiagnosticStrategy.get_queries(alert_name, labels)
        
        # Execute queries
        if self.config.prometheus_url:
            for name, query in queries.items():
                try:
                    context['metrics'][name] = self._query_prometheus(query)
                except Exception as e:
                    logger.warning(f"Failed to query metric {name}: {e}")

        # 2. Log Collection Strategy (K8s)
        if K8S_AVAILABLE:
            try:
                k8s_data = self._collect_k8s_info(labels)
                if k8s_data:
                    # Strategy: Provide BOTH Describe info and Logs to AI
                    
                    # 1. Always append Describe/Event summary
                    context['logs'].append(f"--- Pod Describe / Events ---\n{k8s_data['text_summary']}")
                    
                    # 2. If Logs exist, append them as well
                    if k8s_data.get('logs'):
                         logs_str = "\n".join(k8s_data['logs'])
                         context['logs'].append(f"--- Pod Logs ---\n{logs_str}")

                    context['events'] = k8s_data.get('events', [])
                    context['pod_status'] = k8s_data.get('pod_status', {})
                else:
                    # Fallback if no pod found or logs empty: use Pod Describe info
                    # _collect_k8s_info already includes describe-like info (status, conditions, events)
                    # If it returns None, it means Pod not found.
                    pass
            except Exception as e:
                logger.warning(f"Failed to fetch K8s info: {e}")
                
        # 3. Add Alert Description (if available)
        # If no logs, this description is crucial for AI
        description = raw.get('annotations', {}).get('description') or raw.get('annotations', {}).get('message')
        if description:
             context['logs'].append(f"--- Alert Description ---\n{description}")

        return context

    def _collect_k8s_info(self, labels):
        try:
            config.load_incluster_config()
        except:
            try:
                config.load_kube_config()
            except:
                logger.warning("No K8s config found")
                return None
        
        v1 = client.CoreV1Api()
        app_v1 = client.AppsV1Api()
        
        namespace = labels.get('namespace', 'default')
        pod_name = labels.get('pod')
        
        # If pod is not directly in labels, try to find it via deployment
        if not pod_name:
            deployment = labels.get('deployment')
            if deployment:
                try:
                    pods = v1.list_namespaced_pod(namespace)
                    for p in pods.items:
                        if p.metadata.name.startswith(deployment):
                            pod_name = p.metadata.name
                            break
                except Exception as e:
                    logger.warning(f"Failed to list pods for deployment {deployment}: {e}")

        if not pod_name:
            return None

        result = {
            "text_summary": "",
            "logs": [],
            "events": [],
            "pod_status": {}
        }
        
        info_lines = []
        try:
            # 1. Fetch Pod Object
            pod = v1.read_namespaced_pod(name=pod_name, namespace=namespace)
            
            # --- Emulate `kubectl describe pod` output structure ---
            
            # Header Info
            info_lines.append(f"Name:         {pod.metadata.name}")
            info_lines.append(f"Namespace:    {pod.metadata.namespace}")
            info_lines.append(f"Priority:     {pod.spec.priority or 0}")
            info_lines.append(f"Node:         {pod.spec.node_name}/{pod.status.host_ip}")
            info_lines.append(f"Start Time:   {pod.status.start_time}")
            info_lines.append(f"Labels:       {json.dumps(pod.metadata.labels, indent=2)}")
            info_lines.append(f"Annotations:  {json.dumps(pod.metadata.annotations, indent=2)}")
            info_lines.append(f"Status:       {pod.status.phase}")
            info_lines.append(f"IP:           {pod.status.pod_ip}")
            
            # Controllers
            if pod.metadata.owner_references:
                controllers = [f"{ref.kind}/{ref.name}" for ref in pod.metadata.owner_references]
                info_lines.append(f"Controlled By: {', '.join(controllers)}")
            
            # Containers Detail
            info_lines.append("\nContainers:")
            for c in pod.spec.containers:
                info_lines.append(f"  {c.name}:")
                info_lines.append(f"    Image:          {c.image}")
                
                # Find container status
                c_status = next((s for s in (pod.status.container_statuses or []) if s.name == c.name), None)
                if c_status:
                    info_lines.append(f"    Container ID:   {c_status.container_id}")
                    # State
                    if c_status.state.running:
                        info_lines.append(f"    State:          Running")
                        info_lines.append(f"      Started:      {c_status.state.running.started_at}")
                    elif c_status.state.waiting:
                        info_lines.append(f"    State:          Waiting")
                        info_lines.append(f"      Reason:       {c_status.state.waiting.reason}")
                        info_lines.append(f"      Message:      {c_status.state.waiting.message}")
                    elif c_status.state.terminated:
                        info_lines.append(f"    State:          Terminated")
                        info_lines.append(f"      Reason:       {c_status.state.terminated.reason}")
                        info_lines.append(f"      Exit Code:    {c_status.state.terminated.exit_code}")
                    
                    info_lines.append(f"    Ready:          {c_status.ready}")
                    info_lines.append(f"    Restart Count:  {c_status.restart_count}")
                
                # Limits/Requests
                resources = c.resources
                if resources:
                    if resources.limits:
                        info_lines.append(f"    Limits:         {resources.limits}")
                    if resources.requests:
                        info_lines.append(f"    Requests:       {resources.requests}")
                
                # Ports
                if c.ports:
                    ports = [f"{p.container_port}/{p.protocol}" for p in c.ports]
                    info_lines.append(f"    Ports:          {', '.join(ports)}")

            # Conditions
            info_lines.append("\nConditions:")
            info_lines.append("  Type              Status")
            if pod.status.conditions:
                for cond in pod.status.conditions:
                    info_lines.append(f"  {cond.type:<17} {cond.status}")
            
            # Events
            info_lines.append("\nEvents:")
            info_lines.append("  Type    Reason     Age    From               Message")
            info_lines.append("  ----    ------     ---    ----               -------")
            
            try:
                events = v1.list_namespaced_event(namespace, field_selector=f'involvedObject.name={pod_name}')
                # Sort events by timestamp
                sorted_events = sorted(events.items, key=lambda e: e.last_timestamp or e.event_time or datetime.datetime.min)
                
                for e in sorted_events:
                    # Calculate age (approx)
                    age = "N/A"
                    if e.last_timestamp:
                        delta = timezone.now() - e.last_timestamp
                        age = f"{int(delta.total_seconds())}s"
                    
                    source = e.source.component if e.source else ""
                    msg = (e.message[:100] + '..') if e.message and len(e.message) > 100 else e.message
                    info_lines.append(f"  {e.type:<7} {e.reason:<10} {age:<6} {source:<18} {msg}")
                    
                    # Also populate structured result for frontend
                    result['events'].append({
                        "type": e.type,
                        "reason": e.reason,
                        "message": e.message,
                        "count": e.count,
                        "last_timestamp": e.last_timestamp.isoformat() if e.last_timestamp else None
                    })
            except Exception as e:
                info_lines.append(f"  <Failed to fetch events: {e}>")

            result['text_summary'] = "\n".join(info_lines)
            
            # --- End Emulation ---

            # Also populate pod_status structure for frontend cards
            result['pod_status'] = {
                "name": pod.metadata.name,
                "namespace": pod.metadata.namespace,
                "phase": pod.status.phase,
                "conditions": [{"type": c.type, "status": c.status} for c in (pod.status.conditions or [])],
                "containers": []
            }
            
            for cs in (pod.status.container_statuses or []):
                state = "Running"
                if cs.state.waiting: state = f"Waiting ({cs.state.waiting.reason})"
                elif cs.state.terminated: state = f"Terminated ({cs.state.terminated.reason})"
                
                result['pod_status']['containers'].append({
                    "name": cs.name,
                    "state": state,
                    "restart_count": cs.restart_count,
                    "ready": cs.ready
                })

            # 3. Collect Logs (Strategy: Always try, append if successful)
            # Logic: If pod is in a state where logs are expected (even crashloop), fetch them.
            # Only skip if strictly initializing and API would block/fail? 
            # Actually read_namespaced_pod_log usually works unless container never started.
            # We try anyway and catch exception.
            
            try:
                # Fetch logs (limit 50 lines)
                logs = v1.read_namespaced_pod_log(name=pod_name, namespace=namespace, tail_lines=50)
                if logs:
                    result['logs'].append(logs)
                
                # If previous instance failed, try to get previous logs
                container_statuses = pod.status.container_statuses or []
                for cs in container_statuses:
                    if cs.restart_count > 0:
                         prev_logs = v1.read_namespaced_pod_log(name=pod_name, namespace=namespace, tail_lines=20, previous=True)
                         if prev_logs:
                             result['logs'].append(f"Previous Instance:\n{prev_logs}")
                         break # Only fetch for one container to avoid spam
            except Exception as e:
                # Log fetch failed (e.g. container creating, or CRI error)
                # We do NOT return None here, we just don't have logs.
                # The text_summary (describe info) is still valuable.
                pass

            return result

        except Exception as e:
            logger.error(f"Error analyzing pod {pod_name}: {e}")
            return None

    def _query_prometheus(self, query):
        if not self.config.prometheus_url:
            return []
        
        url = f"{self.config.prometheus_url}/api/v1/query_range"
        now = timezone.now()
        start = now - datetime.timedelta(hours=1)
        
        try:
            response = requests.get(url, params={
                "query": query,
                "start": start.timestamp(),
                "end": now.timestamp(),
                "step": "60s"
            }, timeout=5)
            response.raise_for_status()
            data = response.json()
            return data.get('data', {}).get('result', [])
        except Exception as e:
            logger.error(f"Prometheus query failed: {e}")
            return []

    def _call_ai_service(self, context):
        """
        Mock implementation of calling AI Service (ChatGPT/DeepSeek)
        """
        from ..models import AIConfig
        config = AIConfig.get_active_config()
        
        alert_name = self.incident.alert_name
        labels = self.incident.raw_alert_data.get('labels', {})
        
        # Build prompt using stored template
        # Use replace instead of format to avoid KeyError on JSON braces in the template
        prompt = config.prompt_template
        prompt = prompt.replace("{alert_name}", str(alert_name))
        prompt = prompt.replace("{raw_data}", json.dumps(self.incident.raw_alert_data, ensure_ascii=False))
        prompt = prompt.replace("{metrics}", json.dumps(context.get('metrics', {}), ensure_ascii=False))
        prompt = prompt.replace("{logs}", "\n".join(context.get('logs', [])))
        
        logger.info(f"AI Prompt: {prompt}")

        if config.api_key:
            try:
                headers = {
                    "Authorization": f"Bearer {config.api_key}",
                    "Content-Type": "application/json"
                }
                
                # Adjust for different providers if needed, but OpenAI format is standard
                payload = {
                    "model": config.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": config.temperature,
                    "max_tokens": config.max_tokens
                }

                response = requests.post(
                    f"{config.api_base}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=30
                )
                response.raise_for_status()
                
                result = response.json()
                content = result['choices'][0]['message']['content']
                
                # Attempt to parse JSON from content (it might be wrapped in ```json ... ```)
                if '```json' in content:
                    content = content.split('```json')[1].split('```')[0].strip()
                elif '```' in content:
                    content = content.split('```')[1].strip()
                    
                return json.loads(content)
            except Exception as e:
                logger.error(f"AI Service Call Failed: {e}. Falling back to rule-based mock.")
        
        # Fallback / Mock Chinese response based on alert type
        if 'IO' in alert_name or 'Disk' in alert_name:
            return {
                "phenomenon": f"节点 {labels.get('instance', 'unknown')} 的磁盘 I/O 延迟飙升至 500ms。",
                "root_cause": "容器 'mysql-0' 内的进程 'mysql-backup' (PID 1234) 正在进行全量数据备份，且未设置 I/O 限制。",
                "mitigation": "1. 暂时使用 `ionice` 限制备份进程的 I/O 优先级。\n2. 如果严重影响生产业务，建议终止备份任务。",
                "prevention": "为所有备份 CronJob 配置 `ionice`。在备份容器上设置 IOPS 限制 (Docker/K8s limits)。",
                "refactoring": "架构优化：启用专用的只读从库 (Read-Replica) 进行备份，避免影响主库性能。",
                "solutions": ["kill 1234", "ionice -c3 -p 1234"]
            }
        
        if 'CPU' in alert_name:
            return {
                "phenomenon": f"节点 {labels.get('instance', 'unknown')} CPU 使用率超过 90%。",
                "root_cause": "Java 应用 'payment-service' 发生死循环，导致 CPU 满载。",
                "mitigation": "重启该 Pod。",
                "prevention": "设置 CPU Limit，防止单应用耗尽节点资源。",
                "refactoring": "优化代码逻辑，修复死循环 Bug。",
                "solutions": ["kubectl delete pod payment-service-xxx"]
            }

        return {
            "phenomenon": "检测到未知异常。",
            "root_cause": "需要进一步人工排查。",
            "mitigation": "检查系统日志。",
            "prevention": "完善监控指标。",
            "refactoring": "暂无建议。",
            "solutions": []
        }

    def _build_prompt(self, context):
        return f"""
        You are a Site Reliability Engineer (SRE). Analyze the following system alert and context data.
        
        Alert: {json.dumps(context['alert'])}
        Metrics (Top Consumers): {json.dumps(context['metrics'])}
        Logs: {json.dumps(context['logs'])}
        
        Please provide a structured analysis in JSON format with the following keys:
        - phenomenon: What is happening?
        - root_cause: Specifically which process/pod is responsible? Why?
        - mitigation: How to fix it immediately?
        - prevention: How to prevent recurrence (config changes)?
        - refactoring: Long-term architectural fixes?
        - solutions: A list of short command-like actions.
        """
