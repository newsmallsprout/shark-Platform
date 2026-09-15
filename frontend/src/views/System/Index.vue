<template>
  <div class="inspection-container">
    <div class="page-header">
      <div class="header-info">
        <h2 class="page-title">System Inspection</h2>
        <p class="page-subtitle">集群检查清单 + PVC/业务服务 + 资源告警；异常可通过「系统工单」交由人工处置。</p>
      </div>
      <div class="header-actions">
        <el-button @click="router.push('/system/tickets')" v-if="canViewInspection">系统工单</el-button>
        <el-button @click="showLogs" :icon="Document">Inspection Logs</el-button>
        <el-button @click="configVisible = true" :icon="Setting" v-if="canManage">巡检配置</el-button>
        <el-button type="primary" size="large" @click="handleRun" :loading="loading" class="action-btn shadow-btn" v-if="canManage">
          <el-icon><Search /></el-icon> Run New Inspection
        </el-button>
      </div>
    </div>
    
    <el-card shadow="never" class="table-card">
      <el-table :data="tableData" v-loading="loading" style="width: 100%">
        <el-table-column prop="report_id" label="Report Timestamp" width="220">
          <template #default="{ row }">
            <div class="report-id-cell">
              <el-icon class="report-icon"><Calendar /></el-icon>
              <span>{{ formatIdToDate(row.report_id) }}</span>
            </div>
          </template>
        </el-table-column>
        
        <el-table-column label="Health Status" width="160">
          <template #default="{ row }">
            <div class="score-wrapper">
              <template v-if="row.score != null">
                <el-progress 
                  type="circle" 
                  :percentage="row.score" 
                  :width="40" 
                  :stroke-width="4"
                  :status="getProgressStatus(row.score)"
                />
                <el-tag :type="getScoreType(row.score)" size="small" effect="plain" class="score-tag">
                  {{ row.score }}
                </el-tag>
              </template>
              <template v-else>
                <el-icon class="status-icon-placeholder"><CircleCheck /></el-icon>
                <el-tag type="info" size="small" effect="plain" class="score-tag">未覆盖</el-tag>
              </template>
            </div>
          </template>
        </el-table-column>

        <el-table-column prop="summary" label="Analysis Summary">
          <template #default="{ row }">
            <span class="summary-text">{{ row.summary || 'Awaiting full report analysis...' }}</span>
          </template>
        </el-table-column>

        <el-table-column label="Actions" width="140" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" plain size="small" @click="viewReport(row)">
              View Details
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- Report Detail Dialog -->
    <el-dialog 
      v-model="dialogVisible" 
      title="Inspection Report Analysis" 
      width="1040px"
      class="report-dialog"
    >
      <div v-if="currentReport" class="report-content">
        <div class="report-meta">
          <div class="meta-item">
            <span class="label">TIMESTAMP</span>
            <span class="value">{{ formatIdToDate(currentReport.report_id) }}</span>
          </div>
          <div class="meta-item">
            <span class="label">HEALTH SCORE</span>
            <div class="score-display">
              <span :class="['score-value', getScoreType(currentReport.score)]">{{ currentReport.score == null ? '—' : currentReport.score }}</span>
              <span class="score-total">/100</span>
            </div>
          </div>
          <div class="meta-item">
            <span class="label">SERVERS</span>
            <span class="value">{{ currentReport.fleet_summary?.server_count ?? '-' }}</span>
          </div>
          <div class="meta-item">
            <span class="label">FIRING ALERTS</span>
            <span class="value">{{ currentReport.alerts_summary?.firing_total ?? '-' }}</span>
          </div>
          <div class="meta-item">
            <span class="label">VERDICT</span>
            <span class="value">{{ currentReport.verdict || '-' }}</span>
          </div>
        </div>

        <el-divider />

        <div class="analysis-section" v-if="(currentReport.checklist && currentReport.checklist.length) || (currentReport.findings && currentReport.findings.length)">
          <div class="section-header">
            <el-icon><List /></el-icon>
            <span>检查清单</span>
          </div>
          <el-alert
            v-if="currentReport.verdict"
            :title="currentReport.verdict"
            :type="verdictAlertType"
            :closable="false"
            show-icon
            style="margin-bottom: 12px"
          />
          <div v-if="currentReport.findings && currentReport.findings.length" class="findings-list">
            <div class="chart-title">发现问题</div>
            <ol>
              <li v-for="(item, idx) in currentReport.findings" :key="idx">{{ item }}</li>
            </ol>
          </div>
          <el-table v-if="currentReport.checklist && currentReport.checklist.length" :data="currentReport.checklist" size="small" style="width: 100%">
            <el-table-column prop="name" label="检查项" min-width="160" />
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="checkTagType(row.level)" size="small" effect="plain">{{ checkLevelLabel(row.level) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="result" label="结果" min-width="240" />
            <el-table-column prop="source" label="数据源" width="160" />
          </el-table>
        </div>

        <div class="analysis-section" v-if="esClusters.length">
          <div class="section-header">
            <el-icon><Box /></el-icon>
            <span>Elasticsearch（elasticsearch-exporter）</span>
          </div>
          <el-table :data="esClusters" size="small" style="width: 100%">
            <el-table-column prop="cluster" label="集群" min-width="140" />
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="esStatusType(row.status)" size="small" effect="plain">{{ row.status || '-' }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="nodes" label="节点" width="80" />
            <el-table-column prop="data_nodes" label="数据节点" width="90" />
            <el-table-column prop="unassigned_shards" label="未分配分片" width="110" />
            <el-table-column prop="active_shards" label="活跃分片" width="90" />
          </el-table>
          <el-table
            v-if="esHeapNodes.length"
            :data="esHeapNodes"
            size="small"
            style="width: 100%; margin-top: 12px"
          >
            <el-table-column prop="cluster" label="集群" min-width="120" />
            <el-table-column prop="node" label="节点" min-width="160" />
            <el-table-column label="堆使用率" width="100">
              <template #default="{ row }">{{ row.heap_pct < 0 ? '-' : row.heap_pct + '%' }}</template>
            </el-table-column>
            <el-table-column label="已用" width="110">
              <template #default="{ row }">{{ formatBytes(row.used_bytes) }}</template>
            </el-table-column>
            <el-table-column label="堆上限" width="110">
              <template #default="{ row }">{{ formatBytes(row.max_bytes) }}</template>
            </el-table-column>
          </el-table>
        </div>

        <div class="analysis-section" v-if="currentReport.pvc_usage && currentReport.pvc_usage.length">
          <div class="section-header">
            <el-icon><Coin /></el-icon>
            <span>PVC 用量（全部 {{ currentReport.pvc_usage.length }} 块）</span>
          </div>
          <el-table :data="currentReport.pvc_usage" size="small" style="width: 100%" max-height="420">
            <el-table-column prop="namespace" label="Namespace" min-width="130" />
            <el-table-column prop="pvc" label="PVC" min-width="200" />
            <el-table-column prop="service" label="别名" min-width="110" />
            <el-table-column label="使用率" width="90">
              <template #default="{ row }">{{ row.pct < 0 ? '-' : row.pct + '%' }}</template>
            </el-table-column>
            <el-table-column label="已用" width="100">
              <template #default="{ row }">{{ formatBytes(row.used_bytes) }}</template>
            </el-table-column>
            <el-table-column label="容量" width="100">
              <template #default="{ row }">{{ formatBytes(row.capacity_bytes) }}</template>
            </el-table-column>
            <el-table-column prop="baseline" label="备注" min-width="160" />
          </el-table>
        </div>

        <div class="analysis-section" v-if="currentReport.known_normals && currentReport.known_normals.length">
          <div class="section-header">
            <el-icon><InfoFilled /></el-icon>
            <span>已知常态</span>
          </div>
          <ul class="known-normals">
            <li v-for="(item, idx) in currentReport.known_normals" :key="idx">{{ item }}</li>
          </ul>
        </div>

        <div class="analysis-section">
          <div class="section-header">
            <el-icon><MagicStick /></el-icon>
            <span>巡检报告摘要</span>
          </div>
          <div class="analysis-card">
            <div class="markdown-body">
              {{ currentReport.ai_analysis || 'No detailed analysis available for this report.' }}
            </div>
          </div>
        </div>

        <div class="analysis-section" v-if="currentReport.fleet_summary">
          <div class="section-header">
            <el-icon><Histogram /></el-icon>
            <span>服务器资源使用状况</span>
          </div>
          <el-row :gutter="20" class="metrics-row">
            <el-col :span="12" v-if="getServerTopOption('cpu_pct', 'CPU 使用率 Top 10 (%)').series">
              <div class="chart-card">
                <div class="chart-title">CPU 使用率 Top 10 (%)</div>
                <v-chart class="report-chart" :option="getServerTopOption('cpu_pct', 'CPU 使用率 Top 10 (%)')" autoresize />
              </div>
            </el-col>
            <el-col :span="12" v-if="getServerTopOption('mem_pct', '内存使用率 Top 10 (%)').series">
              <div class="chart-card">
                <div class="chart-title">内存使用率 Top 10 (%)</div>
                <v-chart class="report-chart" :option="getServerTopOption('mem_pct', '内存使用率 Top 10 (%)')" autoresize />
              </div>
            </el-col>
          </el-row>
          <el-row :gutter="20" class="metrics-row" style="margin-top: 20px;">
            <el-col :span="12" v-if="getServerTopOption('disk_pct', '磁盘(/)使用率 Top 10 (%)').series">
              <div class="chart-card">
                <div class="chart-title">磁盘(/)使用率 Top 10 (%)</div>
                <v-chart class="report-chart" :option="getServerTopOption('disk_pct', '磁盘(/)使用率 Top 10 (%)')" autoresize />
              </div>
            </el-col>
          </el-row>
          <el-table v-if="currentReport.servers && currentReport.servers.length" :data="currentReport.servers.slice(0, 50)" style="width: 100%; margin-top: 16px">
            <el-table-column prop="service" label="服务" min-width="140" />
            <el-table-column prop="instance" label="Instance" min-width="220" />
            <el-table-column prop="cpu_pct" label="CPU%" width="110" />
            <el-table-column prop="mem_pct" label="Mem%" width="110" />
            <el-table-column prop="disk_pct" label="Disk%(/)" width="110" />
            <el-table-column prop="load1" label="Load1" width="110" />
            <el-table-column prop="uptime_hours" label="Uptime(h)" width="120" />
          </el-table>
        </div>

        <div class="analysis-section" v-if="currentReport.alerts_summary">
          <div class="section-header">
            <el-icon><Warning /></el-icon>
            <span>告警分析</span>
          </div>
          <el-row :gutter="20" class="metrics-row">
            <el-col :span="12">
              <div class="chart-card">
                <div class="chart-title">Firing 告警严重度分布</div>
                <v-chart class="report-chart" :option="getAlertsPieOption()" autoresize />
              </div>
            </el-col>
            <el-col :span="12">
              <div class="chart-card">
                <div class="chart-title">Top 告警</div>
                <el-table :data="currentReport.alerts_summary.top_alerts || []" style="width: 100%">
                  <el-table-column prop="name" label="Alert" min-width="220" />
                  <el-table-column prop="count" label="Count" width="90" />
                </el-table>
              </div>
            </el-col>
          </el-row>
        </div>

        <div class="analysis-section" v-if="currentReport.trend_7d && currentReport.trend_7d.length">
          <div class="section-header">
            <el-icon><DataLine /></el-icon>
            <span>7 日趋势</span>
          </div>
          <div class="chart-card">
            <div class="chart-title">健康评分 / 告警数量趋势</div>
            <v-chart class="report-chart" :option="getTrendOption()" autoresize />
          </div>
        </div>
      </div>
      <template #footer>
        <el-button @click="dialogVisible = false">关闭</el-button>
        <el-button type="primary" @click="openTicketDialog">提交系统工单</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="ticketDialogVisible" title="提交系统运维工单" width="560px" destroy-on-close>
      <el-form label-position="top">
        <el-form-item label="标题">
          <el-input v-model="ticketTitle" />
        </el-form-item>
        <el-form-item label="严重度">
          <el-select v-model="ticketSeverity" style="width: 100%">
            <el-option label="低" value="low" />
            <el-option label="中" value="medium" />
            <el-option label="高" value="high" />
            <el-option label="紧急" value="critical" />
          </el-select>
        </el-form-item>
        <el-form-item label="说明（可编辑）">
          <el-input v-model="ticketDescription" type="textarea" :rows="12" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="ticketDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="ticketSubmitting" @click="submitOpsTicket">提交</el-button>
      </template>
    </el-dialog>

    <!-- Config Dialog -->
    <el-dialog v-model="configVisible" title="Inspection Configuration" width="540px" class="custom-dialog">
      <el-form :model="configForm" label-width="140px" label-position="top" class="config-form">
        <div class="form-section">
          <h3 class="section-title">Monitoring Data</h3>
          <el-form-item label="Prometheus Endpoint">
            <el-input v-model="configForm.prometheus_url" placeholder="http://prometheus:9090" />
            <div class="form-tip">巡检会拉 Prometheus：node-exporter、告警、pvc_stats_*（pvc-stats-exporter）、以及若存在的 kube-state-metrics / blackbox</div>
          </el-form-item>
        </div>

        <div class="form-section">
          <h3 class="section-title">AI Analysis Engine (Ark/Doubao)</h3>
          <el-form-item label="Ark Base URL">
            <el-input v-model="configForm.ark_base_url" placeholder="https://ark.cn-beijing.volces.com/api/v3" />
          </el-form-item>
          <el-form-item label="Ark API Key">
            <el-input
              v-model="configForm.ark_api_key"
              type="password"
              show-password
              :placeholder="configForm.ark_api_key_set ? '已保存密钥：留空表示不修改' : '可选'"
            />
          </el-form-item>
          <el-form-item label="Ark Model Endpoint ID">
            <el-input v-model="configForm.ark_model_id" placeholder="ep-202xxxxxxxx-xxxxx" />
          </el-form-item>
        </div>
      </el-form>
      <template #footer>
        <div class="dialog-footer">
          <el-button @click="configVisible = false">Cancel</el-button>
          <el-button type="primary" @click="saveConfig" class="shadow-btn">Save Configuration</el-button>
        </div>
      </template>
    </el-dialog>

    <!-- Logs Dialog -->
    <el-dialog v-model="logDialogVisible" title="System Inspection Logs" width="900px" top="5vh">
      <div class="log-viewer-container">
        <div class="log-header">
           <span class="log-filename">inspection.log</span>
           <div class="log-controls">
             <el-pagination 
               small
               layout="prev, pager, next"
               :total="logTotal"
               :page-size="logPageSize"
               v-model:current-page="logPage"
               @current-change="fetchLogs"
             />
             <el-button size="small" :icon="Refresh" circle @click="fetchLogs(logPage)" />
           </div>
        </div>
        <div class="log-content" v-loading="logLoading">
          <pre>{{ logContent || 'No logs available.' }}</pre>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed, watch, provide } from 'vue'
import { useRouter } from 'vue-router'
import { useSystemStore } from '@/stores/system'
import type { InspectionReport } from '@/types/system'
import { 
  Setting, Search, Calendar, 
  MagicStick, Warning, CircleCheck,
  DataLine, Histogram, Document, Refresh, Download,
  List, Box, Coin, InfoFilled
} from '@element-plus/icons-vue'
import { taskApi } from '@/api/task'
import { opsTicketsApi } from '@/api/ops_tickets'
import { ElMessage } from 'element-plus'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart, LineChart, PieChart } from 'echarts/charts'
import {
  TitleComponent,
  TooltipComponent,
  LegendComponent,
  GridComponent
} from 'echarts/components'

use([
  CanvasRenderer,
  BarChart,
  LineChart,
  PieChart,
  TitleComponent,
  TooltipComponent,
  LegendComponent,
  GridComponent
])

const systemStore = useSystemStore()
const router = useRouter()
const canViewInspection = computed(() => systemStore.isAdmin || systemStore.hasPermission('view_inspection'))
const canManage = computed(() => systemStore.isAdmin || systemStore.hasPermission('run_inspection'))
// ... existing refs and computed ...

const getServerTopOption = (key: string, title: string) => {
  const rep: any = currentReport.value
  const top = rep?.fleet_summary?.top_cpu || rep?.servers || []
  const list = Array.isArray(top) ? top : []
  const sorted = [...list].sort((a: any, b: any) => Number(b?.[key] || 0) - Number(a?.[key] || 0)).slice(0, 10)
  if (!sorted.length) return {}
  return {
    title: { text: '', left: 'center' },
    tooltip: { trigger: 'axis' },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: { type: 'category', data: sorted.map((s: any) => s.instance || '-'), axisLabel: { interval: 0, rotate: 25 } },
    yAxis: { type: 'value', name: '%' },
    series: [{ name: title, type: 'bar', data: sorted.map((s: any) => s[key]), itemStyle: { color: '#3b82f6' } }],
  }
}

const getAlertsPieOption = () => {
  const a: any = currentReport.value?.alerts_summary || {}
  const crit = Number(a.critical_total || 0)
  const warn = Number(a.warning_total || 0)
  const other = Math.max(0, Number(a.firing_total || 0) - crit - warn)
  return {
    tooltip: { trigger: 'item' },
    legend: { bottom: 0 },
    series: [
      {
        type: 'pie',
        radius: '70%',
        data: [
          { name: 'Critical/High', value: crit },
          { name: 'Warning', value: warn },
          { name: 'Other', value: other },
        ].filter((x) => x.value > 0),
      },
    ],
  }
}

const getTrendOption = () => {
  const t: any[] = (currentReport.value?.trend_7d || []) as any[]
  const dates = t.map((x) => x.date)
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['Score', 'Firing', 'Critical'] },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: { type: 'category', data: dates },
    yAxis: [
      { type: 'value', name: 'Score', min: 0, max: 100 },
      { type: 'value', name: 'Alerts', min: 0 },
    ],
    series: [
      { name: 'Score', type: 'line', yAxisIndex: 0, data: t.map((x) => x.score ?? null), smooth: true },
      { name: 'Firing', type: 'bar', yAxisIndex: 1, data: t.map((x) => x.firing ?? 0), itemStyle: { color: '#f59e0b' } },
      { name: 'Critical', type: 'bar', yAxisIndex: 1, data: t.map((x) => x.critical ?? 0), itemStyle: { color: '#ef4444' } },
    ],
  }
}
const reports = computed(() => systemStore.reports)
const loading = computed(() => systemStore.loading)
const inspectionConfig = computed(() => systemStore.inspectionConfig)

const tableData = computed(() => {
  return reports.value || []
})

const formatIdToDate = (id: string) => {
  if (!id) return '-'
  try {
    const d = new Date(id.replace(/-/g, '/'))
    return isNaN(d.getTime()) ? id : d.toLocaleString()
  } catch (e) {
    return id
  }
}

const dialogVisible = ref(false)
const configVisible = ref(false)
const currentReport = ref<InspectionReport | null>(null)

const configForm = ref({
  prometheus_url: '',
  ark_base_url: '',
  ark_api_key: '',
  ark_api_key_set: false,
  ark_model_id: ''
})

watch(inspectionConfig, (newVal) => {
  if (newVal) {
    configForm.value = { ...newVal }
  }
}, { immediate: true })

onMounted(() => {
  systemStore.fetchReports()
  systemStore.fetchInspectionConfig()
})

const handleRun = () => {
  systemStore.runInspection()
}

const saveConfig = async () => {
  await systemStore.saveInspectionConfig(configForm.value)
  configVisible.value = false
}

const getScoreType = (score: number) => {
  if (!score) return 'info'
  if (score >= 90) return 'success'
  if (score >= 70) return 'warning'
  return 'danger'
}

const getProgressStatus = (score: number) => {
  if (!score) return ''
  if (score >= 90) return 'success'
  if (score >= 70) return 'warning'
  return 'exception'
}

const esClusters = computed(() => currentReport.value?.elasticsearch?.clusters || [])
const esHeapNodes = computed(() => currentReport.value?.elasticsearch?.heap_nodes || [])

const esStatusType = (status?: string) => {
  if (status === 'green') return 'success'
  if (status === 'yellow') return 'warning'
  if (status === 'red') return 'danger'
  return 'info'
}

const checkTagType = (level?: string) => {
  if (level === 'ok') return 'success'
  if (level === 'warning') return 'warning'
  if (level === 'critical') return 'danger'
  if (level === 'info') return 'info'
  return 'info'
}

const checkLevelLabel = (level?: string) => {
  if (level === 'ok') return '正常'
  if (level === 'warning') return '关注'
  if (level === 'critical') return '严重'
  if (level === 'skip') return '未覆盖'
  if (level === 'info') return '常态'
  return level || '-'
}

const verdictAlertType = computed(() => {
  const v = currentReport.value?.verdict || ''
  if (v.includes('需关注')) return 'warning'
  if (v.includes('无法判定')) return 'warning'
  if (v.includes('未见明显异常')) return 'success'
  return 'info'
})

const formatBytes = (n?: number) => {
  const val = Number(n || 0)
  const units = ['B', 'Ki', 'Mi', 'Gi', 'Ti']
  let size = val
  let i = 0
  while (size >= 1024 && i < units.length - 1) {
    size /= 1024
    i += 1
  }
  return `${size.toFixed(1)}${units[i]}`
}

const viewReport = async (row: any) => {
  await systemStore.fetchReportDetail(row.report_id)
  const rep: any = systemStore.currentReport || {}
  const score =
    rep?.health_summary?.level === 'unknown'
      ? null
      : (rep?.health_summary?.score ??
        rep?.risk_summary?.score ??
        rep?.score ??
        row?.score ??
        null)
  currentReport.value = { ...rep, score }
  dialogVisible.value = true
}

const ticketDialogVisible = ref(false)
const ticketTitle = ref('')
const ticketDescription = ref('')
const ticketSeverity = ref('medium')
const ticketSubmitting = ref(false)

const openTicketDialog = () => {
  const rep: any = currentReport.value
  if (!rep?.report_id) {
    ElMessage.warning('报告数据不完整')
    return
  }
  const hs = rep.health_summary || rep.risk_summary || {}
  const reasons = (hs.reasons || []).filter(Boolean)
  const alerts = rep.alerts_summary?.top_alerts || []
  const rid = rep.report_id as string
  ticketTitle.value = `巡检处置 · ${rid}`
  let desc = `关联巡检报告: ${rid}\n健康分: ${rep.score ?? '-'}\n`
  if (reasons.length) desc += '\n健康原因:\n' + reasons.map((r: string) => `- ${r}`).join('\n')
  if (alerts.length)
    desc += '\nTOP 告警:\n' + alerts.slice(0, 8).map((a: any) => `- ${a.name} (${a.count})`).join('\n')
  if (rep.ai_analysis) desc += '\n\n摘要:\n' + String(rep.ai_analysis).slice(0, 1200)
  ticketDescription.value = desc
  ticketSeverity.value =
    rep.score != null && Number(rep.score) < 60 ? 'critical' : Number(rep.score) < 80 ? 'high' : 'medium'
  ticketDialogVisible.value = true
}

const submitOpsTicket = async () => {
  const rep: any = currentReport.value
  if (!rep?.report_id) return
  ticketSubmitting.value = true
  try {
    const hs = rep.health_summary || rep.risk_summary || {}
    await opsTicketsApi.create({
      title: ticketTitle.value,
      description: ticketDescription.value,
      inspection_report_id: rep.report_id as string,
      severity: ticketSeverity.value,
      inspection_snapshot: {
        score: rep.score,
        health_reasons: hs.reasons || [],
        top_alerts: (rep.alerts_summary?.top_alerts || []).slice(0, 15),
      },
    })
    ElMessage.success('工单已提交')
    ticketDialogVisible.value = false
    dialogVisible.value = false
    router.push('/system/tickets')
  } finally {
    ticketSubmitting.value = false
  }
}

// Log Viewer Logic
const logDialogVisible = ref(false)
const logLoading = ref(false)
const logContent = ref('')
const logPage = ref(1)
const logPageSize = ref(1000)
const logTotal = ref(0)

const showLogs = () => {
  logDialogVisible.value = true
  fetchLogs(1)
}

const fetchLogs = async (page = 1) => {
  logPage.value = page
  logLoading.value = true
  try {
    // Assuming inspection.log exists in logs/inspection.log or just inspection
    // taskApi.getTaskLogs takes a task_id and appends .log
    // So 'inspection' -> 'logs/inspection.log'
    const res = await taskApi.getTaskLogs('inspection', { 
      page, 
      page_size: logPageSize.value,
      reverse: true 
    })
    logContent.value = res.lines.join('')
    logTotal.value = res.total
  } catch (e) {
    logContent.value = `Error loading logs: ${e}`
  } finally {
    logLoading.value = false
  }
}
</script>

<style scoped>
/* Log Viewer Styles */
.log-viewer-container {
  display: flex;
  flex-direction: column;
  height: 600px;
  background: #0f172a;
  border-radius: 4px;
  overflow: hidden;
}

.log-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 16px;
  background: #1e293b;
  border-bottom: 1px solid #334155;
  color: #e2e8f0;
}

.log-filename {
  font-weight: 600;
  font-size: 14px;
}

.log-controls {
  display: flex;
  align-items: center;
  gap: 12px;
}

.log-content {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  color: #cbd5e1;
  font-family: 'Menlo', monospace;
  font-size: 12px;
  line-height: 1.5;
}

.log-content pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-all;
}

/* Existing Styles */
.inspection-container {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.page-title {
  font-size: 24px;
  font-weight: 700;
  color: #1e293b;
  margin: 0 0 4px 0;
}

.page-subtitle {
  font-size: 14px;
  color: #64748b;
  margin: 0;
}

.table-card {
  border: 1px solid #f1f5f9 !important;
  border-radius: 12px !important;
}

.report-id-cell {
  display: flex;
  align-items: center;
  gap: 10px;
  font-family: ui-monospace, monospace;
  font-size: 13px;
  color: #334155;
}

.report-icon {
  color: #3b82f6;
}

.score-wrapper {
  display: flex;
  align-items: center;
  gap: 12px;
}

.score-tag {
  font-weight: 700;
  font-size: 12px;
  min-width: 36px;
  text-align: center;
}

.status-icon-placeholder {
  font-size: 24px;
  color: #94a3b8;
}

.summary-text {
  font-size: 13px;
  color: #64748b;
}

.report-content {
  padding: 8px;
}

.report-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 32px 48px;
  margin-bottom: 24px;
}

.findings-list ol {
  margin: 0 0 12px 18px;
  padding: 0;
  color: #334155;
  font-size: 13px;
  line-height: 1.7;
}

.known-normals {
  margin: 0;
  padding-left: 18px;
  color: #64748b;
  font-size: 13px;
  line-height: 1.8;
}

.meta-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.meta-item .label {
  font-size: 11px;
  font-weight: 800;
  color: #94a3b8;
  letter-spacing: 0.5px;
}

.meta-item .value {
  font-size: 15px;
  font-weight: 600;
  color: #1e293b;
}

.score-display {
  display: flex;
  align-items: baseline;
  gap: 2px;
}

.score-value {
  font-size: 32px;
  font-weight: 800;
}

.score-value.success { color: #10b981; }
.score-value.warning { color: #f59e0b; }
.score-value.danger { color: #ef4444; }

.score-total {
  font-size: 14px;
  color: #94a3b8;
  font-weight: 600;
}

.analysis-section {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.section-header {
  display: flex;
  align-items: center;
  gap: 10px;
  font-weight: 700;
  color: #1e293b;
  font-size: 16px;
}

.section-header .el-icon {
  color: #8b5cf6;
}

.analysis-card {
  background: #f8fafc;
  border: 1px solid #f1f5f9;
  border-radius: 12px;
  padding: 24px;
}

.markdown-body {
  white-space: pre-wrap;
  line-height: 1.8;
  font-size: 14px;
  color: #334155;
}

.metrics-row {
  margin-top: 10px;
}

.chart-card {
  background: white;
  border: 1px solid #f1f5f9;
  border-radius: 8px;
  padding: 16px;
}

.chart-title {
  font-size: 12px;
  font-weight: 700;
  color: #64748b;
  margin-bottom: 12px;
  text-transform: uppercase;
}

.report-chart {
  height: 200px;
}

.forecast-card {
  display: flex;
  justify-content: space-around;
  background: white;
  border: 1px solid #f1f5f9;
  border-radius: 8px;
  padding: 20px;
}

.forecast-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.forecast-item .label {
  font-size: 12px;
  color: #94a3b8;
  font-weight: 600;
  text-transform: uppercase;
}

.forecast-item .value {
  font-size: 24px;
  font-weight: 700;
  color: #3b82f6;
}

.form-section {
  margin-bottom: 24px;
  padding: 16px;
  background: #f8fafc;
  border-radius: 8px;
}

.section-title {
  font-size: 13px;
  font-weight: 700;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 16px;
  border-left: 3px solid #3b82f6;
  padding-left: 8px;
}

.form-tip {
  font-size: 11px;
  color: #94a3b8;
  margin-top: 4px;
}

.shadow-btn {
  box-shadow: 0 4px 12px rgba(59, 130, 246, 0.2);
}

:deep(.el-form-item__label) {
  font-weight: 600;
  color: #475569;
  font-size: 13px;
}
</style>
