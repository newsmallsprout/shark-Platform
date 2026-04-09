<template>
  <div class="ops-dash">
    <nav class="bc" aria-label="面包屑">
      <span>首页</span>
      <span class="bc-sep">/</span>
      <span class="bc-here">运营数据大屏</span>
    </nav>

    <header class="page-head">
      <div class="page-head-text">
        <h1 class="page-title">运营数据大屏</h1>
        <p class="page-sub">
          运行环境、告警与自愈趋势、拓扑与工单一屏可读；数据来自中心库与主机采样（psutil）。
        </p>
      </div>
      <div v-if="sysStats" class="resource-strip" aria-label="主机资源">
        <div class="res-item">
          <span class="res-label">CPU</span>
          <div class="res-bar-wrap">
            <div
              class="res-bar-fill"
              :style="{ width: `${Math.min(100, sysStats.resources.cpu.percentage)}%` }"
            />
          </div>
          <span class="res-val mono">{{ sysStats.resources.cpu.value }}</span>
        </div>
        <div class="res-item">
          <span class="res-label">内存</span>
          <div class="res-bar-wrap">
            <div
              class="res-bar-fill res-bar-fill--mem"
              :style="{ width: `${Math.min(100, sysStats.resources.memory.percentage)}%` }"
            />
          </div>
          <span class="res-val mono">
            {{ sysStats.resources.memory.value }} / {{ sysStats.resources.memory.total }}
          </span>
        </div>
      </div>
    </header>

    <div class="notice-banner" role="status">
      <span class="notice-dot" aria-hidden="true" />
      拓扑与健康分由快照与开放事件推算；24h 趋势按整点桶聚合。边缘节点心跳写入缓存，大屏不单独枚举主机名。
    </div>

    <div class="toolbar">
      <span class="toolbar-meta mono">最后同步 {{ lastAt }}</span>
      <div class="toolbar-actions">
        <el-select v-model="pollMs" size="small" class="poll-select" teleported>
          <el-option :value="0" label="手动刷新" />
          <el-option :value="10000" label="每 10s" />
          <el-option :value="30000" label="每 30s" />
          <el-option :value="60000" label="每 60s" />
        </el-select>
        <el-button size="small" type="primary" plain @click="loadAll">刷新</el-button>
        <router-link class="link-console" to="/console">运维台 →</router-link>
      </div>
    </div>

    <el-tabs v-model="activeTab" class="dash-tabs">
      <el-tab-pane label="态势总览" name="overview">
        <div class="kpi-row">
          <div v-for="card in kpiCards" :key="card.key" class="kpi-card tech-corner">
            <span class="kpi-card-label">{{ card.label }}</span>
            <div class="kpi-card-mid">
              <span class="kpi-card-value" :class="{ 'kpi-card-value--gold': card.emphasis }">
                {{ card.value }}
              </span>
              <span v-if="card.suffix" class="kpi-card-suffix">{{ card.suffix }}</span>
            </div>
            <v-chart
              class="kpi-spark"
              :option="card.sparkOption"
              autoresize
            />
          </div>
        </div>

        <!-- 网关访问日志：按 stream_key / 域名区分；go-log-collector 推送 + 规则与 AI 洞察 -->
        <section v-if="trafficPayload?.hint" class="panel traffic-banner">
          <p class="traffic-zero">{{ trafficPayload.hint }}</p>
        </section>
        <section v-else-if="trafficBlock" class="panel traffic-panel traffic-panel--scifi">
          <div class="traffic-scifi-frame" aria-hidden="true" />
          <div class="panel-cap traffic-cap">
            <span class="cap-title">网关访问趋势</span>
            <span class="cap-hint mono">{{ trafficBlock.streamKey }} · 近 {{ trafficBlock.windowM }} 分钟</span>
          </div>
          <div class="traffic-grid">
            <div class="traffic-metric traffic-metric--glow">
              <span class="tm-label">请求</span>
              <span class="tm-val">{{ trafficBlock.total }}</span>
            </div>
            <div class="traffic-metric traffic-metric--glow">
              <span class="tm-label">QPS</span>
              <span class="tm-val">{{ trafficBlock.qps }}</span>
            </div>
            <div class="traffic-metric traffic-metric--glow">
              <span class="tm-label">错误率</span>
              <span class="tm-val" :class="{ 'tm-warn': trafficBlock.errRate > 0.05 }">
                {{ (trafficBlock.errRate * 100).toFixed(2) }}%
              </span>
            </div>
            <div class="traffic-metric traffic-metric--glow">
              <span class="tm-label">p99 延迟</span>
              <span class="tm-val">{{ trafficBlock.p99Ms ?? '—' }} ms</span>
            </div>
          </div>
          <div class="traffic-viz-row">
            <div class="traffic-viz-cell">
              <span class="traffic-viz-title">时间热力 · 请求密度</span>
              <v-chart class="traffic-chart-heat" :option="trafficHeatmapOption" autoresize />
            </div>
            <div class="traffic-viz-cell">
              <span class="traffic-viz-title">地域流量 · 国家/城市（GeoIP）</span>
              <v-chart class="traffic-chart-region" :option="trafficRegionOption" autoresize />
              <p v-if="trafficRegionGeoStub" class="traffic-geo-hint">
                当前气泡为<strong>无 GeoIP 时的示意分区</strong>（常见原因：日志里是 Docker/内网
                remote_addr、XFF 未带出公网 IP，或未挂载 GeoLite2）。请把真实客户端 IP 写入
                X-Forwarded-For（或 CDN 的 CF-Connecting-IP 等）并配置 .mmdb；历史行可执行
                <code class="mono">python manage.py backfill_logevent_geoip --only-empty-geo</code>。
              </p>
              <p v-else-if="trafficBlock.topClientIps.length" class="traffic-geo-hint traffic-geo-hint--subtle">
                <strong>Host Top</strong> 是浏览器请求的 <code class="mono">Host</code> 头；<strong>地域图</strong>按
                <strong>访客 IP（client_ip）</strong> 解析。下方「访客 IP Top」才是 GeoIP 依据，二者不必一致。
              </p>
            </div>
          </div>
          <div v-if="trafficBlock.hosts.length" class="traffic-hosts">
            <span class="cap-title cap-title--inline">Host Top</span>
            <ul>
              <li v-for="h in trafficBlock.hosts" :key="h.host">
                <span class="mono">{{ h.host }}</span>
                <span>{{ h.count }}</span>
              </li>
            </ul>
          </div>
          <div v-if="trafficBlock.topClientIps.length" class="traffic-hosts traffic-client-ip-top">
            <span class="cap-title cap-title--inline">访客 IP Top（GeoIP 依据）</span>
            <ul>
              <li v-for="(c, idx) in trafficBlock.topClientIps" :key="c.ip + String(idx)">
                <span class="mono">{{ c.ip }}</span>
                <span>{{ c.count }}</span>
              </li>
            </ul>
          </div>
          <div class="traffic-actions">
            <el-button
              size="small"
              type="primary"
              plain
              :loading="analyzeLoading"
              :disabled="!trafficPayload?.stream_key"
              @click="runTrafficAnalyze"
            >
              运行规则 + AI 分析
            </el-button>
            <span class="traffic-ai-hint">基于聚合指标与检测器结果调用 LLM（需配置 AI Key）</span>
          </div>
          <div v-if="trafficLatestInsight" class="traffic-insights traffic-insights--single">
            <span class="cap-title cap-title--inline">AI 洞察</span>
            <div :class="['ins-card', 'sev-' + trafficLatestInsight.severity]">
              <span class="ins-type mono">{{ trafficLatestInsight.insight_type }}</span>
              <span class="ins-title">{{ trafficLatestInsight.title }}</span>
              <p v-if="trafficLatestInsight.body" class="ins-body">{{ trafficLatestInsight.body }}</p>
              <span class="ins-at mono">{{ trafficLatestInsight.created_at }}</span>
            </div>
          </div>
        </section>

        <div class="mid-grid">
          <section class="panel panel-chart tech-grid">
            <div class="panel-cap">
              <span class="cap-title">24h 告警与自愈</span>
              <span class="cap-hint">新建事件 · 已执行工单</span>
            </div>
            <v-chart class="chart-main" :option="trendChartOption" autoresize />
          </section>

          <section class="panel panel-sidecol">
            <div class="panel-cap">
              <span class="cap-title">运行环境</span>
            </div>
            <div class="env-body">
              <ul class="env-list">
                <li v-for="row in envRows" :key="row.k">
                  <span class="env-k">{{ row.k }}</span>
                  <span class="env-v" :class="{ ok: row.ok, warn: row.warn }">{{ row.v }}</span>
                </li>
              </ul>
              <div class="globe-wrap">
                <TechGlobe class="env-globe" />
                <p class="globe-caption">云 · 边 · 中心协同（示意）</p>
              </div>
              <div class="sev-block">
                <span class="cap-title cap-title--inline">开放事件严重度</span>
                <v-chart class="chart-sev" :option="severityChartOption" autoresize />
              </div>
            </div>
          </section>
        </div>

        <div class="tables-grid">
          <section class="panel panel-table">
            <div class="panel-cap">
              <span class="cap-title">待审批工单</span>
              <span class="cap-count mono">{{ pendingCount }}</span>
            </div>
            <div class="table-body">
              <template v-if="(dash?.pending_tickets?.length ?? 0) > 0">
                <div
                  v-for="t in dash!.pending_tickets"
                  :key="t.ticket_id"
                  class="t-row"
                >
                  <span class="mono t-id">{{ t.ticket_id.slice(0, 8) }}</span>
                  <span class="t-main">{{ t.summary }}</span>
                  <span class="t-tag">{{ t.routing || 'human' }}</span>
                </div>
              </template>
              <p v-else class="table-zero">无待审项</p>
            </div>
          </section>

          <section class="panel panel-table">
            <div class="panel-cap">
              <span class="cap-title">近期自愈执行</span>
            </div>
            <div class="table-body">
              <template v-if="(dash?.recent_heals?.length ?? 0) > 0">
                <div
                  v-for="h in dash!.recent_heals"
                  :key="h.ticket_id"
                  class="t-row"
                >
                  <span class="mono t-id">{{ h.ticket_id.slice(0, 8) }}</span>
                  <span class="t-main">{{ h.summary }}</span>
                  <span class="mono t-time">{{ h.executed_at || '—' }}</span>
                </div>
              </template>
              <p v-else class="table-zero">尚无闭环记录</p>
            </div>
          </section>
        </div>
      </el-tab-pane>

      <el-tab-pane label="服务拓扑" name="topo">
        <section class="panel panel-topo-full tech-grid">
          <div class="panel-cap">
            <span class="cap-title">服务拓扑</span>
            <router-link class="cap-link" to="/console">在运维台诊断</router-link>
          </div>
          <div class="topo-body">
            <div v-if="layoutNodes.length" class="topo-chart">
              <svg class="topo-svg" :viewBox="`0 0 ${svgW} ${svgH}`" preserveAspectRatio="xMidYMid meet">
                <defs>
                  <filter id="dash-glow" x="-50%" y="-50%" width="200%" height="200%">
                    <feGaussianBlur stdDeviation="2" result="b" />
                    <feMerge>
                      <feMergeNode in="b" />
                      <feMergeNode in="SourceGraphic" />
                    </feMerge>
                  </filter>
                </defs>
                <line
                  v-for="(e, i) in dash?.topology?.edges ?? []"
                  :key="'e' + i"
                  :x1="nodePos(e.from)?.x ?? 0"
                  :y1="nodePos(e.from)?.y ?? 0"
                  :x2="nodePos(e.to)?.x ?? 0"
                  :y2="nodePos(e.to)?.y ?? 0"
                  class="t-edge"
                />
                <g
                  v-for="n in layoutNodes"
                  :key="n.id"
                  :transform="`translate(${n.x}, ${n.y})`"
                >
                  <circle
                    r="18"
                    :class="['t-node', n.healthy === false ? 't-node--bad' : '']"
                    :filter="n.healthy === false ? 'url(#dash-glow)' : undefined"
                  />
                  <text y="4" text-anchor="middle" class="t-cap">{{ truncate(n.label, 8) }}</text>
                </g>
              </svg>
            </div>
            <div v-else class="topo-empty">
              <TechGlobe class="topo-globe" />
              <p class="empty-copy">暂无拓扑快照</p>
              <p class="empty-hint">接入告警并运行诊断后生成 Service Map</p>
            </div>
          </div>
        </section>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart, BarChart, ScatterChart } from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
} from 'echarts/components'
import VChart from 'vue-echarts'
import { ElMessage } from 'element-plus'
import { aiOpsApi, type DashboardSummary, type TopoNode } from '@/api/ai_ops'
import {
  observabilityApi,
  type LogInsightRow,
  type TrafficSummaryPayload,
} from '@/api/observability'
import { systemApi, type SystemStats } from '@/api/system'
import TechGlobe from '@/components/TechGlobe.vue'

use([
  CanvasRenderer,
  LineChart,
  BarChart,
  ScatterChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
])

const CYAN = '#2dd4bf'
const CYAN_DIM = 'rgba(45, 212, 191, 0.25)'
const GOLD = '#fcd34d'
const MUTED = '#6b8aa0'
const DANGER = '#fb7185'

/** 示意经纬度（无 GeoIP 时按 Host 哈希大区后的气泡位置） */
const REGION_COORDS: Record<string, [number, number]> = {
  华北: [116.4, 40.0],
  华东: [121.5, 31.2],
  华南: [113.3, 23.1],
  西南: [104.1, 30.7],
  西北: [108.9, 34.3],
  海外: [125.0, 24.0],
}

/** 后端无 GeoIP 时按 Host 哈希的六大区名（与 aggregate / ClickHouse 一致） */
const TRAFFIC_STUB_REGION_NAMES = new Set([
  '华北',
  '华东',
  '华南',
  '西南',
  '西北',
  '海外',
])

/** 请求强度柱配色：深青 → 电青 → 淡紫峰，避免高对比黄块 */
function trafficHeatBarColors(v: number, max: number) {
  const t = max > 0 ? Math.min(1, v / max) : 0
  if (t < 0.1)
    return { top: '#2a4a5c', mid: '#152a38', bottom: '#0a141c' }
  if (t < 0.35)
    return { top: '#2a8a8a', mid: '#1a5f62', bottom: '#0e252c' }
  if (t < 0.65)
    return { top: '#5eead4', mid: '#2db8a8', bottom: '#0f3438' }
  if (t < 0.88)
    return { top: '#a7faf0', mid: '#2dd4bf', bottom: '#123840' }
  return { top: '#ddd6fe', mid: '#8b7fd8', bottom: '#1e1a36' }
}

const dash = ref<DashboardSummary | null>(null)
const sysStats = ref<SystemStats | null>(null)
const trafficPayload = ref<TrafficSummaryPayload | null>(null)
const trafficInsights = ref<LogInsightRow[]>([])
const analyzeLoading = ref(false)
const lastAt = ref('—')
const activeTab = ref('overview')
const pollMs = ref(30000)
let pollTimer: ReturnType<typeof setInterval> | null = null

const svgW = 720
const svgH = 280

function truncate(s: string, max: number) {
  if (!s) return ''
  return s.length <= max ? s : `${s.slice(0, max - 1)}…`
}

function cumsum(arr: number[]) {
  const o: number[] = []
  let s = 0
  for (const x of arr) {
    s += x
    o.push(s)
  }
  return o
}

function healthSparkSeries(incidentsNew: number[], healthNow: number): number[] {
  if (!incidentsNew.length) return Array(24).fill(healthNow)
  const out: number[] = []
  let acc = 0
  for (const n of incidentsNew) {
    acc += n
    out.push(Math.round(Math.max(38, Math.min(100, healthNow - acc * 2.2))))
  }
  out[out.length - 1] = Math.round(healthNow)
  return out
}

function sparkOption(values: number[], color: string, fill: string) {
  const n = values.length || 1
  const x = values.map((_, i) => i)
  return {
    animation: false,
    grid: { left: 2, right: 2, top: 4, bottom: 2 },
    xAxis: { type: 'category', show: false, data: x },
    yAxis: { type: 'value', show: false, min: 'dataMin', max: 'dataMax' },
    series: [
      {
        type: 'line',
        data: values,
        smooth: true,
        symbol: 'none',
        lineStyle: { width: 1.2, color },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: fill },
              { offset: 1, color: 'transparent' },
            ],
          },
        },
      },
    ],
  }
}

const layoutNodes = computed(() => {
  const nodes = dash.value?.topology?.nodes ?? []
  const n = nodes.length || 0
  if (!n) return [] as Array<TopoNode & { x: number; y: number }>
  const pad = 48
  const usable = svgW - pad * 2
  const step = n > 1 ? usable / (n - 1) : 0
  return nodes.map((node, i) => ({
    ...node,
    x: pad + (n === 1 ? usable / 2 : i * step),
    y: svgH / 2,
  }))
})

const posMap = computed(() => {
  const m = new Map<string, { x: number; y: number }>()
  for (const n of layoutNodes.value) m.set(n.id, { x: n.x, y: n.y })
  return m
})

function nodePos(id: string) {
  return posMap.value.get(id)
}

const trafficBlock = computed(() => {
  const p = trafficPayload.value
  if (!p?.stream_key || !p.summary) return null
  const s = p.summary as Record<string, unknown>
  const lat = (s.latency_ms || {}) as Record<string, unknown>
  return {
    streamKey: p.stream_key,
    windowM: Number(s.window_minutes) || 60,
    total: Number(s.total) || 0,
    qps: Number(Number(s.qps).toFixed(3)),
    errRate: Number(s.error_rate) || 0,
    p99Ms: lat.p99 != null ? Number(lat.p99) : null,
    hosts: Array.isArray(s.top_hosts) ? (s.top_hosts as { host: string; count: number }[]) : [],
    topClientIps: Array.isArray(s.top_client_ips)
      ? (s.top_client_ips as { ip: string; count: number }[])
      : [],
    timeHeatmap: s.time_heatmap as { labels: string[]; counts: number[] } | undefined,
    regionFlow: Array.isArray(s.region_flow)
      ? (s.region_flow as { name: string; value: number; lat?: number | null; lon?: number | null }[])
      : [],
  }
})

const trafficRegionGeoStub = computed(() => {
  const rows = trafficBlock.value?.regionFlow ?? []
  if (!rows.length) return false
  return rows.every((r) => TRAFFIC_STUB_REGION_NAMES.has(r.name))
})

const trafficLatestInsight = computed(() => trafficInsights.value[0] ?? null)

const trafficHeatmapOption = computed(() => {
  const th = trafficBlock.value?.timeHeatmap
  const labels = th?.labels?.length ? th.labels : []
  const counts = th?.counts?.length ? th.counts : []
  if (!labels.length) {
    return {
      backgroundColor: 'transparent',
      textStyle: { color: MUTED, fontSize: 10 },
      grid: { left: 44, right: 10, top: 12, bottom: 40 },
      xAxis: { type: 'category', data: [], axisLine: { lineStyle: { color: CYAN_DIM } } },
      yAxis: { type: 'value', show: false },
      series: [{ type: 'bar', data: [] }],
    }
  }
  const maxC = Math.max(1, ...counts)
  const barData = labels.map((lab, i) => {
    const v = counts[i] ?? 0
    const c = trafficHeatBarColors(v, maxC)
    const hot = maxC > 0 && v >= maxC * 0.72
    return {
      value: v,
      name: lab,
      itemStyle: {
        color: {
          type: 'linear',
          x: 0,
          y: 0,
          x2: 0,
          y2: 1,
          colorStops: [
            { offset: 0, color: c.top },
            { offset: 0.5, color: c.mid },
            { offset: 1, color: c.bottom },
          ],
        },
        borderRadius: [4, 4, 1, 1],
        shadowBlur: hot ? 16 : 6,
        shadowColor: hot ? 'rgba(167, 250, 240, 0.35)' : 'rgba(45, 212, 191, 0.2)',
      },
    }
  })
  return {
    backgroundColor: 'transparent',
    animationDuration: 480,
    animationEasing: 'cubicOut',
    textStyle: { color: MUTED, fontSize: 10 },
    tooltip: {
      trigger: 'axis',
      axisPointer: {
        type: 'shadow',
        shadowStyle: { color: 'rgba(45, 212, 191, 0.12)' },
      },
      backgroundColor: 'rgba(4, 12, 28, 0.94)',
      borderColor: CYAN_DIM,
      borderWidth: 1,
      textStyle: { color: '#e8f4ff', fontSize: 12 },
      formatter: (p: unknown) => {
        const arr = Array.isArray(p) ? p : [p]
        const x = arr[0] as { name?: string; value?: number }
        return `${x?.name ?? ''}<br/><span style="color:#5eead4">请求</span> ${x?.value ?? 0}`
      },
    },
    grid: { left: 44, right: 10, top: 14, bottom: 44 },
    xAxis: {
      type: 'category',
      data: labels,
      axisLine: { lineStyle: { color: CYAN_DIM } },
      axisTick: { show: false },
      axisLabel: { color: MUTED, fontSize: 9, rotate: 42, margin: 10 },
    },
    yAxis: {
      type: 'value',
      min: 0,
      splitLine: { lineStyle: { color: 'rgba(45, 212, 191, 0.06)' } },
      axisLine: { show: false },
      axisLabel: { color: MUTED, fontSize: 9 },
    },
    series: [
      {
        type: 'bar',
        name: '请求',
        barMaxWidth: 9,
        barGap: '52%',
        showBackground: true,
        backgroundStyle: {
          color: 'rgba(6, 24, 44, 0.55)',
          borderRadius: [4, 4, 0, 0],
        },
        data: barData,
      },
    ],
  }
})

const trafficRegionOption = computed(() => {
  const rows = trafficBlock.value?.regionFlow ?? []
  const data = rows.map((r) => {
    let lon = r.lon
    let lat = r.lat
    if (lat == null || lon == null) {
      const c = REGION_COORDS[r.name]
      if (c) {
        lon = c[0]
        lat = c[1]
      } else {
        lon = 105
        lat = 35
      }
    }
    return {
      name: r.name,
      value: [lon, lat, r.value] as [number, number, number],
    }
  })
  if (!data.length) {
    return {
      backgroundColor: 'transparent',
      grid: { left: 44, right: 16, top: 16, bottom: 28 },
      xAxis: { type: 'value', min: 100, max: 132, show: true },
      yAxis: { type: 'value', min: 18, max: 42, show: true },
      series: [],
    }
  }

  let minX = 180
  let maxX = -180
  let minY = 90
  let maxY = -90
  for (const d of data) {
    const x = d.value[0]
    const y = d.value[1]
    if (typeof x === 'number' && typeof y === 'number' && Number.isFinite(x) && Number.isFinite(y)) {
      minX = Math.min(minX, x)
      maxX = Math.max(maxX, x)
      minY = Math.min(minY, y)
      maxY = Math.max(maxY, y)
    }
  }
  if (minX > maxX) {
    minX = 100
    maxX = 132
    minY = 18
    maxY = 42
  }
  const spanX = Math.max(maxX - minX, 4)
  const spanY = Math.max(maxY - minY, 4)
  const padX = Math.max(2.5, spanX * 0.14)
  const padY = Math.max(2.5, spanY * 0.14)
  const xMin = Math.max(70, minX - padX)
  const xMax = Math.min(150, maxX + padX)
  const yMin = Math.max(0, minY - padY)
  const yMax = Math.min(55, maxY + padY)

  return {
    backgroundColor: 'transparent',
    animationDuration: 400,
    textStyle: { color: MUTED, fontSize: 10 },
    tooltip: {
      backgroundColor: 'rgba(4, 12, 28, 0.94)',
      borderColor: CYAN_DIM,
      borderWidth: 1,
      textStyle: { color: '#e8f4ff', fontSize: 12 },
      formatter: (p: { data?: { name?: string; value?: number[] } }) => {
        const v = p.data?.value
        const n = p.data?.name
        return `${n ?? ''}<br/><span style="color:#5eead4">请求</span> ${v?.[2] ?? 0}`
      },
    },
    grid: { left: 44, right: 16, top: 18, bottom: 30 },
    xAxis: {
      min: xMin,
      max: xMax,
      scale: true,
      name: '经度示意',
      nameTextStyle: { color: MUTED, fontSize: 9 },
      axisLine: { lineStyle: { color: CYAN_DIM } },
      splitLine: { lineStyle: { color: 'rgba(45,212,191,0.04)' } },
      axisLabel: { color: MUTED, fontSize: 9 },
    },
    yAxis: {
      min: yMin,
      max: yMax,
      scale: true,
      name: '纬度示意',
      nameTextStyle: { color: MUTED, fontSize: 9 },
      axisLine: { lineStyle: { color: CYAN_DIM } },
      splitLine: { lineStyle: { color: 'rgba(45,212,191,0.04)' } },
      axisLabel: { color: MUTED, fontSize: 9 },
    },
    series: [
      {
        type: 'scatter',
        data,
        symbolSize: (raw: unknown) => {
          const arr = raw as number[]
          const n = arr?.[2] ?? 0
          return Math.max(14, Math.min(44, 10 + Math.sqrt(n) * 1.85))
        },
        itemStyle: {
          color: {
            type: 'radial',
            x: 0.4,
            y: 0.4,
            r: 0.92,
            colorStops: [
              { offset: 0, color: '#e8fffb' },
              { offset: 0.45, color: '#5eead4' },
              { offset: 1, color: 'rgba(20, 60, 72, 0.55)' },
            ],
          },
          borderColor: 'rgba(94, 234, 212, 0.35)',
          borderWidth: 1,
          shadowBlur: 10,
          shadowColor: 'rgba(45,212,191,0.28)',
        },
        label: {
          show: true,
          formatter: (p: { data?: { name?: string } }) => p.data?.name ?? '',
          color: '#cfeef0',
          fontSize: 9,
          fontWeight: 600,
          position: 'top',
          distance: 10,
          textBorderColor: 'rgba(2, 12, 28, 0.9)',
          textBorderWidth: 2,
        },
        labelLayout: { hideOverlap: true },
        emphasis: {
          scale: 1.12,
          itemStyle: { shadowBlur: 14, shadowColor: 'rgba(45,212,191,0.4)' },
        },
      },
    ],
  }
})

const pendingCount = computed(() => {
  const d = dash.value
  if (d?.pending_approval_count != null) return d.pending_approval_count
  return d?.pending_tickets?.length ?? 0
})

const trendChartOption = computed(() => {
  const t = dash.value?.trends
  if (!t?.labels?.length) {
    return {
      backgroundColor: 'transparent',
      grid: { left: 48, right: 24, top: 28, bottom: 40 },
      xAxis: { type: 'category', data: [] },
      yAxis: { type: 'value' },
      series: [],
    }
  }
  return {
    backgroundColor: 'transparent',
    textStyle: { color: MUTED, fontSize: 11 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(6, 22, 48, 0.92)',
      borderColor: CYAN_DIM,
      textStyle: { color: '#e8f4ff', fontSize: 12 },
    },
    legend: {
      textStyle: { color: MUTED, fontSize: 11 },
      top: 0,
      data: ['新建事件', '自愈工单'],
    },
    grid: { left: 48, right: 24, top: 36, bottom: 36 },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: t.labels,
      axisLine: { lineStyle: { color: CYAN_DIM } },
      axisLabel: { color: MUTED, fontSize: 10, rotate: 32 },
    },
    yAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: 'rgba(45, 212, 191, 0.08)' } },
      axisLabel: { color: MUTED, fontSize: 10 },
    },
    series: [
      {
        name: '新建事件',
        type: 'line',
        smooth: true,
        symbol: 'none',
        lineStyle: { width: 1.5, color: CYAN },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(45, 212, 191, 0.22)' },
              { offset: 1, color: 'transparent' },
            ],
          },
        },
        data: t.incidents_new,
      },
      {
        name: '自愈工单',
        type: 'line',
        smooth: true,
        symbol: 'none',
        lineStyle: { width: 1.5, color: GOLD },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(252, 211, 77, 0.15)' },
              { offset: 1, color: 'transparent' },
            ],
          },
        },
        data: t.tickets_executed,
      },
    ],
  }
})

const severityChartOption = computed(() => {
  const s = dash.value?.severity_open
  const c = s?.critical ?? 0
  const w = s?.warning ?? 0
  const i = s?.info ?? 0
  return {
    backgroundColor: 'transparent',
    textStyle: { color: MUTED, fontSize: 11 },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      backgroundColor: 'rgba(6, 22, 48, 0.92)',
      borderColor: CYAN_DIM,
    },
    grid: { left: 72, right: 16, top: 8, bottom: 8 },
    xAxis: { type: 'value', show: false },
    yAxis: {
      type: 'category',
      data: ['Info', 'Warning', 'Critical'],
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: MUTED, fontSize: 11 },
    },
    series: [
      {
        type: 'bar',
        barWidth: 10,
        data: [
          { value: i, itemStyle: { color: CYAN, borderRadius: [0, 4, 4, 0] } },
          { value: w, itemStyle: { color: GOLD, borderRadius: [0, 4, 4, 0] } },
          { value: c, itemStyle: { color: DANGER, borderRadius: [0, 4, 4, 0] } },
        ],
      },
    ],
  }
})

const kpiCards = computed(() => {
  const d = dash.value
  const inc = d?.trends?.incidents_new ?? []
  const hel = d?.trends?.tickets_executed ?? []
  const h = d?.health_score ?? 100
  const sumInc = inc.reduce((a, b) => a + b, 0)
  const sumHel = hel.reduce((a, b) => a + b, 0)
  const pend = pendingCount.value
  const ts = d?.topology_stats
  const nodes = ts?.node_count ?? d?.topology?.nodes?.length ?? 0
  const healthy = ts?.healthy_nodes ?? 0

  const healthSpark = healthSparkSeries(inc, h)
  const incCum = cumsum(inc)
  const helCum = cumsum(hel)
  const pendLine = inc.length ? Array(inc.length).fill(pend) : [pend]

  return [
    {
      key: 'health',
      label: '健康分',
      value: d?.health_score != null ? String(d.health_score) : '—',
      suffix: '/ 100',
      emphasis: true,
      sparkOption: sparkOption(healthSpark.length ? healthSpark : [h], GOLD, 'rgba(252, 211, 77, 0.2)'),
    },
    {
      key: 'open',
      label: '开放事件',
      value: String(d?.open_incidents ?? 0),
      suffix: '',
      emphasis: false,
      sparkOption: sparkOption(incCum.length ? incCum : [0], CYAN, 'rgba(45, 212, 191, 0.15)'),
    },
    {
      key: 'pend',
      label: '待审工单',
      value: String(pend),
      suffix: '',
      emphasis: false,
      sparkOption: sparkOption(pendLine, GOLD, 'rgba(252, 211, 77, 0.12)'),
    },
    {
      key: '24h',
      label: '24h 新告警',
      value: String(sumInc),
      suffix: '起',
      emphasis: false,
      sparkOption: sparkOption(inc.length ? inc : [0], CYAN, 'rgba(45, 212, 191, 0.12)'),
    },
    {
      key: 'heal',
      label: '24h 自愈',
      value: String(sumHel),
      suffix: '单',
      emphasis: false,
      sparkOption: sparkOption(hel.length ? hel : [0], GOLD, 'rgba(252, 211, 77, 0.12)'),
    },
    {
      key: 'topo',
      label: '拓扑节点',
      value: String(nodes),
      suffix: healthy && nodes ? `健 ${healthy}` : '',
      emphasis: false,
      sparkOption: sparkOption(
        (inc.length ? inc : Array(12).fill(0)).map(() => nodes),
        CYAN,
        'rgba(45, 212, 191, 0.1)',
      ),
    },
  ]
})

const envRows = computed(() => {
  const d = dash.value?.deployment
  const modeLabel: Record<string, string> = {
    kubernetes: 'Kubernetes',
    hybrid: '混合',
    physical: '物理 / 边缘',
    unspecified: '未声明',
  }
  const ai = dash.value?.ai_status
  return [
    {
      k: '部署模式',
      v: d ? modeLabel[d.mode] || d.mode : '—',
      ok: Boolean(d && d.mode !== 'unspecified'),
      warn: !d || d.mode === 'unspecified',
    },
    {
      k: '控制面 Pod',
      v: d?.center_in_kubernetes_pod ? '在 Pod 内' : '否 / 未知',
      ok: Boolean(d?.center_in_kubernetes_pod),
      warn: false,
    },
    {
      k: '集群数据',
      v: d?.cluster_data_via_api ? '经 API / 指标栈' : '未标记',
      ok: Boolean(d?.cluster_data_via_api),
      warn: false,
    },
    {
      k: '边缘心跳',
      v: d?.edge_heartbeat_expected ? '预期边缘探针' : '不强制',
      ok: true,
      warn: false,
    },
    {
      k: 'AI 巡检',
      v: ai === 'analyzing' ? '分析中' : ai === 'degraded' ? '有风险' : '静默',
      ok: ai === 'idle',
      warn: ai === 'degraded',
    },
    {
      k: '经验库',
      v: `${dash.value?.knowledge_entries ?? 0} 条`,
      ok: (dash.value?.knowledge_entries ?? 0) > 0,
      warn: false,
    },
  ]
})

function formatNow() {
  const x = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return `${x.getFullYear()}-${p(x.getMonth() + 1)}-${p(x.getDate())} ${p(x.getHours())}:${p(x.getMinutes())}:${p(x.getSeconds())}`
}

async function loadTraffic() {
  try {
    trafficPayload.value = await observabilityApi.getTrafficSummary({ minutes: 60 })
    const sk = trafficPayload.value.stream_key
    if (sk) {
      const ins = await observabilityApi.listInsights({ stream_key: sk, limit: 1 })
      trafficInsights.value = ins.insights
    } else {
      trafficInsights.value = []
    }
  } catch {
    trafficPayload.value = null
    trafficInsights.value = []
  }
}

async function runTrafficAnalyze() {
  const sk = trafficPayload.value?.stream_key
  if (!sk) return
  analyzeLoading.value = true
  try {
    await observabilityApi.requestAnalyze(sk, 60)
    ElMessage.success('已触发分析，请稍后点击刷新查看洞察')
    await loadTraffic()
  } catch {
    ElMessage.error('分析请求失败')
  } finally {
    analyzeLoading.value = false
  }
}

async function loadAll() {
  try {
    const [d, s] = await Promise.all([aiOpsApi.getDashboard(), systemApi.getStats()])
    dash.value = d
    sysStats.value = s
    await loadTraffic()
    lastAt.value = formatNow()
  } catch {
    try {
      dash.value = await aiOpsApi.getDashboard()
    } catch {
      dash.value = null
    }
    sysStats.value = null
    await loadTraffic()
    lastAt.value = formatNow()
  }
}

function clearPoll() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

watch(pollMs, (ms) => {
  clearPoll()
  if (ms > 0) {
    pollTimer = setInterval(() => void loadAll(), ms)
  }
})

onMounted(() => {
  void loadAll()
  if (pollMs.value > 0) {
    pollTimer = setInterval(() => void loadAll(), pollMs.value)
  }
})

onUnmounted(() => clearPoll())
</script>

<style scoped>
.ops-dash {
  animation: in 0.45s cubic-bezier(0.22, 1, 0.36, 1) both;
}

@keyframes in {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.bc {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
  font-size: 12px;
  color: var(--tech-text-muted);
}

.bc-sep {
  opacity: 0.45;
}

.bc-here {
  color: var(--tech-text-secondary);
}

.page-head {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
  margin-bottom: 14px;
}

.page-title {
  margin: 0;
  font-size: 1.45rem;
  font-weight: 600;
  letter-spacing: 0.03em;
  color: var(--tech-text);
  text-shadow: 0 0 24px rgba(45, 212, 191, 0.12);
}

.page-sub {
  margin: 8px 0 0;
  max-width: 640px;
  font-size: 13px;
  line-height: 1.55;
  color: var(--tech-text-muted);
}

.resource-strip {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 220px;
  padding: 12px 14px;
  border-radius: 10px;
  border: 1px solid var(--tech-cyan-border);
  background: rgba(6, 24, 48, 0.45);
}

.res-item {
  display: grid;
  grid-template-columns: 36px 1fr auto;
  align-items: center;
  gap: 10px;
}

.res-label {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--tech-text-muted);
}

.res-bar-wrap {
  height: 6px;
  border-radius: 3px;
  background: rgba(45, 212, 191, 0.08);
  overflow: hidden;
}

.res-bar-fill {
  height: 100%;
  border-radius: 3px;
  background: linear-gradient(90deg, var(--tech-cyan), rgba(45, 212, 191, 0.45));
  box-shadow: 0 0 10px rgba(45, 212, 191, 0.35);
  transition: width 0.35s ease;
}

.res-bar-fill--mem {
  background: linear-gradient(90deg, #38bdf8, rgba(56, 189, 248, 0.45));
  box-shadow: 0 0 10px rgba(56, 189, 248, 0.25);
}

.res-val {
  font-size: 11px;
  color: var(--tech-text-secondary);
}

.notice-banner {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 14px;
  margin-bottom: 14px;
  border-radius: 8px;
  border: 1px solid rgba(56, 189, 248, 0.28);
  background: rgba(14, 165, 233, 0.06);
  font-size: 12px;
  line-height: 1.5;
  color: var(--tech-text-secondary);
}

.notice-dot {
  width: 6px;
  height: 6px;
  margin-top: 5px;
  border-radius: 50%;
  flex-shrink: 0;
  background: var(--tech-cyan);
  box-shadow: 0 0 8px rgba(45, 212, 191, 0.5);
}

.toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 18px;
}

.toolbar-meta {
  font-size: 11px;
  color: var(--tech-text-muted);
}

.toolbar-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}

.poll-select {
  width: 120px;
}

.link-console {
  font-size: 12px;
  font-weight: 500;
  color: var(--tech-cyan);
  text-decoration: none;
}

.link-console:hover {
  text-decoration: underline;
}

.dash-tabs :deep(.el-tabs__header) {
  margin-bottom: 16px;
}

.dash-tabs :deep(.el-tabs__nav-wrap::after) {
  background-color: rgba(45, 212, 191, 0.15);
}

.dash-tabs :deep(.el-tabs__item) {
  color: var(--tech-text-muted);
  font-weight: 500;
}

.dash-tabs :deep(.el-tabs__item.is-active) {
  color: var(--tech-cyan);
}

.dash-tabs :deep(.el-tabs__active-bar) {
  background-color: var(--tech-cyan);
  box-shadow: 0 0 12px rgba(45, 212, 191, 0.45);
}

.kpi-row {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 12px;
  margin-bottom: 16px;
}

@media (max-width: 1200px) {
  .kpi-row {
    grid-template-columns: repeat(3, 1fr);
  }
}

@media (max-width: 560px) {
  .kpi-row {
    grid-template-columns: 1fr;
  }
}

.kpi-card {
  position: relative;
  padding: 12px 14px 6px;
  border-radius: 10px;
  border: 1px solid var(--tech-cyan-border);
  background: linear-gradient(165deg, rgba(10, 32, 56, 0.42) 0%, rgba(4, 14, 32, 0.72) 100%);
  box-shadow: 0 0 14px var(--tech-cyan-glow), inset 0 1px 0 rgba(255, 255, 255, 0.04);
}

.tech-corner::before {
  content: '';
  position: absolute;
  top: -1px;
  left: -1px;
  width: 9px;
  height: 9px;
  border-top: 2px solid var(--tech-cyan);
  border-left: 2px solid var(--tech-cyan);
  opacity: 0.55;
  pointer-events: none;
}

.kpi-card-label {
  display: block;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--tech-text-muted);
}

.kpi-card-mid {
  display: flex;
  align-items: baseline;
  gap: 6px;
  margin-top: 4px;
}

.kpi-card-value {
  font-size: 1.35rem;
  font-weight: 600;
  font-feature-settings: 'tnum' 1;
  color: var(--tech-text);
}

.kpi-card-value--gold {
  color: var(--tech-gold);
  text-shadow: 0 0 18px var(--tech-gold-dim);
}

.kpi-card-suffix {
  font-size: 11px;
  color: var(--tech-text-muted);
}

.kpi-spark {
  height: 44px;
  width: 100%;
  margin-top: 4px;
}

.traffic-banner {
  margin-bottom: 16px;
  padding: 14px 16px;
}

.traffic-zero {
  margin: 0;
  font-size: 12px;
  line-height: 1.5;
  color: var(--tech-text-muted);
}

.traffic-panel {
  margin-bottom: 16px;
  position: relative;
  overflow: hidden;
}

.traffic-panel--scifi {
  border-color: rgba(45, 212, 191, 0.45);
  box-shadow:
    0 0 24px rgba(45, 212, 191, 0.18),
    0 0 60px rgba(45, 212, 191, 0.06),
    inset 0 0 40px rgba(45, 212, 191, 0.04);
}

.traffic-scifi-frame {
  pointer-events: none;
  position: absolute;
  inset: 0;
  border: 1px solid transparent;
  background:
    linear-gradient(90deg, rgba(45, 212, 191, 0.12) 1px, transparent 1px) 0 0 / 24px 24px,
    linear-gradient(rgba(45, 212, 191, 0.08) 1px, transparent 1px) 0 0 / 24px 24px;
  opacity: 0.35;
  mask-image: linear-gradient(180deg, rgba(0, 0, 0, 0.65), rgba(0, 0, 0, 0.2));
}

.traffic-cap {
  position: relative;
  z-index: 1;
}

.traffic-metric--glow {
  box-shadow: 0 0 12px rgba(45, 212, 191, 0.08);
}

.traffic-viz-row {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  padding: 8px 16px 4px;
}

@media (max-width: 900px) {
  .traffic-viz-row {
    grid-template-columns: 1fr;
  }
}

.traffic-viz-cell {
  border: 1px solid rgba(45, 212, 191, 0.22);
  border-radius: 10px;
  background: linear-gradient(165deg, rgba(4, 28, 52, 0.55) 0%, rgba(2, 10, 26, 0.82) 100%);
  padding: 8px 8px 4px;
  box-shadow:
    inset 0 0 24px rgba(45, 212, 191, 0.05),
    0 0 1px rgba(94, 234, 212, 0.15);
}

.traffic-viz-title {
  display: block;
  font-size: 9px;
  font-weight: 600;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--tech-cyan);
  margin-bottom: 4px;
  padding-left: 4px;
}

.traffic-chart-heat {
  height: 200px;
  width: 100%;
  filter: drop-shadow(0 0 10px rgba(45, 212, 191, 0.06));
}

.traffic-chart-region {
  height: 220px;
  width: 100%;
  filter: drop-shadow(0 0 12px rgba(45, 212, 191, 0.08));
}

.traffic-geo-hint {
  margin: 6px 2px 0;
  padding: 8px 10px;
  font-size: 11px;
  line-height: 1.45;
  color: var(--tech-text-muted);
  background: rgba(4, 20, 44, 0.45);
  border-radius: 6px;
  border: 1px solid rgba(45, 212, 191, 0.12);
}

.traffic-geo-hint .mono {
  font-size: 10px;
  word-break: break-all;
}

.traffic-geo-hint--subtle {
  background: rgba(4, 20, 44, 0.28);
  border-color: rgba(45, 212, 191, 0.08);
}

.traffic-client-ip-top {
  margin-top: 4px;
}

.traffic-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  padding: 12px 16px 8px;
}

@media (max-width: 720px) {
  .traffic-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

.traffic-metric {
  padding: 10px 12px;
  border-radius: 8px;
  border: 1px solid rgba(45, 212, 191, 0.2);
  background: rgba(4, 20, 44, 0.35);
}

.tm-label {
  display: block;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--tech-text-muted);
}

.tm-val {
  font-size: 1.2rem;
  font-weight: 600;
  font-feature-settings: 'tnum' 1;
  color: var(--tech-text);
}

.tm-warn {
  color: var(--tech-gold);
}

.traffic-hosts {
  padding: 0 16px 8px;
}

.traffic-hosts ul {
  list-style: none;
  margin: 0;
  padding: 0;
}

.traffic-hosts li {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  padding: 6px 0;
  border-bottom: 1px solid rgba(45, 212, 191, 0.08);
  color: var(--tech-text-secondary);
}

.traffic-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  padding: 8px 16px 12px;
  border-top: 1px solid rgba(45, 212, 191, 0.1);
}

.traffic-ai-hint {
  font-size: 11px;
  color: var(--tech-text-muted);
}

.traffic-insights {
  position: relative;
  z-index: 1;
  padding: 0 16px 14px;
}

.traffic-insights--single .ins-card {
  margin-top: 8px;
  padding: 12px 14px;
  border-radius: 8px;
  border: 1px solid rgba(45, 212, 191, 0.28);
  background: linear-gradient(135deg, rgba(8, 28, 52, 0.85), rgba(4, 14, 32, 0.95));
  box-shadow: 0 0 18px rgba(45, 212, 191, 0.1);
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.traffic-insights .ins-type {
  font-size: 10px;
  color: var(--tech-text-muted);
}

.traffic-insights .ins-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--tech-text-secondary);
}

.traffic-insights .ins-body {
  margin: 0;
  font-size: 12px;
  line-height: 1.55;
  color: var(--tech-text-muted);
}

.traffic-insights .ins-at {
  font-size: 10px;
  color: var(--tech-text-muted);
  opacity: 0.85;
}

.traffic-insights .sev-critical .ins-title {
  color: var(--tech-danger);
}

.traffic-insights .sev-warning .ins-title {
  color: var(--tech-gold);
}

.traffic-insights .sev-critical.ins-card {
  border-color: rgba(251, 113, 133, 0.35);
  box-shadow: 0 0 20px rgba(251, 113, 133, 0.12);
}

.traffic-insights .sev-warning.ins-card {
  border-color: rgba(252, 211, 77, 0.35);
  box-shadow: 0 0 18px rgba(252, 211, 77, 0.1);
}

.mid-grid {
  display: grid;
  grid-template-columns: 1fr 320px;
  gap: 14px;
  margin-bottom: 16px;
}

@media (max-width: 1024px) {
  .mid-grid {
    grid-template-columns: 1fr;
  }
}

.panel {
  border-radius: 10px;
  border: 1px solid var(--tech-cyan-border);
  background: linear-gradient(165deg, rgba(10, 32, 56, 0.45) 0%, rgba(4, 14, 32, 0.72) 100%);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  box-shadow: 0 0 18px var(--tech-cyan-glow), inset 0 1px 0 rgba(255, 255, 255, 0.04);
}

.panel-cap {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--aiops-border);
}

.cap-title {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--tech-cyan);
}

.cap-title--inline {
  display: block;
  margin-bottom: 8px;
  border: none;
  padding: 0;
}

.cap-hint {
  font-size: 11px;
  color: var(--tech-text-muted);
}

.cap-count {
  font-size: 12px;
  color: var(--tech-gold);
}

.cap-link {
  font-size: 12px;
  font-weight: 500;
}

.chart-main {
  height: 300px;
  width: 100%;
  padding: 4px 8px 12px;
}

.env-body {
  padding: 12px 16px 16px;
}

.env-list {
  list-style: none;
  margin: 0 0 16px;
  padding: 0;
}

.env-list li {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 0;
  border-bottom: 1px solid rgba(45, 212, 191, 0.08);
  font-size: 12px;
}

.env-list li:last-child {
  border-bottom: none;
}

.env-k {
  color: var(--tech-text-muted);
}

.env-v {
  color: var(--tech-text-secondary);
  text-align: right;
}

.env-v.ok {
  color: var(--tech-cyan);
}

.env-v.warn {
  color: var(--tech-danger);
}

.globe-wrap {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 8px 0 12px;
  border-top: 1px solid rgba(45, 212, 191, 0.1);
  border-bottom: 1px solid rgba(45, 212, 191, 0.1);
}

.env-globe {
  width: 160px;
  height: 160px;
  opacity: 0.9;
}

.globe-caption {
  margin: 6px 0 0;
  font-size: 10px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--tech-text-muted);
}

.chart-sev {
  height: 120px;
  width: 100%;
}

.tables-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}

@media (max-width: 900px) {
  .tables-grid {
    grid-template-columns: 1fr;
  }
}

.table-body {
  padding: 4px 0 8px;
  min-height: 100px;
}

.t-row {
  display: grid;
  grid-template-columns: 72px 1fr auto;
  gap: 12px;
  align-items: center;
  padding: 10px 16px;
  border-bottom: 1px solid rgba(45, 212, 191, 0.08);
  font-size: 13px;
}

.t-row:last-child {
  border-bottom: none;
}

.t-row:hover {
  background: rgba(45, 212, 191, 0.04);
}

.t-id {
  font-size: 11px;
  color: var(--tech-text-muted);
}

.t-main {
  color: var(--tech-text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.t-tag {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--tech-gold);
  padding: 2px 8px;
  border-radius: 4px;
  border: 1px solid rgba(252, 211, 77, 0.35);
  background: var(--tech-gold-dim);
}

.t-time {
  font-size: 10px;
  color: var(--tech-text-muted);
}

.table-zero {
  margin: 0;
  padding: 28px 16px;
  text-align: center;
  font-size: 12px;
  color: var(--tech-text-muted);
}

.panel-topo-full {
  min-height: 360px;
}

.topo-body {
  min-height: 300px;
  padding: 12px;
}

.topo-chart {
  border-radius: 8px;
  border: 1px solid var(--aiops-border);
  overflow: hidden;
}

.topo-svg {
  display: block;
  width: 100%;
  height: 300px;
}

.t-edge {
  stroke: rgba(45, 212, 191, 0.35);
  stroke-width: 1;
}

.t-node {
  fill: rgba(8, 24, 48, 0.9);
  stroke: var(--tech-cyan);
  stroke-width: 1;
}

.t-node--bad {
  stroke: var(--tech-danger);
  fill: rgba(251, 113, 133, 0.12);
}

.t-cap {
  fill: var(--tech-text-muted);
  font-size: 9px;
  font-family: var(--aiops-font-mono);
}

.topo-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px 16px;
  min-height: 280px;
}

.topo-globe {
  margin-bottom: 12px;
}

.empty-copy {
  margin: 0;
  font-size: 13px;
  color: var(--tech-text-secondary);
}

.empty-hint {
  margin: 6px 0 0;
  font-size: 11px;
  color: var(--tech-text-muted);
}

.mono {
  font-family: var(--aiops-font-mono);
}
</style>
