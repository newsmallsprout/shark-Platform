<!--
  AgentThoughtStream — AI 诊断过程白盒化时间线
  依赖后端 SSE：监听 event: agent，载荷为 { type, payload, seq, ts, ... }
-->
<script setup lang="ts">
import { ref, watch, onUnmounted, nextTick, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { Loading, CircleCheck, WarningFilled, Connection } from '@element-plus/icons-vue'

/** SSE 单条信封（与后端 redis_stream / sse_server 一致） */
interface StreamEnvelope {
  run_id?: string
  incident_id?: number | null
  seq?: number
  ts?: number
  type: string
  payload?: Record<string, unknown>
}

/** 单次工具调用 UI 状态 */
interface ToolRun {
  callId: string
  toolName: string
  args: Record<string, unknown>
  loading: boolean
  observation?: unknown
  error?: string | null
  ok?: boolean
}

/** 时间线上的一个「宏观步骤」（对应 graph_node） */
interface TimelineStep {
  id: string
  nodeKey: string
  deltaKeys: string[]
  ts: number
  seq: number
  tools: ToolRun[]
}

const props = withDefaults(
  defineProps<{
    /** 运行实例 ID（展示用，可与 URL 校验） */
    runId: string
    /** 完整 SSE URL，如 http://host:8010/api/agent/stream/{run_id} */
    sseStreamUrl: string
    /** 最大自动重连次数 */
    maxReconnectAttempts?: number
    /** 是否自动连接（默认 true） */
    autoConnect?: boolean
    /** 为 true 时不展示内置 el-result，由父组件在 @done 后做内联审批等 */
    hideCompletionResult?: boolean
  }>(),
  {
    maxReconnectAttempts: 8,
    autoConnect: true,
    hideCompletionResult: false,
  },
)

const emit = defineEmits<{
  (e: 'done', payload: Record<string, unknown> | undefined): void
  (e: 'error', detail: unknown): void
  (e: 'connected'): void
  (e: 'closed'): void
}>()

const scrollerRef = ref<HTMLElement | null>(null)
const steps = ref<TimelineStep[]>([])
const connectionState = ref<'idle' | 'connecting' | 'open' | 'closed' | 'error'>('idle')
const doneState = ref<{ visible: boolean; ticketId?: string }>({ visible: false })
const globalError = ref<string | null>(null)
const reconnectCount = ref(0)
const lastSeq = ref(0)

let eventSource: EventSource | null = null
let reconnectTimer: ReturnType<typeof setTimeout> | null = null

const isStreaming = computed(
  () => connectionState.value === 'connecting' || connectionState.value === 'open',
)

function genStepId(seq: number) {
  return `step-${seq}-${Date.now()}`
}

/** 将 JSON 格式化为可读字符串 */
function formatJson(data: unknown): string {
  try {
    return JSON.stringify(data, null, 2)
  } catch {
    return String(data)
  }
}

/** 滚动到底部 */
async function scrollToBottom() {
  await nextTick()
  const el = scrollerRef.value
  if (!el) return
  el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
}

/** 在最后一个时间线步骤上挂工具；若无步骤则先插入占位步骤 */
function ensureLastStepForTool(seq: number): TimelineStep {
  const label = '智能体执行'
  if (steps.value.length === 0) {
    const s: TimelineStep = {
      id: genStepId(seq),
      nodeKey: label,
      deltaKeys: [],
      ts: Date.now() / 1000,
      seq,
      tools: [],
    }
    steps.value.push(s)
    return s
  }
  return steps.value[steps.value.length - 1]!
}

function onGraphNode(seq: number, payload: Record<string, unknown>) {
  const node = String(payload.node ?? 'unknown')
  const deltaKeys = Array.isArray(payload.delta_keys) ? (payload.delta_keys as string[]) : []
  steps.value.push({
    id: genStepId(seq),
    nodeKey: node,
    deltaKeys,
    ts: Date.now() / 1000,
    seq,
    tools: [],
  })
  void scrollToBottom()
}

function onToolStart(seq: number, payload: Record<string, unknown>) {
  const callId = String(payload.call_id ?? `orphan-${seq}`)
  const toolName = String(payload.tool_name ?? 'unknown_tool')
  const args = (payload.arguments as Record<string, unknown>) ?? {}
  const step = ensureLastStepForTool(seq)
  step.tools.push({
    callId,
    toolName,
    args,
    loading: true,
  })
  void scrollToBottom()
}

function onToolEnd(payload: Record<string, unknown>) {
  const callId = String(payload.call_id ?? '')
  const toolName = String(payload.tool_name ?? '')
  for (let i = steps.value.length - 1; i >= 0; i--) {
    const t = steps.value[i]!.tools.find(
      (x) => x.callId === callId || (!callId && x.toolName === toolName && x.loading),
    )
    if (t) {
      t.loading = false
      t.ok = payload.ok !== false
      t.error = (payload.error as string) || null
      t.observation = payload.observation
      break
    }
  }
  void scrollToBottom()
}

function onStreamDone(payload: Record<string, unknown> | undefined) {
  if (!props.hideCompletionResult) {
    doneState.value = {
      visible: true,
      ticketId: payload?.ticket_id != null ? String(payload.ticket_id) : undefined,
    }
  }
  closeStream()
  emit('done', payload)
  void scrollToBottom()
}

function onStreamErrorMessage(payload: Record<string, unknown>) {
  const msg =
    (payload.message as string) ||
    (payload.detail as string) ||
    (payload.phase as string) ||
    '未知错误'
  globalError.value = msg
  emit('error', payload)
  ElMessage.error(msg)
  void scrollToBottom()
}

function handleEnvelope(env: StreamEnvelope) {
  if (typeof env.seq === 'number' && env.seq > lastSeq.value) {
    lastSeq.value = env.seq
  }
  const p = env.payload ?? {}
  switch (env.type) {
    case 'run_start':
      globalError.value = null
      break
    case 'operator_context': {
      const text = String((p as Record<string, unknown>).text ?? '')
      onGraphNode(env.seq ?? lastSeq.value, {
        node: '运维排障指引',
        delta_keys: [text.slice(0, 800)],
      })
      break
    }
    case 'human_feedback': {
      const text = String((p as Record<string, unknown>).text ?? '')
      onGraphNode(env.seq ?? lastSeq.value, {
        node: '收到人类反馈',
        delta_keys: [text.slice(0, 800)],
      })
      break
    }
    case 'graph_node':
      onGraphNode(env.seq ?? lastSeq.value, p)
      break
    case 'tool_start':
      onToolStart(env.seq ?? lastSeq.value, p)
      break
    case 'tool_end':
      onToolEnd(p)
      break
    case 'thought_delta':
      // 可选：后续接入 LLM 流式 token
      break
    case 'done':
      onStreamDone(p)
      break
    case 'error':
      onStreamErrorMessage(p)
      break
    default:
      break
  }
}

function parseAgentData(raw: string) {
  try {
    const env = JSON.parse(raw) as StreamEnvelope
    if (env && typeof env.type === 'string') {
      handleEnvelope(env)
    }
  } catch {
    /* 非 JSON 忽略 */
  }
}

function clearReconnectTimer() {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
}

function closeStream() {
  clearReconnectTimer()
  if (eventSource) {
    eventSource.close()
    eventSource = null
  }
  if (connectionState.value === 'open' || connectionState.value === 'connecting') {
    connectionState.value = 'closed'
  }
  emit('closed')
}

function scheduleReconnect() {
  if (doneState.value.visible) return
  if (reconnectCount.value >= props.maxReconnectAttempts) {
    connectionState.value = 'error'
    globalError.value = `已重试 ${props.maxReconnectAttempts} 次，请检查网络或刷新页面`
    return
  }
  const delay = Math.min(30000, 1000 * Math.pow(2, reconnectCount.value))
  reconnectCount.value += 1
  clearReconnectTimer()
  reconnectTimer = setTimeout(() => {
    openStream()
  }, delay)
}

function openStream() {
  if (!props.sseStreamUrl || !props.runId) {
    ElMessage.warning('缺少 sseStreamUrl 或 runId')
    return
  }
  closeStream()
  connectionState.value = 'connecting'
  globalError.value = null

  try {
    eventSource = new EventSource(props.sseStreamUrl)
  } catch (e) {
    connectionState.value = 'error'
    globalError.value = '无法创建 EventSource'
    emit('error', e)
    return
  }

  eventSource.addEventListener('open', () => {
    connectionState.value = 'open'
    reconnectCount.value = 0
    emit('connected')
  })

  eventSource.addEventListener('ready', () => {
    /* 握手帧，可扩展 */
  })

  eventSource.addEventListener('agent', (ev: MessageEvent) => {
    if (typeof ev.data === 'string') {
      parseAgentData(ev.data)
    }
  })

  eventSource.addEventListener('heartbeat', () => {
    /* 保活 */
  })

  eventSource.onerror = () => {
    if (eventSource?.readyState === EventSource.CLOSED) {
      connectionState.value = 'closed'
      if (!doneState.value.visible) {
        scheduleReconnect()
      }
    } else {
      connectionState.value = 'error'
    }
  }
}

function manualReconnect() {
  reconnectCount.value = 0
  openStream()
}

/** 收起完成横幅（done 事件已在收到 done 包时向父组件抛出过一次） */
function dismissDoneBanner() {
  doneState.value = { visible: false, ticketId: doneState.value.ticketId }
}

function resetView() {
  steps.value = []
  doneState.value = { visible: false }
  globalError.value = null
  lastSeq.value = 0
  reconnectCount.value = 0
}

watch(
  () => [props.runId, props.sseStreamUrl] as const,
  () => {
    resetView()
    if (props.autoConnect && props.sseStreamUrl && props.runId) {
      openStream()
    }
  },
  { immediate: true },
)

watch(
  steps,
  () => {
    void scrollToBottom()
  },
  { deep: true },
)

onUnmounted(() => {
  closeStream()
})

/** 节点展示标题 */
function stepTitle(step: TimelineStep) {
  const map: Record<string, string> = {
    investigate: '调查取证',
    diagnose: '诊断归纳',
    draft_ticket: '生成智能工单',
  }
  return map[step.nodeKey] ?? step.nodeKey
}

defineExpose({
  openStream,
  closeStream,
  resetView,
})
</script>

<template>
  <div class="agent-thought-stream">
    <!-- 顶栏状态条 -->
    <div class="stream-header">
      <div class="stream-header__left">
        <el-icon class="stream-header__pulse" :class="{ 'is-live': isStreaming }">
          <Connection />
        </el-icon>
        <span class="stream-header__title">Agent 思维流</span>
        <el-tag
          :type="connectionState === 'open' ? 'success' : connectionState === 'error' ? 'danger' : 'info'"
          size="small"
          effect="dark"
          class="stream-header__tag"
        >
          {{
            connectionState === 'idle'
              ? '未连接'
              : connectionState === 'connecting'
                ? '连接中'
                : connectionState === 'open'
                  ? 'LIVE'
                  : connectionState === 'error'
                    ? '异常'
                    : '已断开'
          }}
        </el-tag>
        <span v-if="runId" class="stream-header__runid mono">run_id · {{ runId.slice(0, 8) }}…</span>
      </div>
      <div class="stream-header__actions">
        <el-button size="small" text type="primary" :disabled="isStreaming" @click="manualReconnect">
          重新连接
        </el-button>
        <el-button size="small" text @click="closeStream">停止</el-button>
      </div>
    </div>

    <!-- 全局错误 -->
    <el-alert
      v-if="globalError"
      type="error"
      :closable="true"
      show-icon
      class="stream-alert"
      @close="globalError = null"
    >
      <template #title>流式通道异常</template>
      {{ globalError }}
    </el-alert>

    <!-- 主滚动区 -->
    <div ref="scrollerRef" class="stream-scroller">
      <div v-if="!steps.length && !doneState.visible" class="stream-empty">
        <el-icon class="stream-empty__icon"><Loading /></el-icon>
        <p>等待智能体推送事件…</p>
        <p class="stream-empty__hint mono">{{ sseStreamUrl }}</p>
      </div>

      <el-timeline v-else class="thought-timeline">
        <el-timeline-item
          v-for="step in steps"
          :key="step.id"
          :timestamp="new Date(step.ts * 1000).toLocaleTimeString()"
          placement="top"
          :icon="CircleCheck"
          :color="'#22d3ee'"
          class="thought-timeline__item"
        >
          <div class="step-card">
            <div class="step-card__head">
              <span class="step-card__label">{{ stepTitle(step) }}</span>
              <el-tag v-if="step.deltaKeys.length" size="small" type="info" effect="plain" class="mono">
                {{ step.deltaKeys.join(', ') }}
              </el-tag>
            </div>

            <div v-if="step.tools.length" class="step-card__tools">
              <el-collapse accordion class="tool-collapse">
                <el-collapse-item
                  v-for="tool in step.tools"
                  :key="tool.callId"
                  :name="tool.callId"
                >
                  <template #title>
                    <div class="tool-title">
                      <el-icon v-if="tool.loading" class="tool-title__spin"><Loading /></el-icon>
                      <el-icon v-else-if="tool.ok === false" class="tool-title__warn" color="#f56c6c">
                        <WarningFilled />
                      </el-icon>
                      <el-icon v-else class="tool-title__ok" color="#67c23a">
                        <CircleCheck />
                      </el-icon>
                      <span class="tool-title__name mono">{{ tool.toolName }}</span>
                      <el-tag v-if="tool.loading" size="small" type="warning" effect="dark">执行中</el-tag>
                    </div>
                  </template>

                  <div class="tool-body">
                    <div class="tool-section">
                      <div class="tool-section__label">参数</div>
                      <pre class="tool-json mono"><code>{{ formatJson(tool.args) }}</code></pre>
                    </div>
                    <div v-if="!tool.loading && (tool.observation != null || tool.error)" class="tool-section">
                      <div class="tool-section__label">Observation</div>
                      <el-alert v-if="tool.error" type="error" :title="tool.error" show-icon class="tool-err" />
                      <pre v-else class="tool-json mono tool-json--obs"><code>{{ formatJson(tool.observation) }}</code></pre>
                    </div>
                  </div>
                </el-collapse-item>
              </el-collapse>
            </div>
          </div>
        </el-timeline-item>
      </el-timeline>

      <!-- 完成态 -->
      <div v-if="doneState.visible && !hideCompletionResult" class="stream-done">
        <el-result icon="success" title="分析完成" sub-title="请前往智能工单台查看详情并完成审批。">
          <template #extra>
            <p v-if="doneState.ticketId" class="mono done-ticket">
              ticket_id: {{ doneState.ticketId }}
            </p>
            <el-button type="primary" @click="dismissDoneBanner">知道了</el-button>
          </template>
        </el-result>
      </div>
    </div>
  </div>
</template>

<style scoped>
.mono {
  font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
  font-size: 12px;
}

.agent-thought-stream {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 360px;
  border-radius: 12px;
  border: 1px solid rgba(56, 189, 248, 0.25);
  background: linear-gradient(145deg, rgba(15, 23, 42, 0.96) 0%, rgba(15, 23, 42, 0.88) 100%);
  box-shadow:
    0 0 0 1px rgba(34, 211, 238, 0.08),
    0 12px 40px rgba(0, 0, 0, 0.35);
  overflow: hidden;
}

.stream-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.15);
  background: rgba(15, 23, 42, 0.6);
  backdrop-filter: blur(8px);
}

.stream-header__left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.stream-header__title {
  font-weight: 600;
  font-size: 15px;
  letter-spacing: 0.02em;
  color: #e2e8f0;
}

.stream-header__runid {
  color: #64748b;
  margin-left: 4px;
}

.stream-header__pulse {
  font-size: 20px;
  color: #64748b;
  transition: color 0.3s;
}

.stream-header__pulse.is-live {
  color: #22d3ee;
  animation: pulse-glow 1.8s ease-in-out infinite;
}

@keyframes pulse-glow {
  0%,
  100% {
    filter: drop-shadow(0 0 2px rgba(34, 211, 238, 0.4));
  }
  50% {
    filter: drop-shadow(0 0 8px rgba(34, 211, 238, 0.85));
  }
}

.stream-alert {
  margin: 8px 12px 0;
  border-radius: 8px;
}

.stream-scroller {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px 24px;
  scroll-behavior: smooth;
}

.stream-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 200px;
  color: #94a3b8;
  text-align: center;
}

.stream-empty__icon {
  font-size: 32px;
  margin-bottom: 12px;
  animation: spin 1.2s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.stream-empty__hint {
  margin-top: 8px;
  font-size: 11px;
  color: #475569;
  word-break: break-all;
  max-width: 100%;
}

.thought-timeline {
  padding-left: 4px;
}

.thought-timeline :deep(.el-timeline-item__timestamp) {
  color: #64748b;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
}

.thought-timeline :deep(.el-timeline-item__node) {
  background: linear-gradient(180deg, #22d3ee, #0ea5e9);
  box-shadow: 0 0 12px rgba(34, 211, 238, 0.45);
}

.thought-timeline__item {
  padding-bottom: 8px;
}

.step-card {
  border-radius: 10px;
  border: 1px solid rgba(51, 65, 85, 0.6);
  background: rgba(30, 41, 59, 0.55);
  padding: 12px 14px;
  margin-bottom: 4px;
}

.step-card__head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}

.step-card__label {
  font-size: 15px;
  font-weight: 600;
  color: #f1f5f9;
  letter-spacing: 0.03em;
}

.tool-collapse {
  --el-collapse-border-color: transparent;
  background: transparent;
}

.tool-collapse :deep(.el-collapse-item__header) {
  background: rgba(15, 23, 42, 0.5);
  border-radius: 8px;
  padding: 8px 12px;
  border: 1px solid rgba(71, 85, 105, 0.5);
  color: #cbd5e1;
}

.tool-collapse :deep(.el-collapse-item__wrap) {
  border: none;
  background: transparent;
}

.tool-collapse :deep(.el-collapse-item__content) {
  padding: 12px 0 4px;
}

.tool-title {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
}

.tool-title__spin {
  animation: spin 1s linear infinite;
}

.tool-title__name {
  flex: 1;
  color: #e2e8f0;
}

.tool-body {
  padding: 0 4px;
}

.tool-section {
  margin-bottom: 12px;
}

.tool-section__label {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: #64748b;
  margin-bottom: 6px;
}

.tool-json {
  margin: 0;
  padding: 12px;
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.9);
  border: 1px solid rgba(51, 65, 85, 0.8);
  color: #a5f3fc;
  font-size: 11px;
  line-height: 1.45;
  overflow-x: auto;
  max-height: 280px;
}

.tool-json--obs {
  color: #86efac;
}

.tool-err {
  margin-bottom: 0;
}

.stream-done {
  margin-top: 20px;
  padding: 16px;
  border-radius: 12px;
  background: rgba(22, 101, 52, 0.12);
  border: 1px solid rgba(74, 222, 128, 0.25);
}

.stream-done :deep(.el-result__title) {
  color: #ecfccb;
}

.stream-done :deep(.el-result__subtitle) {
  color: #a3e635;
}

.done-ticket {
  color: #bef264;
  margin-bottom: 12px;
}
</style>
