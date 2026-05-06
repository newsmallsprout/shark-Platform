import request from '@/utils/request'

export interface MonitorTask {
  id?: number
  name: string
  enabled: boolean
  k8s_namespace: string
  k8s_kubeconfig: string
  /** Present on API responses when kubeconfig is stored server-side; plaintext is never returned. */
  k8s_kubeconfig_set?: boolean
  s3_archive_enabled: boolean
  s3_bucket: string
  s3_region: string
  s3_access_key: string
  s3_secret_key: string
  s3_endpoint: string
  retention_days: number
  alert_enabled: boolean
  slack_webhook_url: string
  poll_interval_seconds: number
  
  // New Fields
  immediate_keywords?: string[]
  ignore_keywords?: string[]
  record_only_keywords?: string[]
  alert_threshold_count?: number
  alert_threshold_window?: number
  alert_silence_minutes?: number
  alert_keywords?: string[]
  
  last_run?: string
  last_error?: string
  alerts_sent_count?: number
}

export const monitorApi = {
  getTasks: () => request.get<MonitorTask[]>('/monitor/tasks'),
  getTask: (id: number) => request.get<MonitorTask>(`/monitor/tasks/${id}`),
  createTask: (data: Partial<MonitorTask>) => request.post<MonitorTask>('/monitor/tasks', data),
  updateTask: (id: number, data: Partial<MonitorTask>) => request.put<MonitorTask>(`/monitor/tasks/${id}`, data),
  deleteTask: (id: number) => request.delete(`/monitor/tasks/${id}`),
  
  getLogs: (taskId: number, params?: any) => request.get<{files: any[], total: number}>('/monitor/logs', { params: { task_id: taskId, ...params } }),

  viewLog: (taskId: number, filename: string, params?: any) => 
    request.get<{content: string, total: number}>('/monitor/logs/view', { params: { task_id: taskId, filename, ...params } }),
  batchViewLogs: (taskId: number, filenames: string[], keyword: string) => 
    request.post<{results: any[]}>('/monitor/logs/batch_search', { task_id: taskId, filenames, keyword }),
  downloadLog: (taskId: number, filename: string) => `/api/monitor/logs/download?task_id=${taskId}&filename=${encodeURIComponent(filename)}`,

  getIndexHistory: (taskId: number, params: any) =>
    request.get<{ items: any[]; total: number; page: number; page_size: number }>('/monitor/logs/history', { params: { task_id: taskId, ...params } }),
  getIndexDetail: (taskId: number, key: string) =>
    request.get<any>('/monitor/logs/index_detail', { params: { task_id: taskId, key } }),
}
