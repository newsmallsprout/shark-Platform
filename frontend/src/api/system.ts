import request from '@/utils/request'
import type { MonitorConfig, InspectionReport } from '@/types/system'

export const systemApi = {
  // Monitor
  getMonitorTasks: () => request.get<any[]>('/monitor/tasks'),
  saveMonitorTask: (task: any) => request.post('/monitor/tasks', task),
  updateMonitorTask: (id: number, task: any) => request.put(`/monitor/tasks/${id}`, task),
  deleteMonitorTask: (id: number) => request.delete(`/monitor/tasks/${id}`),
  getMonitorLogs: (params: any) => request.get<any[]>('/monitor/logs', { params }),
  getLogContent: (params: any) => request.get<{content: string}>('/monitor/logs/view', { 
    params,
    timeout: 120000 // 120s for log searching
  }),
  
  // Inspection
  getReports: () => request.get<{items: any[]}>('/inspection/reports').then(res => res.items),
  runInspection: (config?: any) => request.post<any>('/inspection/run', config ?? {}, { timeout: 300000 }),
  getReportDetail: (id: string) => request.get<any>(`/inspection/reports/${id}`),
  getInspectionConfig: () => request.get<any>('/inspection/config'),
  saveInspectionConfig: (config: any) => request.post('/inspection/config', config),
  listInspectionIgnores: () => request.get<{items: any[]}>('/inspection/ignores').then(res => res.items || []),
  addInspectionIgnore: (payload: { key: string; label?: string; check_id?: string; note?: string }) =>
    request.post('/inspection/ignores', payload),
  removeInspectionIgnore: (key: string) => request.delete('/inspection/ignores', { params: { key } }),
  
  // Stats
  getSystemStats: () => request.get<any>('/system/stats'),
  
  // Deploy
  getServers: () => request.get<{servers: any[]}>('/deploy/servers'),
  saveServer: (server: any) => request.post('/deploy/servers', server),
  deleteServer: (id: string) => request.delete(`/deploy/servers/${id}`),
  runDeploy: (plan: any) => request.post<{plan_id: string}>('/deploy/run', plan),
  getPlan: (id: string) => request.get<any>(`/deploy/plans/${id}`)
}
