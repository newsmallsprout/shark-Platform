<template>
  <div class="ai-ops-container">
    <div class="page-header">
      <div class="header-info">
        <h2 class="page-title">智能故障分析</h2>
        <p class="page-subtitle">
          基于大模型与工具调用的根因分析。列表数据来自 Alertmanager Webhook（<code>/api/ai_ops/webhook/prometheus</code>），与 Traffic 接入无关。
        </p>
      </div>
      <div class="header-actions">
        <el-button @click="openConfig" :icon="Setting">配置</el-button>
        <el-button @click="fetchIncidents" :icon="Refresh" circle />
      </div>
    </div>

    <el-row :gutter="24">
      <!-- Incident List -->
      <el-col :span="8">
        <el-card shadow="never" class="list-card">
          <div class="list-header">
            <span>最近告警</span>
          </div>
          <div v-loading="loading" class="incident-list">
            <div 
              v-for="inc in incidents" 
              :key="inc.id"
              class="incident-item"
              :class="{ active: selectedId === inc.id }"
              @click="selectIncident(inc)"
            >
              <div class="inc-status">
                <el-tag :type="getStatusType(inc.status)" size="small" effect="dark">{{ inc.status }}</el-tag>
              </div>
              <div class="inc-info">
                <div class="inc-title">{{ inc.alert_name }}</div>
                <div class="inc-meta">
                  <span :class="['severity-dot', inc.severity]"></span>
                  {{ inc.severity.toUpperCase() }} • {{ listTimeLabel(inc) }}
                  <span v-if="(inc.occurrence_count || 0) > 1" class="occ-badge">×{{ inc.occurrence_count }}</span>
                </div>
              </div>
              <el-icon class="arrow-icon"><ArrowRight /></el-icon>
            </div>
            <el-empty v-if="incidents.length === 0" description="暂无告警" />
          </div>
        </el-card>
      </el-col>

      <!-- Analysis Detail -->
      <el-col :span="16">
        <el-card shadow="never" class="detail-card" v-if="selectedId">
          <template #header>
            <div class="detail-header">
              <span>分析报告 #{{ selectedId }}</span>
              <el-tag v-if="detailLoading" type="info">加载中...</el-tag>
            </div>
          </template>
          
          <div v-loading="detailLoading" class="detail-content">
            <div v-if="currentDetail">
              <!-- Alert Summary -->
              <div class="section-block">
                <h3 class="section-title"><el-icon><Warning /></el-icon> 告警描述</h3>
                <p class="text-content">{{ currentDetail.description }}</p>
                <div class="json-box">
                    <pre>{{ JSON.stringify(currentDetail.raw_alert_data, null, 2) }}</pre>
                </div>
              </div>

              <!-- Agent trace (ReAct + tools) -->
              <div
                v-if="(currentDetail.agent_trace?.length || 0) > 0"
                class="trace-box"
              >
                <h3 class="section-title"><el-icon><Monitor /></el-icon> Agent 排查轨迹</h3>
                <p class="trace-intro">
                  模型多轮调用只读工具（日志 / Prometheus / K8s）的过程摘要；完整 Observation 见下方 JSON。
                </p>
                <el-collapse>
                  <el-collapse-item title="展开查看 agent_trace" name="trace">
                    <pre class="trace-json">{{ JSON.stringify(currentDetail.agent_trace, null, 2) }}</pre>
                  </el-collapse-item>
                </el-collapse>
              </div>

              <!-- AI Analysis -->
              <div v-if="currentDetail.report" class="ai-report-box">
                <div class="report-header">
                  <el-icon><Cpu /></el-icon> 故障原因分析
                </div>
                <div class="report-body">
                  <div class="analysis-section">
                    <div class="label">故障现象</div>
                    <p>{{ currentDetail.report.phenomenon }}</p>
                  </div>

                  <div class="analysis-section">
                    <div class="label">根本原因 (进程/Pod)</div>
                    <p class="root-cause">{{ currentDetail.report.root_cause }}</p>
                  </div>
                  
                  <div class="analysis-grid">
                    <div class="analysis-card mitigation">
                        <div class="label">紧急处理 (Mitigation)</div>
                        <p>{{ currentDetail.report.mitigation }}</p>
                    </div>
                    <div class="analysis-card prevention">
                        <div class="label">预防措施 (Prevention)</div>
                        <p>{{ currentDetail.report.prevention }}</p>
                    </div>
                  </div>

                  <div class="analysis-section" v-if="currentDetail.report.refactoring">
                    <div class="label">整改建议</div>
                    <p>{{ currentDetail.report.refactoring }}</p>
                  </div>

                  <div class="analysis-section" v-if="currentDetail.report.platform_linkage">
                    <div class="label">平台联动</div>
                    <p>{{ currentDetail.report.platform_linkage }}</p>
                  </div>

                  <div class="solutions" v-if="currentDetail.report.solutions?.length">
                    <div class="label">可执行命令</div>
                    <div class="cmd-list">
                      <div v-for="(sol, idx) in currentDetail.report.solutions" :key="idx" class="cmd-item">
                        <code>> {{ sol }}</code>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
              <div v-else-if="currentDetail.status === 'analyzing'" class="analyzing-state">
                <el-icon class="is-loading"><Loading /></el-icon>
                <span>{{ analyzingMessage }}</span>
              </div>
              <div v-else-if="currentDetail.status === 'awaiting_evidence'" class="no-report mild">
                状态 awaiting_evidence 为旧数据；新告警由 Agent 自动分析，无需粘贴命令输出。
              </div>
              <div v-else class="no-report">
                暂无分析报告
              </div>

              <!-- Metrics Chart -->
              <div
                v-if="chartDataKeys.length"
                class="chart-section"
              >
                <h3 class="section-title"><el-icon><TrendCharts /></el-icon> 监控指标证据</h3>
                <div ref="chartRef" class="metrics-chart"></div>
              </div>

              <!-- Diagnostic Logs -->
              <div v-if="currentDetail.report && currentDetail.report.diagnosis_logs && currentDetail.report.diagnosis_logs.length" class="logs-section">
                <h3 class="section-title"><el-icon><Monitor /></el-icon> 诊断日志证据</h3>
                <div class="logs-container">
                  <div v-for="(log, idx) in currentDetail.report.diagnosis_logs" :key="idx" class="log-block">
                    <pre>{{ log }}</pre>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </el-card>
        <el-empty v-else description="请选择一个告警以查看分析" class="empty-detail" />
      </el-col>
    </el-row>

    <!-- Configuration Dialog -->
    <el-dialog v-model="configVisible" title="AI 分析配置" width="600px">
      <el-form :model="configForm" label-width="120px">
        <el-form-item label="Provider">
          <el-select v-model="configForm.provider">
            <el-option label="OpenAI" value="openai" />
            <el-option label="DeepSeek" value="deepseek" />
            <el-option label="Custom" value="custom" />
          </el-select>
        </el-form-item>
        <el-form-item label="API Base URL">
          <el-input v-model="configForm.api_base" />
        </el-form-item>
        <el-form-item label="API Key">
          <el-input
            v-model="configForm.api_key"
            type="password"
            show-password
            :placeholder="configForm.api_key_set ? '已保存密钥：留空表示不修改' : '必填以启用模型调用'"
          />
        </el-form-item>
        <el-form-item label="Model Name">
          <el-input v-model="configForm.model" placeholder="e.g. gpt-4, deepseek-chat" />
        </el-form-item>
        <el-form-item label="Max Tokens">
          <el-input-number v-model="configForm.max_tokens" :min="100" :max="8000" />
        </el-form-item>
        <el-form-item label="Temperature">
          <el-slider v-model="configForm.temperature" :min="0" :max="2" :step="0.1" show-input />
        </el-form-item>
        <el-form-item label="启用 AI">
          <el-switch v-model="configForm.enable_ai_analysis" />
        </el-form-item>
        <el-form-item label="Agent 最大轮次">
          <el-input-number v-model="configForm.max_agent_iterations" :min="1" :max="24" />
        </el-form-item>
        <el-form-item label="单事件工具上限">
          <el-input-number v-model="configForm.max_tool_calls_per_incident" :min="1" :max="80" />
        </el-form-item>
        <el-form-item label="Prompt 模板（遗留）">
          <el-input v-model="configForm.prompt_template" type="textarea" :rows="4" />
          <span class="form-hint">SRE Agent 使用内置系统提示；此项仅兼容旧配置存储</span>
        </el-form-item>
        <el-form-item label="最终 Prompt（遗留）">
          <el-input v-model="configForm.final_prompt_template" type="textarea" :rows="4" />
        </el-form-item>
      </el-form>
      <template #footer>
        <span class="dialog-footer">
          <el-button @click="configVisible = false">取消</el-button>
          <el-button type="primary" @click="saveConfig">保存</el-button>
        </span>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, nextTick, watch, onUnmounted, reactive } from 'vue'
import { aiOpsApi } from '@/api/ai_ops'
import { Refresh, ArrowRight, Warning, Cpu, Loading, TrendCharts, Setting, Monitor } from '@element-plus/icons-vue'
import * as echarts from 'echarts'
import { ElMessage } from 'element-plus'

const loading = ref(false)
const detailLoading = ref(false)
const incidents = ref<any[]>([])
const selectedId = ref<number | null>(null)
const currentDetail = ref<any>(null)
const chartRef = ref<HTMLElement>()
let chartInstance: echarts.ECharts | null = null

const chartDataKeys = computed(() => {
  const m =
    currentDetail.value?.chart_metrics ||
    currentDetail.value?.report?.related_metrics ||
    {}
  return Object.keys(m || {})
})

const analyzingMessage = computed(() => 'SRE Agent 正在调用工具（日志 / Prom / K8s）并生成结论，请稍候…')

function listTimeLabel(inc: { last_received_at?: string; started_at?: string }) {
  const raw = inc.last_received_at || inc.started_at
  if (!raw) return '—'
  return new Date(raw).toLocaleString()
}

// Config State
const configVisible = ref(false)
const configForm = reactive({
  provider: 'openai',
  api_base: '',
  api_key: '',
  api_key_set: false,
  model: '',
  max_tokens: 2000,
  temperature: 0.7,
  prompt_template: '',
  final_prompt_template: '',
  enable_ai_analysis: true,
  max_agent_iterations: 12,
  max_tool_calls_per_incident: 36,
})

const openConfig = async () => {
  try {
    const res = await aiOpsApi.getConfig() as any
    Object.assign(configForm, res)
    configForm.api_key = ''
    configVisible.value = true
  } catch (error) {
    ElMessage.error('Failed to load config')
  }
}

const saveConfig = async () => {
  try {
    await aiOpsApi.updateConfig(configForm)
    ElMessage.success('Configuration saved')
    configVisible.value = false
    const res = await aiOpsApi.getConfig() as any
    Object.assign(configForm, res)
    configForm.api_key = ''
  } catch (error) {
    ElMessage.error('Failed to save config')
  }
}

const fetchIncidents = async () => {
  loading.value = true
  try {
    const res = await aiOpsApi.getIncidents() as any
    incidents.value = res.incidents
  } finally {
    loading.value = false
  }
}

const selectIncident = async (inc: any) => {
  selectedId.value = inc.id
  detailLoading.value = true
  currentDetail.value = null
  try {
    const res = await aiOpsApi.getIncidentDetail(inc.id) as any
    currentDetail.value = res
    const metrics = res.chart_metrics || res.report?.related_metrics
    if (metrics && Object.keys(metrics).length) {
      nextTick(() => renderChart(metrics))
    }
  } finally {
    detailLoading.value = false
  }
}

const getStatusType = (status: string) => {
  if (status === 'analyzed') return 'success'
  if (status === 'analyzing') return 'warning'
  if (status === 'awaiting_evidence') return 'info' // legacy rows only
  if (status === 'resolved') return 'info'
  return 'danger'
}

const renderChart = (metrics: any) => {
  if (!chartRef.value) return
  if (chartInstance) chartInstance.dispose()
  
  chartInstance = echarts.init(chartRef.value)
  
  // Example: render first metric found
  const series: any[] = []
  const legendData: string[] = []
  let xAxisData: string[] = []

  for (const [key, data] of Object.entries(metrics)) {
      // Assuming prometheus result format
      // data = [{ metric: {}, values: [[ts, val], ...] }]
      if (Array.isArray(data)) {
          data.forEach((seriesData: any, idx) => {
              const name = `${key}-${idx}`
              legendData.push(name)
              const values = seriesData.values || []
              if (idx === 0) {
                  xAxisData = values.map((v: any[]) => new Date(v[0] * 1000).toLocaleTimeString())
              }
              series.push({
                  name: name,
                  type: 'line',
                  data: values.map((v: any[]) => parseFloat(v[1])),
                  smooth: true
              })
          })
      }
  }

  if (series.length === 0) {
      chartInstance.setOption({ 
          title: { text: 'No metric data available', left: 'center', top: 'center' }
      })
      return
  }

  chartInstance.setOption({
      tooltip: { trigger: 'axis' },
      legend: { data: legendData, bottom: 0 },
      grid: { left: '3%', right: '4%', bottom: '10%', containLabel: true },
      xAxis: { type: 'category', data: xAxisData },
      yAxis: { type: 'value' },
      series: series
  })
}

let pollTimer: ReturnType<typeof setTimeout> | null = null
function scheduleDetailPoll() {
  if (pollTimer) clearTimeout(pollTimer)
  const id = selectedId.value
  if (!id || currentDetail.value?.status !== 'analyzing') return
  pollTimer = setTimeout(async () => {
    if (selectedId.value === id) {
      await selectIncident({ id })
      scheduleDetailPoll()
    }
  }, 5000)
}

watch(
  () => [selectedId.value, currentDetail.value?.status],
  () => scheduleDetailPoll()
)

onMounted(() => {
  fetchIncidents()
  window.addEventListener('resize', () => chartInstance?.resize())
})

onUnmounted(() => {
  if (pollTimer) clearTimeout(pollTimer)
  chartInstance?.dispose()
})
</script>

<style scoped>
.ai-ops-container {
  display: flex;
  flex-direction: column;
  gap: 20px;
  height: calc(100vh - 100px);
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
  margin: 0;
}

.page-subtitle {
  font-size: 14px;
  color: #64748b;
  margin: 0;
}

.list-card, .detail-card {
  height: calc(100vh - 180px);
  display: flex;
  flex-direction: column;
}

.list-card :deep(.el-card__body), .detail-card :deep(.el-card__body) {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  padding: 0;
}

.list-header {
  padding: 16px;
  font-weight: 600;
  border-bottom: 1px solid #f1f5f9;
  background: #f8fafc;
}

.incident-list {
  flex: 1;
  overflow-y: auto;
}

.incident-item {
  padding: 16px;
  border-bottom: 1px solid #f1f5f9;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 12px;
  transition: all 0.2s;
}

.incident-item:hover { background: #f8fafc; }
.incident-item.active { background: #f0f9ff; border-left: 3px solid #3b82f6; }

.inc-info { flex: 1; }
.inc-title { font-weight: 600; color: #334155; margin-bottom: 4px; }
.inc-meta { font-size: 12px; color: #94a3b8; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.occ-badge { font-size: 10px; color: #64748b; margin-left: 4px; }

.severity-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.severity-dot.critical { background: #ef4444; box-shadow: 0 0 4px #ef4444; }
.severity-dot.warning { background: #f59e0b; }
.severity-dot.info { background: #3b82f6; }

.detail-header {
  font-weight: 600;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.detail-content {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
}

.section-block { margin-bottom: 24px; }
.section-title { font-size: 16px; font-weight: 600; color: #1e293b; display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
.text-content { font-size: 14px; color: #475569; line-height: 1.6; }

.json-box {
  background: #1e293b;
  color: #e2e8f0;
  padding: 12px;
  border-radius: 8px;
  font-size: 12px;
  max-height: 200px;
  overflow: auto;
}

.ai-report-box {
  background: linear-gradient(to bottom right, #f0f9ff, #e0f2fe);
  border: 1px solid #bae6fd;
  border-radius: 12px;
  padding: 20px;
  margin-bottom: 24px;
}

.report-header {
  font-size: 16px;
  font-weight: 700;
  color: #0369a1;
  margin-bottom: 20px;
  display: flex;
  align-items: center;
  gap: 8px;
  border-bottom: 1px solid #bae6fd;
  padding-bottom: 12px;
}

.analysis-section { margin-bottom: 20px; }
.analysis-section .label { 
    font-size: 12px; 
    font-weight: 700; 
    color: #0284c7; 
    text-transform: uppercase; 
    margin-bottom: 6px; 
}
.analysis-section p { margin: 0; color: #334155; line-height: 1.6; }

.root-cause { font-weight: 600; color: #be185d !important; font-size: 15px; }

.analysis-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
    margin-bottom: 20px;
}

.analysis-card {
    background: rgba(255,255,255,0.6);
    padding: 12px;
    border-radius: 8px;
}
.analysis-card .label { font-size: 11px; font-weight: 700; margin-bottom: 4px; text-transform: uppercase; }
.analysis-card.mitigation .label { color: #d97706; }
.analysis-card.prevention .label { color: #059669; }

.solutions .label { 
    font-size: 12px; 
    font-weight: 700; 
    color: #475569; 
    text-transform: uppercase; 
    margin-bottom: 8px; 
}
.cmd-list { background: #0f172a; border-radius: 8px; overflow: hidden; }
.cmd-item { 
    padding: 10px 16px; 
    border-bottom: 1px solid #1e293b; 
    font-family: 'Menlo', 'Monaco', monospace; 
    font-size: 13px; 
    color: #a5f3fc;
}
.cmd-item:last-child { border-bottom: none; }

.metrics-chart {
  height: 300px;
  width: 100%;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 12px;
}

.analyzing-state {
  text-align: center;
  padding: 40px;
  color: #64748b;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
}
.analyzing-state .el-icon { font-size: 32px; color: #3b82f6; }

.empty-detail { height: 100%; }

.trace-box {
  margin-bottom: 24px;
  padding: 20px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
}
.trace-intro {
  font-size: 14px;
  color: #475569;
  line-height: 1.6;
  margin: 0 0 12px;
}
.trace-json {
  margin: 0;
  padding: 12px;
  background: #1e293b;
  color: #e2e8f0;
  border-radius: 8px;
  font-size: 11px;
  max-height: 420px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
}
.no-report.mild {
  color: #64748b;
  font-size: 14px;
  padding: 16px;
  text-align: center;
}
.form-hint {
  margin-left: 8px;
  font-size: 12px;
  color: #94a3b8;
}
</style>
