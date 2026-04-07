import request from '@/utils/request'

export interface SystemStats {
  resources: {
    cpu: { value: string; percentage: number }
    memory: { value: string; percentage: number; total: string }
    disk: { value: string; percentage: number; total: string }
    load: string
  }
  health: Array<{ name: string; desc: string; status: string }>
}

export const systemApi = {
  getStats: () => request.get<SystemStats>('/system/stats'),
}
