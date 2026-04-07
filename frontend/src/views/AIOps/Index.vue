<template>
  <div class="ai-ops-container l5-aiops">
    <div class="page-header">
      <div class="header-info">
        <h2 class="page-title">运维台 · 诊断与工单</h2>
        <p class="page-subtitle">
          告警 → <strong>LangGraph</strong>（SSE 思维流）→ 内联审批；高置信命中经验库时中心可下发边缘 Playbook。
          <router-link class="back-dash" to="/">返回概览</router-link>
        </p>
      </div>
      <div class="header-actions">
        <el-button :icon="Setting" @click="openConfig">配置</el-button>
        <el-button :icon="Refresh" circle @click="fetchIncidents" />
      </div>
    </div>

    <el-row :gutter="24">
      <el-col :span="8">
        <el-card shadow="never" class="list-card">
          <div class="list-header">最近告警</div>
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
                  <span :class="['severity-dot', inc.severity]" />
                  {{ inc.severity.toUpperCase() }} · {{ listTimeLabel(inc) }}
                  <span v-if="(inc.occurrence_count || 0) > 1" class="occ-badge">×{{ inc.occurrence_count }}</span>
                </div>
              </div>
              <el-icon class="arrow-icon"><ArrowRight /></el-icon>
            </div>
            <el-empty v-if="!incidents.length" description="暂无告警" />
          </div>
        </el-card>
      </el-col>

      <el-col :span="16">
        <el-card v-if="selectedId" shadow="never" class="detail-card">
          <template #header>
            <div class="detail-header">
              <span>Incident #{{ selectedId }}</span>
              <el-tag v-if="detailLoading" type="info" size="small">刷新中…</el-tag>
            </div>
          </template>

          <div v-loading="detailLoading" class="detail-scroll">
            <!-- —— 1. LangGraph 触发 + SSE —— -->
            <section class="section-langgraph">
              <h3 class="section-title">
                <el-icon><Cpu /></el-icon>
                LangGraph 异步诊断
              </h3>
              <p class="section-hint">
                填写排障指引后启动；思维流结束后在本页<strong>内联审批</strong>。审批<strong>打回</strong>将携带理由触发 AI 反思并重挂新一轮 SSE，无需刷新。
              </p>
              <div class="diagnose-trigger-area">
                <el-input
                  v-model="userNote"
                  type="textarea"
                  :rows="2"
                  maxlength="2000"
                  show-word-limit
                  placeholder="补充排障方向（可选），例如：刚上了新版本，重点查 DB 慢查询…"
                  class="context-input"
                />
                <el-button
                  type="primary"
                  class="btn-diagnose-full"
                  :loading="diagnoseLoading"
                  :disabled="!selectedId || diagnoseLoading"
                  @click="startLangGraphDiagnose"
                >
                  <el-icon class="btn-diagnose-icon"><Cpu /></el-icon>
                  启动 AI 智能诊断
                </el-button>
                <div v-if="streamRunId" class="mono stream-meta">run_id {{ streamRunId.slice(0, 8) }}…</div>
              </div>
            </section>

            <div v-if="streamVisible && streamRunId && streamSseUrl" class="stream-wrap">
              <AgentThoughtStream
                :key="streamKey"
                :run-id="streamRunId"
                :sse-stream-url="streamSseUrl"
                :hide-completion-result="true"
                @done="onStreamDone"
                @error="onStreamError"
              />
            </div>

            <!-- —— 2. 内联审批（思维流完成后，上下文最全） —— -->
            <el-card v-if="currentTicketId" shadow="never" class="inline-approval-card">
              <template #header>
                <div class="inline-approval-head">
                  <span class="inline-approval-title">
                    <el-icon><CircleCheck /></el-icon>
                    智能工单审批
                    <span class="mono inline-ticket-id">({{ currentTicketId }})</span>
                  </span>
                  <el-tag
                    v-if="ticketDetail"
                    :type="ticketStatusTag(ticketDetail.status)"
                    effect="dark"
                    size="small"
                  >
                    {{ ticketDetail.status }}
                  </el-tag>
                  <el-tag v-else type="info" size="small">加载中…</el-tag>
                </div>
              </template>

              <el-skeleton v-if="ticketLoading" :rows="6" animated />
              <template v-else-if="ticketDetail">
                <el-descriptions :column="1" border size="small" class="ticket-desc">
                  <el-descriptions-item label="ticket_id">
                    <span class="mono">{{ ticketDetail.ticket_id }}</span>
                  </el-descriptions-item>
                  <el-descriptions-item label="状态">
                    <el-tag :type="ticketStatusTag(ticketDetail.status)" effect="dark">{{ ticketDetail.status }}</el-tag>
                  </el-descriptions-item>
                  <el-descriptions-item label="摘要">{{ ticketDetail.summary || '—' }}</el-descriptions-item>
                  <el-descriptions-item label="根因">{{ ticketDetail.root_cause || '—' }}</el-descriptions-item>
                  <el-descriptions-item label="拟执行方案">
                    <pre class="ticket-pre">{{ ticketDetail.proposed_action || '—' }}</pre>
                  </el-descriptions-item>
                  <el-descriptions-item v-if="ticketDetail.routing" label="路由">
                    {{ ticketDetail.routing }}
                    <span v-if="ticketDetail.auto_heal_dispatched" class="occ-badge">auto</span>
                  </el-descriptions-item>
                  <el-descriptions-item v-if="ticketDetail.ai_confidence != null" label="AI 置信度">
                    {{ Number(ticketDetail.ai_confidence).toFixed(3) }}
                  </el-descriptions-item>
                  <el-descriptions-item v-if="userNote.trim()" label="排障指引（发起诊断时）">
                    <pre class="ticket-pre note">{{ userNote }}</pre>
                  </el-descriptions-item>
                </el-descriptions>

                <div v-if="ticketDetail.status === 'draft'" class="approval-row">
                  <el-button type="primary" :loading="ticketActionLoading" @click="submitTicketForApproval">
                    提交审批（进入待审队列）
                  </el-button>
                  <span class="approval-tip">提交后 Leader 可在独立工作台批复；有权限者也可在此继续操作。</span>
                </div>

                <div v-else-if="ticketDetail.status === 'pending_approval'" class="approval-row pending-body">
                  <el-input
                    v-model="approveComment"
                    type="textarea"
                    :rows="2"
                    placeholder="批准意见（可选）"
                    class="approval-comment"
                  />
                </div>

                <el-result
                  v-else-if="ticketDetail.status === 'approved'"
                  icon="success"
                  title="已批准"
                  sub-title="写操作可携带 X-Shark-Work-Order-Id 头由执行器落库（见工单闸门配置）。"
                />
                <el-result
                  v-else-if="ticketDetail.status === 'rejected'"
                  icon="error"
                  title="已驳回"
                  :sub-title="ticketDetail.approval_comment || '—'"
                />
                <el-result
                  v-else-if="ticketDetail.status === 'executed'"
                  icon="success"
                  title="已执行闭环"
                />
              </template>

              <template v-if="ticketDetail?.status === 'pending_approval'" #footer>
                <div class="inline-approval-footer">
                  <el-button type="danger" plain :loading="ticketActionLoading" @click="promptRejectAndRetry">
                    打回并让 AI 重试
                  </el-button>
                  <el-button type="success" :loading="ticketActionLoading" @click="approveTicket">
                    批准执行
                  </el-button>
                </div>
              </template>
            </el-card>

            <el-divider content-position="left">告警与历史报告</el-divider>

            <div v-if="currentDetail" class="legacy-blocks">
              <div class="section-block">
                <h3 class="section-title"><el-icon><Warning /></el-icon> 告警描述</h3>
                <p class="text-content">{{ currentDetail.description }}</p>
                <div class="json-box">
                  <pre>{{ JSON.stringify(currentDetail.raw_alert_data, null, 2) }}</pre>
                </div>
              </div>

              <div v-if="(currentDetail.agent_trace?.length || 0) > 0" class="trace-box">
                <h3 class="section-title"><el-icon><Monitor /></el-icon> 历史 Agent 轨迹（旧链路）</h3>
                <el-collapse>
                  <el-collapse-item title="agent_trace" name="t">
                    <pre class="trace-json">{{ JSON.stringify(currentDetail.agent_trace, null, 2) }}</pre>
                  </el-collapse-item>
                </el-collapse>
              </div>

              <div v-if="currentDetail.report" class="ai-report-box">
                <div class="report-header">
                  <el-icon><Cpu /></el-icon> 分析报告（同步 / 历史）
                </div>
                <div class="report-body">
                  <div class="analysis-section">
                    <div class="label">故障现象</div>
                    <p>{{ currentDetail.report.phenomenon }}</p>
                  </div>
                  <div class="analysis-section">
                    <div class="label">根本原因</div>
                    <p class="root-cause">{{ currentDetail.report.root_cause }}</p>
                  </div>
                  <div class="analysis-grid">
                    <div class="analysis-card mitigation">
                      <div class="label">紧急处理</div>
                      <p>{{ currentDetail.report.mitigation }}</p>
                    </div>
                    <div class="analysis-card prevention">
                      <div class="label">预防</div>
                      <p>{{ currentDetail.report.prevention }}</p>
                    </div>
                  </div>
                  <div v-if="currentDetail.report.solutions?.length" class="solutions">
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
              <div v-else class="no-report">暂无同步分析报告（可使用上方 LangGraph 生成工单）</div>

              <div v-if="chartDataKeys.length" class="chart-section">
                <h3 class="section-title"><el-icon><TrendCharts /></el-icon> 监控指标</h3>
                <div ref="chartRef" class="metrics-chart" />
              </div>
            </div>
          </div>
        </el-card>
        <el-empty v-else description="请选择一个告警" class="empty-detail" />
      </el-col>
    </el-row>

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
          <el-input v-model="configForm.api_key" type="password" show-password />
        </el-form-item>
        <el-form-item label="Model Name">
          <el-input v-model="configForm.model" placeholder="e.g. gpt-4" />
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
        <el-form-item label="工具调用上限">
          <el-input-number v-model="configForm.max_tool_calls_per_incident" :min="1" :max="80" />
        </el-form-item>
        <el-form-item label="Prompt（遗留）">
          <el-input v-model="configForm.prompt_template" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="最终 Prompt（遗留）">
          <el-input v-model="configForm.final_prompt_template" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="configVisible = false">取消</el-button>
        <el-button type="primary" @click="saveConfig">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, nextTick, watch, onUnmounted, reactive } from 'vue'
import { useRoute } from 'vue-router'
import { aiOpsApi, type TicketPayload } from '@/api/ai_ops'
import AgentThoughtStream from '@/components/AgentThoughtStream.vue'
import {
  Refresh,
  ArrowRight,
  Warning,
  Cpu,
  Loading,
  TrendCharts,
  Setting,
  Monitor,
  CircleCheck,
} from '@element-plus/icons-vue'
import * as echarts from 'echarts'
import { ElMessage, ElMessageBox } from 'element-plus'

const route = useRoute()
const loading = ref(false)
const detailLoading = ref(false)
const incidents = ref<any[]>([])
const selectedId = ref<number | null>(null)
const currentDetail = ref<any>(null)
const chartRef = ref<HTMLElement>()
let chartInstance: echarts.ECharts | null = null

/** 排障方向 / 人工先验（随 diagnose 传给后端 operator_context） */
const userNote = ref('')

/** LangGraph / SSE */
const diagnoseLoading = ref(false)
const streamVisible = ref(false)
const streamRunId = ref('')
const streamSseUrl = ref('')
const streamKey = ref(0)

/** 工单内联审批 */
const currentTicketId = ref<string | null>(null)
const ticketDetail = ref<TicketPayload | null>(null)
const ticketLoading = ref(false)
const ticketActionLoading = ref(false)
const approveComment = ref('')

const chartDataKeys = computed(() => {
  const m =
    currentDetail.value?.chart_metrics || currentDetail.value?.report?.related_metrics || {}
  return Object.keys(m || {})
})

const analyzingMessage = computed(
  () => '同步分析进行中；或使用上方 LangGraph 获取独立工单与 SSE 轨迹。',
)

function listTimeLabel(inc: { last_received_at?: string; started_at?: string }) {
  const raw = inc.last_received_at || inc.started_at
  if (!raw) return '—'
  return new Date(raw).toLocaleString()
}

function ticketStatusTag(s: string) {
  if (s === 'approved' || s === 'executed') return 'success'
  if (s === 'rejected') return 'danger'
  if (s === 'pending_approval') return 'warning'
  return 'info'
}

const configVisible = ref(false)
const configForm = reactive({
  provider: 'openai',
  api_base: '',
  api_key: '',
  model: '',
  max_tokens: 2000,
  temperature: 0.7,
  prompt_template: '',
  final_prompt_template: '',
  enable_ai_analysis: true,
  max_agent_iterations: 12,
  max_tool_calls_per_incident: 36,
})

async function openConfig() {
  try {
    const res = (await aiOpsApi.getConfig()) as any
    Object.assign(configForm, res)
    configVisible.value = true
  } catch {
    ElMessage.error('加载配置失败')
  }
}

async function saveConfig() {
  try {
    await aiOpsApi.updateConfig(configForm)
    ElMessage.success('已保存')
    configVisible.value = false
  } catch {
    ElMessage.error('保存失败')
  }
}

async function fetchIncidents() {
  loading.value = true
  try {
    const res = (await aiOpsApi.getIncidents()) as any
    incidents.value = res.incidents || []
  } finally {
    loading.value = false
  }
}

function resetStreamState() {
  streamVisible.value = false
  streamRunId.value = ''
  streamSseUrl.value = ''
  currentTicketId.value = null
  ticketDetail.value = null
}

/** 仅刷新右侧详情与图表，不清空 SSE / 工单（供诊断完成后刷新） */
async function refreshIncidentDetail() {
  if (!selectedId.value) return
  detailLoading.value = true
  try {
    const res = (await aiOpsApi.getIncidentDetail(selectedId.value)) as any
    currentDetail.value = res
    const metrics = res.chart_metrics || res.report?.related_metrics
    if (metrics && Object.keys(metrics).length) {
      nextTick(() => renderChart(metrics))
    }
  } finally {
    detailLoading.value = false
  }
}

async function selectIncident(inc: any) {
  resetStreamState()
  selectedId.value = inc.id
  detailLoading.value = true
  currentDetail.value = null
  try {
    const res = (await aiOpsApi.getIncidentDetail(inc.id)) as any
    currentDetail.value = res
    const metrics = res.chart_metrics || res.report?.related_metrics
    if (metrics && Object.keys(metrics).length) {
      nextTick(() => renderChart(metrics))
    }
  } finally {
    detailLoading.value = false
  }
}

/** POST /api/ai_ops/diagnose/:id/，挂载 SSE */
async function startLangGraphDiagnose() {
  if (!selectedId.value) {
    ElMessage.warning('请先选择告警')
    return
  }
  diagnoseLoading.value = true
  try {
    const payload = userNote.value.trim() ? { operator_context: userNote.value.trim() } : {}
    const res = await aiOpsApi.diagnose(selectedId.value, payload)
    streamRunId.value = res.run_id
    streamSseUrl.value = res.sse_stream_url
    streamKey.value += 1
    streamVisible.value = true
    currentTicketId.value = null
    ticketDetail.value = null
    ElMessage.success('诊断任务已投递，Agent 将结合你的指引进行调查…')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || e?.message || '触发诊断失败')
  } finally {
    diagnoseLoading.value = false
  }
}

async function loadTicketDetail() {
  if (!currentTicketId.value) return
  ticketLoading.value = true
  try {
    ticketDetail.value = await aiOpsApi.getTicket(currentTicketId.value)
  } catch {
    ElMessage.error('加载工单失败')
    ticketDetail.value = null
  } finally {
    ticketLoading.value = false
  }
}

async function onStreamDone(payload: Record<string, unknown> | undefined) {
  const tid = payload?.ticket_id != null ? String(payload.ticket_id) : ''
  if (tid) {
    currentTicketId.value = tid
    await loadTicketDetail()
    await refreshIncidentDetail()
    ElMessage.success('分析完成，请在下方完成内联审批')
  } else {
    ElMessage.warning('流程结束但未返回 ticket_id，请检查 Celery / 图节点 draft_ticket')
  }
}

function onStreamError() {
  /* AgentThoughtStream 已 Message；此处可扩展埋点 */
}

async function submitTicketForApproval() {
  if (!currentTicketId.value) return
  ticketActionLoading.value = true
  try {
    ticketDetail.value = await aiOpsApi.submitTicket(currentTicketId.value)
    ElMessage.success('已提交审批')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || e?.message || '提交失败')
  } finally {
    ticketActionLoading.value = false
  }
}

async function approveTicket() {
  if (!currentTicketId.value) return
  ticketActionLoading.value = true
  try {
    ticketDetail.value = await aiOpsApi.approveTicket(currentTicketId.value, approveComment.value)
    approveComment.value = ''
    ElMessage.success('已批准')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || e?.message || '操作失败')
  } finally {
    ticketActionLoading.value = false
  }
}

/** 打回待审工单并触发新一轮 LangGraph（SSE 无缝切换） */
async function promptRejectAndRetry() {
  if (!currentTicketId.value) return
  try {
    const { value: reason } = await ElMessageBox.prompt(
      '说明问题或正确排障方向，AI 将结合反馈重新诊断并生成工单。',
      '打回工单',
      {
        confirmButtonText: '打回并重试',
        cancelButtonText: '取消',
        inputPattern: /\S+/,
        inputErrorMessage: '打回理由不能为空',
        inputType: 'textarea',
        inputPlaceholder: '例如：不要回滚代码，先查 Nginx 错误日志…',
      },
    )

    ticketActionLoading.value = true
    const res = await aiOpsApi.rejectTicket(currentTicketId.value, {
      reason: reason.trim(),
    })

    ElMessage.success('已打回，AI 正在反思并重试…')

    if (res.new_run_id && res.new_sse_stream_url) {
      streamRunId.value = res.new_run_id
      streamSseUrl.value = res.new_sse_stream_url
      streamKey.value += 1
      streamVisible.value = true
      currentTicketId.value = null
      ticketDetail.value = null
    } else {
      await refreshIncidentDetail()
    }
  } catch (err: unknown) {
    if (err !== 'cancel') {
      const e = err as { response?: { data?: { error?: string } }; message?: string }
      ElMessage.error(e?.response?.data?.error || e?.message || '操作失败')
    }
  } finally {
    ticketActionLoading.value = false
  }
}

const getStatusType = (status: string) => {
  if (status === 'analyzed') return 'success'
  if (status === 'analyzing') return 'warning'
  if (status === 'awaiting_evidence') return 'info'
  if (status === 'resolved') return 'info'
  return 'danger'
}

function renderChart(metrics: any) {
  if (!chartRef.value) return
  chartInstance?.dispose()

  chartInstance = echarts.init(chartRef.value)

  const series: any[] = []
  const legendData: string[] = []
  let xAxisData: string[] = []

  for (const [key, data] of Object.entries(metrics)) {
    if (Array.isArray(data)) {
      ;(data as any[]).forEach((seriesData: any, idx: number) => {
        const name = `${key}-${idx}`
        legendData.push(name)
        const values = seriesData.values || []
        if (idx === 0) {
          xAxisData = values.map((v: any[]) => new Date(v[0] * 1000).toLocaleTimeString())
        }
        series.push({
          name,
          type: 'line',
          data: values.map((v: any[]) => parseFloat(v[1])),
          smooth: true,
        })
      })
    }
  }

  if (series.length === 0) {
    chartInstance.setOption({
      title: { text: 'No metric data', left: 'center', top: 'center' },
    })
    return
  }

  chartInstance.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: legendData, bottom: 0 },
    grid: { left: '3%', right: '4%', bottom: '10%', containLabel: true },
    xAxis: { type: 'category', data: xAxisData },
    yAxis: { type: 'value' },
    series,
  })
}

let pollTimer: ReturnType<typeof setTimeout> | null = null
function scheduleDetailPoll() {
  if (pollTimer) clearTimeout(pollTimer)
  const id = selectedId.value
  if (!id || currentDetail.value?.status !== 'analyzing') return
  pollTimer = setTimeout(async () => {
    if (selectedId.value === id) {
      await refreshIncidentDetail()
      scheduleDetailPoll()
    }
  }, 5000)
}

watch(
  () => [selectedId.value, currentDetail.value?.status],
  () => scheduleDetailPoll(),
)

onMounted(() => {
  const q = route.query.q
  if (typeof q === 'string' && q.trim()) {
    userNote.value = q.trim()
  }
  fetchIncidents()
  window.addEventListener('resize', () => chartInstance?.resize())
})

onUnmounted(() => {
  if (pollTimer) clearTimeout(pollTimer)
  chartInstance?.dispose()
})
</script>

<style scoped>
.mono {
  font-family: var(--l5-font-mono);
  font-size: 12px;
}

.l5-aiops {
  --l5-text: #e5e5e5;
  --l5-muted: #737373;
  --l5-line: rgba(14, 165, 233, 0.15);
}

.ai-ops-container {
  display: flex;
  flex-direction: column;
  gap: 20px;
  height: calc(100vh - 120px);
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.page-title {
  font-size: 24px;
  font-weight: 800;
  color: #fafafa;
  margin: 0;
  letter-spacing: 0.02em;
}

.page-subtitle {
  font-size: 14px;
  color: #a3a3a3;
  margin: 4px 0 0;
  line-height: 1.5;
}

.back-dash {
  margin-left: 8px;
  font-size: 13px;
  color: #737373;
  text-decoration: none;
}
.back-dash:hover {
  color: #fafafa;
}

.list-card,
.detail-card {
  height: calc(100vh - 200px);
  display: flex;
  flex-direction: column;
}

.list-card :deep(.el-card__body),
.detail-card :deep(.el-card__body) {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  padding: 0;
}

.list-header {
  padding: 16px;
  font-weight: 600;
  border-bottom: 1px solid var(--l5-line);
  background: rgba(12, 12, 14, 0.85);
  color: #e5e5e5;
}

.incident-list {
  flex: 1;
  overflow-y: auto;
}

.incident-item {
  padding: 16px;
  border-bottom: 1px solid rgba(38, 38, 42, 0.9);
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 12px;
  transition: background 0.2s;
}
.incident-item:hover {
  background: rgba(14, 165, 233, 0.06);
}
.incident-item.active {
  background: rgba(16, 185, 129, 0.08);
  border-left: 3px solid #10b981;
}

.inc-info {
  flex: 1;
}
.inc-title {
  font-weight: 600;
  color: #e5e5e5;
  margin-bottom: 4px;
}
.inc-meta {
  font-size: 12px;
  color: #737373;
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.occ-badge {
  font-size: 10px;
  color: #64748b;
  margin-left: 4px;
}

.severity-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}
.severity-dot.critical {
  background: #ef4444;
  box-shadow: 0 0 4px #ef4444;
}
.severity-dot.warning {
  background: #f59e0b;
}
.severity-dot.info {
  background: #3b82f6;
}

.detail-header {
  font-weight: 600;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.detail-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 20px 24px 32px;
}

.section-langgraph {
  margin-bottom: 20px;
  padding: 16px;
  border-radius: 12px;
  background: rgba(16, 16, 18, 0.55);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(14, 165, 233, 0.2);
  box-shadow: 0 0 0 1px rgba(16, 185, 129, 0.05) inset;
}

.section-title {
  font-size: 16px;
  font-weight: 600;
  color: #fafafa;
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 0 8px;
}

.section-hint {
  font-size: 13px;
  color: #a3a3a3;
  margin: 0 0 12px;
  line-height: 1.5;
}

.context-input {
  margin-bottom: 12px;
}

.diagnose-trigger-area {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.btn-diagnose-full {
  width: 100%;
}

.btn-diagnose-icon {
  margin-right: 6px;
  vertical-align: middle;
}

.stream-meta {
  color: #737373;
  font-size: 12px;
}

.stream-wrap {
  margin-bottom: 24px;
  min-height: 420px;
  border-radius: 12px;
  overflow: hidden;
  border: 1px solid rgba(14, 165, 233, 0.18);
}

.inline-approval-card {
  margin-bottom: 28px;
  border-radius: 12px;
  border: 1px solid rgba(16, 185, 129, 0.25);
  background: rgba(12, 18, 16, 0.5);
  backdrop-filter: blur(14px);
}

.inline-approval-card :deep(.el-card__header) {
  background: rgba(10, 14, 12, 0.75);
  border-bottom: 1px solid rgba(16, 185, 129, 0.2);
}

.inline-approval-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  width: 100%;
}

.inline-approval-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  color: #34d399;
  flex: 1;
  min-width: 0;
}

.inline-ticket-id {
  font-weight: 400;
  color: #737373;
  font-size: 12px;
}

.inline-approval-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  flex-wrap: wrap;
}

.pending-body {
  margin-top: 8px;
}

.ticket-desc {
  margin-bottom: 16px;
  background: rgba(8, 8, 10, 0.6);
}

.ticket-pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
  line-height: 1.45;
  max-height: 200px;
  overflow: auto;
}
.ticket-pre.note {
  color: #38bdf8;
  background: rgba(14, 165, 233, 0.08);
  padding: 8px;
  border-radius: 6px;
}

.approval-row {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.approval-tip {
  font-size: 12px;
  color: #737373;
}

.approval-comment {
  max-width: 560px;
}

.approval-btns {
  display: flex;
  gap: 12px;
}

.legacy-blocks .section-block {
  margin-bottom: 20px;
}

.text-content {
  font-size: 14px;
  color: #d4d4d4;
  line-height: 1.6;
}

.json-box {
  background: #1e293b;
  color: #e2e8f0;
  padding: 12px;
  border-radius: 8px;
  font-size: 12px;
  max-height: 200px;
  overflow: auto;
}

.trace-box {
  margin-bottom: 20px;
  padding: 16px;
  background: rgba(16, 16, 18, 0.5);
  border: 1px solid rgba(14, 165, 233, 0.15);
  border-radius: 12px;
}
.trace-json {
  margin: 0;
  padding: 12px;
  background: #1e293b;
  color: #e2e8f0;
  border-radius: 8px;
  font-size: 11px;
  max-height: 320px;
  overflow: auto;
  white-space: pre-wrap;
}

.ai-report-box {
  background: rgba(12, 20, 28, 0.45);
  border: 1px solid rgba(14, 165, 233, 0.22);
  border-radius: 12px;
  padding: 20px;
  margin-bottom: 20px;
}

.report-header {
  font-size: 16px;
  font-weight: 700;
  color: #0ea5e9;
  margin-bottom: 16px;
  display: flex;
  align-items: center;
  gap: 8px;
  border-bottom: 1px solid rgba(14, 165, 233, 0.2);
  padding-bottom: 12px;
}

.analysis-section {
  margin-bottom: 16px;
}
.analysis-section .label {
  font-size: 12px;
  font-weight: 700;
  color: #38bdf8;
  text-transform: uppercase;
  margin-bottom: 6px;
}
.analysis-section p {
  margin: 0;
  color: #d4d4d4;
  line-height: 1.6;
}

.root-cause {
  font-weight: 600;
  color: #be185d !important;
}

.analysis-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-bottom: 16px;
}

.analysis-card {
  background: rgba(8, 10, 12, 0.55);
  padding: 12px;
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.06);
}
.analysis-card .label {
  font-size: 11px;
  font-weight: 700;
  margin-bottom: 4px;
  text-transform: uppercase;
}
.analysis-card.mitigation .label {
  color: #d97706;
}
.analysis-card.prevention .label {
  color: #059669;
}

.solutions .label {
  font-size: 12px;
  font-weight: 700;
  color: #a3a3a3;
  margin-bottom: 8px;
  text-transform: uppercase;
}

.cmd-list {
  background: #0f172a;
  border-radius: 8px;
  overflow: hidden;
}
.cmd-item {
  padding: 10px 16px;
  border-bottom: 1px solid #1e293b;
  font-family: Menlo, Monaco, monospace;
  font-size: 13px;
  color: #a5f3fc;
}
.cmd-item:last-child {
  border-bottom: none;
}

.metrics-chart {
  height: 280px;
  width: 100%;
  border: 1px solid rgba(14, 165, 233, 0.15);
  border-radius: 8px;
  padding: 8px;
}

.analyzing-state {
  text-align: center;
  padding: 32px;
  color: #737373;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}
.analyzing-state .el-icon {
  font-size: 28px;
  color: #0ea5e9;
}

.no-report {
  color: #737373;
  font-size: 14px;
  padding: 16px;
  text-align: center;
}

.empty-detail {
  height: 360px;
}
</style>
