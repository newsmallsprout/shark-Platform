import request from '@/utils/request'

export type TrafficLogSourceRow = {
  id: string
  label: string
  file_path: string
  redis_key: string
  /** 与 go-log-collector 的每流格式一致；空=用全局「日志格式」 */
  log_format?: string
}

export const trafficApi = {
  sources: () => request.get('/traffic/sources') as Promise<{ items: { id: string; label: string }[] }>,
  /** 一次拉齐大盘数据，长超时；替代多路 overview/timeseries/geo/top 并行 */
  snapshot: (
    range: string,
    source?: string,
    opts?: { start?: string; end?: string; fullData?: boolean },
  ) =>
    request.get('/traffic/snapshot', {
      params: {
        range,
        ...(source ? { source } : {}),
        ...(opts?.start ? { start: opts.start } : {}),
        ...(opts?.end ? { end: opts.end } : {}),
        ...(opts?.fullData ? { full_data: 1 } : {}),
      },
      timeout: 120000,
    }) as Promise<Record<string, unknown>>,
  overview: (range: string, source?: string) =>
    request.get('/traffic/overview', { params: { range, ...(source ? { source } : {}) } }),
  timeseries: (range: string, source?: string) =>
    request.get('/traffic/timeseries', { params: { range, ...(source ? { source } : {}) } }),
  geo: (range: string, granularity = 'country', country = '', source?: string) =>
    request.get('/traffic/geo', {
      params: { range, granularity, country, ...(source ? { source } : {}) },
    }),
  top: (range: string, type: string, limit = 10, source?: string) =>
    request.get('/traffic/top', {
      params: { range, type, limit, ...(source ? { source } : {}) },
    }),
  blackbox: () => request.get('/traffic/blackbox'),
  jaegerTraces: (params?: { range?: string; start?: string; end?: string; service?: string; limit?: string }) =>
    request.get('/traffic/jaeger/traces', { params, timeout: 20000 }),
  jaegerTraceDetail: (traceId: string) =>
    request.get(`/traffic/jaeger/trace/${encodeURIComponent(traceId)}`, { timeout: 30000 }),
  getConfig: () => request.get('/traffic/config'),
  saveConfig: (data: Record<string, unknown>) => request.post('/traffic/config', data),
}
