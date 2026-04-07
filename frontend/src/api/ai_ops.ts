import request from '@/utils/request'

export interface DiagnoseResponse {
  status: string
  run_id: string
  sse_stream_url: string
}

export interface TicketPayload {
  ticket_id: string
  incident_id: number
  run_id: string
  status: string
  summary: string
  root_cause: string
  proposed_action: string
  approval_comment?: string
  approved_at?: string | null
  executed_at?: string | null
  ticket_class?: string
  impact_scope?: Record<string, unknown>
  ai_confidence?: number
  routing?: string
  auto_heal_dispatched?: boolean
}

export interface DashboardSummary {
  health_score: number
  topology: { nodes: TopoNode[]; edges: TopoEdge[] }
  ai_status: 'idle' | 'analyzing' | 'degraded'
  open_incidents: number
  pending_tickets: Array<{
    ticket_id: string
    summary: string
    status: string
    routing: string
    ai_confidence: number
  }>
  recent_heals: Array<{
    ticket_id: string
    summary: string
    executed_at: string | null
    routing: string
  }>
  knowledge_entries: number
  auto_heal_threshold: number
}

export interface TopoNode {
  id: string
  label: string
  healthy?: boolean
}

export interface TopoEdge {
  from: string
  to: string
}

/** POST tickets/:id/reject/ — 打回并触发新一轮 LangGraph */
export interface RejectRetryResponse {
  status: string
  new_run_id?: string
  new_sse_stream_url?: string
  ticket?: TicketPayload
}

export const aiOpsApi = {
  getDashboard: () => request.get<DashboardSummary>('/ai_ops/dashboard/'),
  getIncidents: () => request.get('/ai_ops/incidents'),
  getIncidentDetail: (id: number) => request.get(`/ai_ops/incidents/${id}`),
  getConfig: () => request.get('/ai_ops/config'),
  updateConfig: (data: any) => request.post('/ai_ops/config', data),
  /** LangGraph + Celery；可选 operator_context 人工排障指引 */
  diagnose: (incidentId: number | string, data?: { operator_context?: string }) =>
    request.post<DiagnoseResponse>(`/ai_ops/diagnose/${incidentId}/`, data ?? {}),
  getTicket: (ticketId: string) => request.get<TicketPayload>(`/ai_ops/tickets/${ticketId}`),
  submitTicket: (ticketId: string) => request.post<TicketPayload>(`/ai_ops/tickets/${ticketId}/submit/`),
  approveTicket: (ticketId: string, comment?: string) =>
    request.post<TicketPayload>(`/ai_ops/tickets/${ticketId}/approve/`, { comment: comment || '' }),
  rejectTicket: (ticketId: string, data: { reason: string }) =>
    request.post<RejectRetryResponse>(`/ai_ops/tickets/${ticketId}/reject/`, data),
}
