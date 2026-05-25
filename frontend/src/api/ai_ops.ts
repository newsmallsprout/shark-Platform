import request from '@/utils/request'

export const aiOpsApi = {
  getIncidents: () => request.get('/ai_ops/incidents'),
  getIncidentDetail: (id: number) => request.get(`/ai_ops/incidents/${id}`),
  getConfig: () => request.get('/ai_ops/config'),
  updateConfig: (data: any) => request.post('/ai_ops/config', data),
}
