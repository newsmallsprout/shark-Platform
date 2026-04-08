import request from '@/utils/request'

export interface TrafficSummaryPayload {
  stream_key: string | null
  summary: Record<string, unknown> | null
  hint?: string
}

export interface LogInsightRow {
  id: string
  stream_key: string
  insight_type: string
  severity: string
  title: string
  body: string
  evidence: Record<string, unknown>
  source: string
  created_at: string
}

export const observabilityApi = {
  getTrafficSummary: (params?: { stream_key?: string; minutes?: number }) =>
    request.get<TrafficSummaryPayload>('/observability/traffic/summary/', { params }),

  listInsights: (params?: { stream_key?: string; limit?: number }) =>
    request.get<{ insights: LogInsightRow[] }>('/observability/insights/', { params }),

  listStreams: () => request.get<{ streams: Array<{ stream_key: string; display_name: string; last_event_at: string | null }> }>('/observability/streams/'),

  requestAnalyze: (stream_key: string, window_minutes = 60) =>
    request.post<{ status: string; stream_key?: string; insights_created?: number }>(
      '/observability/traffic/analyze/',
      { stream_key, window_minutes },
    ),
}
