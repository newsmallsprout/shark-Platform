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
        <el-card shadow="never" class="list-card aiops-surface-card">
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
            <EmptyState
              v-if="!incidents.length"
              compact
              title="暂无告警"
              hint="接入 Prometheus Webhook 后，告警将出现在此列表。"
            />
          </div>
        </el-card>
      </el-col>

      <el-col :span="16">
        <el-card v-if="selectedId" shadow="never" class="detail-card aiops-surface-card">
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
                    <span v-if="Number(ticketDetail.ai_confidence) === 0" class="confidence-hint">
                      （未命中经验库或被动诊断草案时常为 0，不代表接口故障）
                    </span>
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
          </div>
        </el-card>
        <el-card v-else shadow="never" class="detail-card detail-placeholder aiops-surface-card">
          <EmptyState
            title="请选择一个告警"
            hint="在左侧选取一条告警，启动异步诊断并在本页完成工单审批。"
          />
        </el-card>
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
import { ref, onMounted, watch, onUnmounted, reactive } from 'vue'
import { useRoute } from 'vue-router'
import { aiOpsApi, type TicketPayload } from '@/api/ai_ops'
import AgentThoughtStream from '@/components/AgentThoughtStream.vue'
import EmptyState from '@/components/EmptyState.vue'
import { Refresh, ArrowRight, Cpu, Setting, CircleCheck } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'

const route = useRoute()
const loading = ref(false)
const detailLoading = ref(false)
const incidents = ref<any[]>([])
const selectedId = ref<number | null>(null)
const currentDetail = ref<any>(null)

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
    ElMessage.warning('流程结束但未返回 ticket_id，请检查 Celery Worker 与后端日志')
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
})

onUnmounted(() => {
  if (pollTimer) clearTimeout(pollTimer)
})
</script>

<style scoped>
.mono {
  font-family: var(--aiops-font-mono);
  font-size: 12px;
}

.l5-aiops {
  --line: var(--aiops-border);
}

.ai-ops-container {
  display: flex;
  flex-direction: column;
  gap: 22px;
  min-height: calc(100dvh - 120px);
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
}

.page-title {
  font-size: 1.375rem;
  font-weight: 600;
  color: var(--aiops-text);
  margin: 0;
  letter-spacing: -0.03em;
}

.page-subtitle {
  font-size: 14px;
  color: var(--aiops-text-tertiary);
  margin: 8px 0 0;
  line-height: 1.55;
  max-width: 52ch;
}

.back-dash {
  margin-left: 8px;
  font-size: 13px;
  font-weight: 500;
  color: var(--aiops-text-secondary);
  text-decoration: none;
}
.back-dash:hover {
  color: var(--aiops-text);
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
  padding: 14px 16px;
  font-weight: 600;
  font-size: 13px;
  border-bottom: 1px solid var(--line);
  background: var(--aiops-bg-elevated);
  color: var(--aiops-text-secondary);
}

.incident-list {
  flex: 1;
  overflow-y: auto;
}

.incident-item {
  padding: 14px 16px;
  border-bottom: 1px solid var(--aiops-border);
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 12px;
  transition: background 0.2s cubic-bezier(0.16, 1, 0.3, 1);
}
.incident-item:hover {
  background: rgba(255, 255, 255, 0.03);
}
.incident-item.active {
  background: var(--aiops-accent-live-dim);
  border-left: 2px solid var(--aiops-accent-live);
}

.inc-info {
  flex: 1;
}
.inc-title {
  font-weight: 600;
  color: var(--aiops-text);
  margin-bottom: 4px;
}
.inc-meta {
  font-size: 12px;
  color: var(--aiops-text-tertiary);
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
  background: var(--aiops-danger);
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
  padding: 18px;
  border-radius: 12px;
  background: var(--aiops-surface-2);
  border: 1px solid var(--aiops-border);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
}

.section-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--aiops-text);
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 0 8px;
}

.section-hint {
  font-size: 13px;
  color: var(--aiops-text-tertiary);
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
  color: var(--aiops-text-tertiary);
  font-size: 12px;
}

.stream-wrap {
  margin-bottom: 24px;
  min-height: 420px;
  border-radius: 12px;
  overflow: hidden;
  border: 1px solid var(--aiops-border);
}

.inline-approval-card {
  margin-bottom: 28px;
  border-radius: 12px;
  border: 1px solid var(--aiops-border-strong);
  background: var(--aiops-bg-elevated);
}

.inline-approval-card :deep(.el-card__header) {
  background: var(--aiops-surface-2);
  border-bottom: 1px solid var(--aiops-border);
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
  color: var(--aiops-text);
  flex: 1;
  min-width: 0;
}

.inline-ticket-id {
  font-weight: 400;
  color: var(--aiops-text-tertiary);
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
  background: var(--aiops-bg);
}

.confidence-hint {
  display: inline-block;
  margin-left: 8px;
  font-size: 12px;
  color: var(--aiops-text-secondary);
  font-weight: normal;
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
  color: var(--aiops-text-secondary);
  background: rgba(255, 255, 255, 0.04);
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
  color: var(--aiops-text-tertiary);
}

.approval-comment {
  max-width: 560px;
}

.approval-btns {
  display: flex;
  gap: 12px;
}

.empty-detail {
  height: 360px;
}
</style>
