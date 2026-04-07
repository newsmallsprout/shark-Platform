<template>
  <div class="bento-page">
    <div class="bento-grid">
      <section class="bento-cell bento-span-4 glass-panel hero-metrics">
        <p class="eyebrow">全局健康</p>
        <div class="health-row">
          <span class="health-score">{{ dash?.health_score ?? '—' }}</span>
          <span class="health-unit">/ 100</span>
        </div>
        <p class="muted small">开放事件 {{ dash?.open_incidents ?? 0 }} · 经验库条目 {{ dash?.knowledge_entries ?? 0 }}</p>
        <p v-if="deployHint" class="muted small deploy-hint">{{ deployHint }}</p>
      </section>

      <section class="bento-cell bento-span-4 glass-panel">
        <p class="eyebrow">AI 巡检</p>
        <div class="lamp-row">
          <span class="lamp" :class="lampClass" aria-hidden="true" />
          <div>
            <p class="lamp-label">{{ lampLabel }}</p>
            <p class="muted small">感知 → 拓扑 → 经验库 → 因果 → 工单 / 自愈</p>
          </div>
        </div>
      </section>

      <section class="bento-cell bento-span-4 glass-panel">
        <p class="eyebrow">自愈阈值</p>
        <p class="mono threshold">
          AutoHeal ≥ {{ (dash?.auto_heal_threshold ?? 0.95).toFixed(2) }}
        </p>
        <p class="muted small">匹配置信度达标时生成已批准工单并下发边缘 Playbook。</p>
      </section>

      <section class="bento-cell bento-span-12 glass-panel topo-panel">
        <div class="topo-head">
          <p class="eyebrow">动态拓扑</p>
          <router-link class="link-console" to="/console">进入运维台 →</router-link>
        </div>
        <div v-if="layoutNodes.length" class="topo-stage">
          <svg class="topo-svg" :viewBox="`0 0 ${svgW} ${svgH}`" preserveAspectRatio="xMidYMid meet">
            <defs>
              <filter id="glow-red" x="-50%" y="-50%" width="200%" height="200%">
                <feGaussianBlur stdDeviation="3" result="b" />
                <feMerge>
                  <feMergeNode in="b" />
                  <feMergeNode in="SourceGraphic" />
                </feMerge>
              </filter>
            </defs>
            <line
              v-for="(e, i) in dash?.topology?.edges ?? []"
              :key="`e-${i}`"
              :x1="nodePos(e.from)?.x ?? 0"
              :y1="nodePos(e.from)?.y ?? 0"
              :x2="nodePos(e.to)?.x ?? 0"
              :y2="nodePos(e.to)?.y ?? 0"
              class="topo-edge"
            />
            <g
              v-for="n in layoutNodes"
              :key="n.id"
              :transform="`translate(${n.x}, ${n.y})`"
            >
              <circle
                r="22"
                :class="['topo-node', n.healthy === false ? 'bad' : 'ok']"
                :filter="n.healthy === false ? 'url(#glow-red)' : undefined"
              />
              <text y="4" text-anchor="middle" class="topo-label">{{ truncate(n.label, 10) }}</text>
            </g>
          </svg>
        </div>
        <div v-else class="empty-topo muted">
          <span class="empty-icon">◇</span>
          <p>暂无拓扑快照；接入 Prometheus Webhook 并触发诊断后将自动推导 Service Map。</p>
        </div>
      </section>

      <section class="bento-cell bento-span-6 glass-panel list-panel">
        <p class="eyebrow">待审批工单</p>
        <ul v-if="(dash?.pending_tickets?.length ?? 0) > 0" class="mini-list">
          <li v-for="t in dash!.pending_tickets" :key="t.ticket_id" class="mini-item">
            <span class="mono id">{{ t.ticket_id.slice(0, 8) }}…</span>
            <span class="txt">{{ t.summary }}</span>
            <span class="pill">{{ t.routing || 'human' }}</span>
          </li>
        </ul>
        <div v-else class="empty-list muted">
          <span class="empty-icon">—</span>
          <p>无待审项</p>
        </div>
      </section>

      <section class="bento-cell bento-span-6 glass-panel list-panel">
        <p class="eyebrow">近期自愈 / 执行</p>
        <ul v-if="(dash?.recent_heals?.length ?? 0) > 0" class="mini-list">
          <li v-for="h in dash!.recent_heals" :key="h.ticket_id" class="mini-item">
            <span class="mono id">{{ h.ticket_id.slice(0, 8) }}…</span>
            <span class="txt">{{ h.summary }}</span>
            <span class="muted tiny">{{ h.executed_at || '—' }}</span>
          </li>
        </ul>
        <div v-else class="empty-list muted">
          <span class="empty-icon">—</span>
          <p>尚无闭环记录</p>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { aiOpsApi, type DashboardSummary, type TopoNode } from '@/api/ai_ops'

const dash = ref<DashboardSummary | null>(null)
let poll: ReturnType<typeof setInterval> | null = null

const lampClass = computed(() => {
  const s = dash.value?.ai_status
  if (s === 'analyzing') return 'lamp-analyze'
  if (s === 'degraded') return 'lamp-bad'
  return 'lamp-ok'
})

const lampLabel = computed(() => {
  const s = dash.value?.ai_status
  if (s === 'analyzing') return '分析中 · 图节点流式推送中'
  if (s === 'degraded') return '异常域 · 存在 Critical 级开放事件'
  return '正常 · 后台静默巡检'
})

const deployHint = computed(() => {
  const d = dash.value?.deployment
  if (!d) return ''
  const modeLabel: Record<string, string> = {
    kubernetes: 'K8s 中心部署',
    hybrid: '混合（K8s + 物理/边缘）',
    physical: '物理机 / VM 为主',
    unspecified: '未声明部署模式',
  }
  const m = modeLabel[d.mode] || d.mode
  const bits: string[] = [m]
  if (d.center_in_kubernetes_pod) bits.push('运行在 Pod 内')
  if (d.cluster_data_via_api) bits.push('集群侧建议走 API / Prometheus 取数')
  if (d.edge_heartbeat_expected) bits.push('边缘探针用于集群外或 Playbook 执行点')
  return bits.join(' · ')
})

const svgW = 720
const svgH = 220

const layoutNodes = computed(() => {
  const nodes = dash.value?.topology?.nodes ?? []
  const n = nodes.length || 0
  if (!n) return [] as Array<TopoNode & { x: number; y: number }>
  const pad = 56
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
  for (const n of layoutNodes.value) {
    m.set(n.id, { x: n.x, y: n.y })
  }
  return m
})

function nodePos(id: string) {
  return posMap.value.get(id)
}

function truncate(s: string, max: number) {
  if (!s) return ''
  return s.length <= max ? s : `${s.slice(0, max - 1)}…`
}

async function load() {
  try {
    dash.value = await aiOpsApi.getDashboard()
  } catch {
    dash.value = null
  }
}

onMounted(() => {
  void load()
  poll = setInterval(() => void load(), 15000)
})

onUnmounted(() => {
  if (poll) clearInterval(poll)
})
</script>

<style scoped>
.bento-page {
  max-width: 1200px;
  margin: 0 auto;
}

.bento-grid {
  display: grid;
  grid-template-columns: repeat(12, 1fr);
  gap: 16px;
}

.bento-cell {
  min-height: 0;
}

.bento-span-4 {
  grid-column: span 4;
}
.bento-span-6 {
  grid-column: span 6;
}
.bento-span-12 {
  grid-column: span 12;
}

@media (max-width: 960px) {
  .bento-span-4,
  .bento-span-6 {
    grid-column: span 12;
  }
}

.glass-panel {
  background: rgba(12, 12, 12, 0.55);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid #333333;
  border-radius: 12px;
  padding: 20px 22px;
  box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.03) inset;
}

.eyebrow {
  font-size: 11px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: #888888;
  margin: 0 0 12px;
}

.health-row {
  display: flex;
  align-items: baseline;
  gap: 6px;
}

.health-score {
  font-size: 42px;
  font-weight: 600;
  letter-spacing: -0.03em;
  color: #fafafa;
  font-feature-settings: 'tnum';
}

.health-unit {
  font-size: 14px;
  color: #888888;
}

.muted {
  color: #888888;
}
.small {
  font-size: 12px;
  margin: 10px 0 0;
  line-height: 1.5;
}

.deploy-hint {
  margin-top: 8px;
  max-width: 42em;
}
.tiny {
  font-size: 11px;
}

.lamp-row {
  display: flex;
  align-items: center;
  gap: 14px;
}

.lamp {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  flex-shrink: 0;
}

.lamp-ok {
  background: #14532d;
  box-shadow: 0 0 10px rgba(34, 197, 94, 0.35);
  opacity: 0.85;
}

.lamp-analyze {
  background: #38bdf8;
  animation: breathe 2.4s ease-in-out infinite;
  box-shadow: 0 0 16px rgba(56, 189, 248, 0.55);
}

.lamp-bad {
  background: #dc2626;
  box-shadow: 0 0 14px rgba(220, 38, 38, 0.65);
  animation: pulse-red 1.8s ease-in-out infinite;
}

@keyframes breathe {
  0%,
  100% {
    opacity: 0.45;
    transform: scale(0.92);
  }
  50% {
    opacity: 1;
    transform: scale(1.05);
  }
}

@keyframes pulse-red {
  50% {
    opacity: 0.55;
  }
}

.lamp-label {
  margin: 0;
  font-size: 15px;
  color: #e5e5e5;
}

.threshold {
  margin: 0;
  font-size: 20px;
  color: #fafafa;
}

.topo-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.link-console {
  font-size: 13px;
  color: #a3a3a3;
  text-decoration: none;
}
.link-console:hover {
  color: #fafafa;
}

.topo-stage {
  width: 100%;
  min-height: 200px;
  border-radius: 8px;
  border: 1px solid #262626;
  background: #050505;
}

.topo-svg {
  width: 100%;
  height: 200px;
  display: block;
}

.topo-edge {
  stroke: #333333;
  stroke-width: 1;
}

.topo-node.ok {
  fill: #171717;
  stroke: #404040;
  stroke-width: 1;
}

.topo-node.bad {
  fill: #450a0a;
  stroke: #dc2626;
  stroke-width: 1.5;
}

.topo-label {
  fill: #a3a3a3;
  font-size: 9px;
  font-family: var(--aiops-font-mono);
  pointer-events: none;
}

.empty-topo,
.empty-list {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  min-height: 160px;
  padding: 24px;
  font-size: 13px;
  line-height: 1.6;
}

.empty-icon {
  font-size: 22px;
  color: #525252;
  margin-bottom: 8px;
}

.mini-list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.mini-item {
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: 10px;
  align-items: baseline;
  padding: 10px 0;
  border-bottom: 1px solid #1f1f1f;
  font-size: 13px;
}

.mini-item:last-child {
  border-bottom: none;
}

.mini-item .id {
  color: #737373;
  font-size: 11px;
}

.mini-item .txt {
  color: #d4d4d4;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pill {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: #888888;
  border: 1px solid #333333;
  border-radius: 999px;
  padding: 2px 8px;
}

.list-panel {
  min-height: 220px;
}
</style>
