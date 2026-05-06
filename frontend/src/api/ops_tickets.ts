import request from '@/utils/request'

export interface OpsTicketItem {
  id: number
  title: string
  description: string
  inspection_report_id: string
  inspection_snapshot: Record<string, unknown>
  severity: string
  status: string
  created_by: number | null
  created_by_username?: string
  assigned_to: number | null
  assigned_to_username?: string
  resolution_notes: string
  created_at: string
  updated_at: string
}

export const opsTicketsApi = {
  list(): Promise<{ items: OpsTicketItem[] }> {
    return request.get('/ops/tickets/')
  },
  create(payload: {
    title: string
    description?: string
    inspection_report_id: string
    inspection_snapshot?: Record<string, unknown>
    severity?: string
  }) {
    return request.post<OpsTicketItem>('/ops/tickets/', payload)
  },
  get(id: number) {
    return request.get<OpsTicketItem>(`/ops/tickets/${id}/`)
  },
  patch(id: number, payload: Partial<{ status: string; severity: string; assigned_to: number | null; resolution_notes: string }>) {
    return request.patch<OpsTicketItem>(`/ops/tickets/${id}/`, payload)
  },
}
