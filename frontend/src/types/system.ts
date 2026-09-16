export interface MonitorConfig {
  enabled: boolean
  k8s_namespace: string
  k8s_container_name: string
  k8s_label_selector: string
  k8s_tail_lines: number
  include_keywords: string[]
  exclude_keywords: string[]
  s3_bucket: string
  s3_endpoint: string
  s3_access_key: string
  s3_secret_key: string
  s3_region: string
  s3_archive_enabled: boolean
  slack_webhook_url: string
}

export interface MonitorTask {
  task_id: string
  status: string
  metrics: any
}

export interface InspectionReport {
  report_id: string
  timestamp?: string
  score: number
  summary: string
  ai_analysis?: string
  metrics_summary?: any[]
  health_summary?: { score: number; level?: string; reasons?: string[] }
  fleet_summary?: {
    server_count: number
    avg_cpu_pct?: number
    avg_mem_pct?: number
    avg_disk_pct?: number
    top_cpu?: any[]
    top_mem?: any[]
    top_disk?: any[]
  }
  alerts_summary?: {
    firing_total: number
    critical_total: number
    warning_total: number
    top_alerts?: { name: string; count: number }[]
  }
  servers?: any[]
  verdict?: string
  findings?: string[]
  checklist?: { id?: string; name: string; level: string; result: string; source?: string; detail?: string[]; items?: { key?: string; label: string; when?: string }[] }[]
  pvc_usage?: { key: string; namespace?: string; pvc?: string; service: string; pct: number; used_bytes: number; capacity_bytes: number; baseline?: string }[]
  workloads?: {
    key?: string
    kind?: string
    namespace?: string
    name?: string
    service: string
    desired?: number
    ready?: number
    level?: string
    pods?: { pod: string; phase: string; ready?: boolean | null; waiting?: string; pod_ip?: string; host_ip?: string; node?: string; restarts?: number; level?: string }[]
  }[]
  workload_pods?: { key: string; namespace?: string; pod: string; phase: string; ready?: boolean | null; waiting?: string; service: string; aliased?: boolean; level: string; pod_ip?: string; host_ip?: string; node?: string }[]
  services?: { service: string; status: string; summary: string; baseline?: string }[]
  elasticsearch?: {
    available?: boolean
    clusters?: { cluster: string; status?: string; nodes?: number; data_nodes?: number; unassigned_shards?: number; active_shards?: number }[]
    heap_nodes?: { cluster: string; node: string; heap_pct: number; used_bytes: number; max_bytes: number }[]
  }
  middleware?: {
    available?: boolean
    discovered_names?: number
    items?: { id: string; name: string; source: string; level: string; result: string; up?: number; down?: number; cpu_pct?: number | null; mem_pct?: number | null; disk_pct?: number | null; mem_text?: string; disk_text?: string; instances?: string[]; metrics?: string[] }[]
  }
  discovery?: { scanned?: boolean; metric_name_count?: number; middleware_families?: number }
  known_normals?: string[]
  decommissioned?: { kind?: string; name?: string; job?: string; instance?: string; label?: string; when?: string; last_scrape?: string; persistent?: boolean; key?: string }[]
  trend_7d?: { date: string; score?: number; firing?: number; critical?: number; avg_cpu?: number; avg_mem?: number; avg_disk?: number }[]
  forecast_7_15_30?: any
}
