<template>
  <div class="aiops-root">
    <div class="aiops-ambient" aria-hidden="true" />
    <header class="aiops-header">
      <div class="header-left">
        <router-link to="/" class="brand-mark" aria-label="AIOps Platform home">
          <span class="brand-dot" />
          <span class="brand-text">AIOps</span>
        </router-link>
        <span class="brand-divider" />
        <span class="brand-sub">Platform</span>
      </div>
      <nav class="nav-rail" aria-label="Main">
        <router-link to="/" class="nav-pill">概览</router-link>
        <router-link to="/console" class="nav-pill">运维台</router-link>
      </nav>
      <div class="header-actions">
        <button type="button" class="cmd-trigger" @click="openPalette">
          <span class="cmd-label">命令</span>
          <kbd class="cmd-kbd">{{ modKey }}K</kbd>
        </button>
      </div>
    </header>

    <div class="aiops-body">
      <aside v-if="showSidenav" class="app-sidenav" aria-label="主导航">
        <div class="sidenav-top">
          <span class="sidenav-logo-dot" aria-hidden="true" />
          <div class="sidenav-brand-block">
            <span class="sidenav-name">Shark Platform</span>
            <span class="sidenav-tag">AIOps</span>
          </div>
        </div>
        <p class="sidenav-section">工作台</p>
        <router-link to="/" class="sidenav-link" active-class="is-active">运营数据大屏</router-link>
        <router-link to="/console" class="sidenav-link" active-class="is-active">运维台</router-link>
        <p class="sidenav-section">说明</p>
        <p class="sidenav-hint">大屏聚合运行态势、部署形态与 24h 趋势；工单审批在运维台完成。</p>
      </aside>

      <main class="aiops-main">
        <router-view />
      </main>

      <aside class="aiops-rail" aria-label="Context">
        <p class="rail-label">状态</p>
        <div class="rail-status">
          <span class="status-dot" :class="sidebarLamp" />
          <span class="status-text">{{ sidebarStatusText }}</span>
        </div>
        <div class="rail-body">
          <p v-if="assistantThinking" class="rail-thinking">Thinking</p>
          <p v-else class="rail-copy">
            在运维台发起诊断后，SSE 事件在页面内展示；此处仅指示全局分析态。
          </p>
        </div>
      </aside>
    </div>

    <teleport to="body">
      <div v-if="paletteOpen" class="palette-scrim" @click.self="paletteOpen = false">
        <div class="palette-sheet" role="dialog" aria-modal="true" aria-label="命令面板">
          <input
            ref="paletteInputRef"
            v-model="paletteQuery"
            class="palette-field"
            type="text"
            placeholder="查询或跳转运维台…"
            @keydown.esc="paletteOpen = false"
            @keydown.enter="runPaletteCommand"
          />
          <p class="palette-note">Enter 确认 · Esc 关闭</p>
        </div>
      </div>
    </teleport>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { aiAssistantThinking } from '@/stores/aiAssistant'
import { useSystemStore } from '@/stores/system'
import { aiOpsApi } from '@/api/ai_ops'

const router = useRouter()
const systemStore = useSystemStore()
const showSidenav = computed(() => Boolean(systemStore.currentUser))
const paletteOpen = ref(false)
const paletteQuery = ref('')
const paletteInputRef = ref<HTMLInputElement | null>(null)

const modKey = computed(() => (navigator.platform.toLowerCase().includes('mac') ? '⌘' : 'Ctrl+'))

const assistantThinking = computed(() => aiAssistantThinking.value)
const dashAiStatus = ref<'idle' | 'analyzing' | 'degraded' | null>(null)
let dashPoll: ReturnType<typeof setInterval> | null = null

async function refreshDashStatus() {
  try {
    const d = await aiOpsApi.getDashboard()
    dashAiStatus.value = d.ai_status
  } catch {
    dashAiStatus.value = null
  }
}

const sidebarLamp = computed(() => {
  if (assistantThinking.value) return 'is-live'
  if (dashAiStatus.value === 'analyzing') return 'is-live'
  if (dashAiStatus.value === 'degraded') return 'is-warn'
  return 'is-idle'
})

const sidebarStatusText = computed(() => {
  if (assistantThinking.value) return '推理流'
  if (dashAiStatus.value === 'analyzing') return '分析中'
  if (dashAiStatus.value === 'degraded') return '风险开放事件'
  return '就绪'
})

function openPalette() {
  paletteOpen.value = true
  paletteQuery.value = ''
  void nextTick(() => paletteInputRef.value?.focus())
}

function onKeyDown(e: KeyboardEvent) {
  if ((e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'K')) {
    e.preventDefault()
    paletteOpen.value = !paletteOpen.value
    if (paletteOpen.value) void nextTick(() => paletteInputRef.value?.focus())
  }
}

function runPaletteCommand() {
  const q = paletteQuery.value.trim()
  paletteOpen.value = false
  router.push({ path: '/console', query: q ? { q } : {} })
}

watch(paletteOpen, (v) => {
  if (v) void nextTick(() => paletteInputRef.value?.focus())
})

onMounted(() => {
  window.addEventListener('keydown', onKeyDown)
  void refreshDashStatus()
  dashPoll = setInterval(() => void refreshDashStatus(), 20000)
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKeyDown)
  if (dashPoll) clearInterval(dashPoll)
})
</script>

<style scoped>
.aiops-root {
  min-height: 100dvh;
  display: flex;
  flex-direction: column;
  position: relative;
  background: transparent;
  color: var(--aiops-text);
}

.aiops-ambient {
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: 0;
  background:
    radial-gradient(ellipse 55% 40% at 20% 0%, rgba(45, 212, 191, 0.07), transparent 50%),
    radial-gradient(ellipse 45% 35% at 95% 100%, rgba(14, 165, 233, 0.06), transparent 45%);
  opacity: 1;
}

.aiops-header {
  position: relative;
  z-index: 2;
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  gap: 16px;
  padding: 0 24px;
  height: 52px;
  border-bottom: 1px solid var(--tech-cyan-border, rgba(45, 212, 191, 0.35));
  background: rgba(4, 14, 32, 0.75);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  box-shadow: 0 1px 0 rgba(45, 212, 191, 0.12);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
  justify-self: start;
}

.brand-mark {
  display: flex;
  align-items: center;
  gap: 10px;
  text-decoration: none;
  color: inherit;
}

.brand-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--tech-cyan, #2dd4bf);
  box-shadow: 0 0 10px rgba(45, 212, 191, 0.55);
  opacity: 0.95;
}

.brand-text {
  font-size: 15px;
  font-weight: 600;
  letter-spacing: -0.03em;
}

.brand-divider {
  width: 1px;
  height: 14px;
  background: var(--aiops-border-strong);
}

.brand-sub {
  font-size: 12px;
  font-weight: 500;
  color: var(--aiops-text-tertiary);
  letter-spacing: 0.02em;
}

.nav-rail {
  justify-self: center;
  display: flex;
  padding: 3px;
  gap: 2px;
  border-radius: 10px;
  background: rgba(45, 212, 191, 0.05);
  border: 1px solid var(--tech-cyan-border, rgba(45, 212, 191, 0.35));
}

.nav-pill {
  padding: 6px 14px;
  font-size: 13px;
  font-weight: 500;
  color: var(--aiops-text-tertiary);
  border-radius: 8px;
  text-decoration: none;
  transition:
    color 0.2s cubic-bezier(0.16, 1, 0.3, 1),
    background 0.2s cubic-bezier(0.16, 1, 0.3, 1);
}

.nav-pill:hover {
  color: var(--aiops-text-secondary);
}

.router-link-active.nav-pill {
  color: #021018;
  background: var(--tech-cyan, #2dd4bf);
  box-shadow: 0 0 14px rgba(45, 212, 191, 0.35);
}

.header-actions {
  justify-self: end;
}

.cmd-trigger {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px 6px 12px;
  font: inherit;
  font-size: 12px;
  font-weight: 500;
  color: var(--tech-text-secondary, #94b8cc);
  background: rgba(45, 212, 191, 0.06);
  border: 1px solid var(--tech-cyan-border, rgba(45, 212, 191, 0.35));
  border-radius: 8px;
  cursor: pointer;
  transition:
    border-color 0.2s ease,
    color 0.2s ease,
    box-shadow 0.2s ease;
}

.cmd-trigger:hover {
  border-color: var(--tech-cyan, #2dd4bf);
  color: var(--tech-cyan, #2dd4bf);
  box-shadow: 0 0 12px rgba(45, 212, 191, 0.2);
}

.cmd-trigger:active {
  transform: scale(0.98);
}

.cmd-label {
  letter-spacing: 0.04em;
}

.cmd-kbd {
  font-family: var(--aiops-font-mono);
  font-size: 10px;
  font-weight: 500;
  padding: 3px 6px;
  border-radius: 4px;
  background: var(--aiops-bg-elevated);
  border: 1px solid var(--aiops-border);
  color: var(--aiops-text-tertiary);
}

.aiops-body {
  position: relative;
  z-index: 1;
  flex: 1;
  display: flex;
  min-height: 0;
}

.app-sidenav {
  width: 220px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 20px 14px 24px;
  border-right: 1px solid var(--tech-cyan-border, rgba(45, 212, 191, 0.28));
  background: rgba(4, 18, 40, 0.82);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
}

.sidenav-top {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 20px;
  padding-bottom: 16px;
  border-bottom: 1px solid rgba(45, 212, 191, 0.12);
}

.sidenav-logo-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--tech-cyan, #2dd4bf);
  box-shadow: 0 0 12px rgba(45, 212, 191, 0.5);
  flex-shrink: 0;
}

.sidenav-brand-block {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.sidenav-name {
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: var(--tech-text, #e8f4ff);
}

.sidenav-tag {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--tech-text-muted, #6b8aa0);
}

.sidenav-section {
  margin: 16px 0 8px;
  padding: 0 8px;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--tech-text-muted, #6b8aa0);
}

.sidenav-section:first-of-type {
  margin-top: 0;
}

.sidenav-link {
  display: block;
  padding: 10px 12px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  color: var(--tech-text-secondary, #94b8cc);
  text-decoration: none;
  border: 1px solid transparent;
  transition:
    background 0.2s ease,
    color 0.2s ease,
    border-color 0.2s ease;
}

.sidenav-link:hover {
  color: var(--tech-cyan, #2dd4bf);
  background: rgba(45, 212, 191, 0.06);
}

.sidenav-link.is-active {
  color: #021018;
  background: var(--tech-cyan, #2dd4bf);
  border-color: rgba(45, 212, 191, 0.5);
  box-shadow: 0 0 16px rgba(45, 212, 191, 0.25);
}

.sidenav-hint {
  margin: 0;
  padding: 0 8px;
  font-size: 11px;
  line-height: 1.5;
  color: var(--tech-text-muted, #6b8aa0);
}

.aiops-main {
  flex: 1;
  min-width: 0;
  padding: 28px 32px 56px;
  max-width: 1600px;
  margin: 0 auto;
  width: 100%;
}

.aiops-rail {
  width: 260px;
  flex-shrink: 0;
  border-left: 1px solid var(--tech-cyan-border, rgba(45, 212, 191, 0.28));
  padding: 24px 20px;
  background: rgba(4, 16, 36, 0.55);
  backdrop-filter: blur(12px);
}

@media (min-width: 901px) {
  .nav-rail {
    display: none;
  }
}

@media (max-width: 900px) {
  .app-sidenav {
    display: none;
  }

  .aiops-rail {
    display: none;
  }
  .aiops-header {
    grid-template-columns: 1fr auto;
  }
  .nav-rail {
    display: flex;
    justify-self: end;
  }
  .header-actions {
    display: none;
  }
}

.rail-label {
  margin: 0 0 12px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--aiops-text-tertiary);
}

.rail-status {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 20px;
}

.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}

.status-dot.is-idle {
  background: var(--aiops-text-tertiary);
  opacity: 0.5;
}

.status-dot.is-live {
  background: var(--tech-gold, #fcd34d);
  box-shadow: 0 0 10px rgba(252, 211, 77, 0.45);
  animation: pulse-soft 2s ease-in-out infinite;
}

.status-dot.is-warn {
  background: var(--aiops-danger);
}

@keyframes pulse-soft {
  0%,
  100% {
    opacity: 0.55;
    transform: scale(1);
  }
  50% {
    opacity: 1;
    transform: scale(1.15);
  }
}

.status-text {
  font-size: 13px;
  font-weight: 500;
  color: var(--aiops-text-secondary);
}

.rail-body {
  font-size: 13px;
  line-height: 1.55;
  color: var(--aiops-text-tertiary);
}

.rail-thinking {
  margin: 0;
  font-family: var(--aiops-font-mono);
  font-size: 12px;
  color: var(--aiops-text-secondary);
  letter-spacing: 0.06em;
}

.rail-thinking::after {
  content: '…';
  animation: dots 1.2s steps(4, end) infinite;
}

@keyframes dots {
  0%,
  20% {
    content: '';
  }
  40% {
    content: '.';
  }
  60% {
    content: '..';
  }
  80%,
  100% {
    content: '...';
  }
}

.rail-copy {
  margin: 0;
}

.palette-scrim {
  position: fixed;
  inset: 0;
  z-index: 2000;
  background: rgba(9, 9, 11, 0.65);
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding-top: min(18vh, 160px);
  backdrop-filter: blur(6px);
}

.palette-sheet {
  width: min(480px, 92vw);
  padding: 20px 22px 18px;
  border-radius: 12px;
  border: 1px solid var(--tech-cyan-border, rgba(45, 212, 191, 0.4));
  background: var(--tech-panel-solid, #0a1628);
  box-shadow:
    0 0 28px rgba(45, 212, 191, 0.15),
    0 24px 64px rgba(0, 0, 0, 0.55),
    inset 0 1px 0 rgba(255, 255, 255, 0.05);
}

.palette-field {
  width: 100%;
  box-sizing: border-box;
  padding: 12px 14px;
  font-size: 15px;
  font-family: inherit;
  color: var(--aiops-text);
  background: var(--aiops-bg);
  border: 1px solid var(--aiops-border);
  border-radius: 10px;
  outline: none;
  transition: border-color 0.2s cubic-bezier(0.16, 1, 0.3, 1);
}

.palette-field:focus {
  border-color: var(--tech-cyan, #2dd4bf);
  box-shadow: 0 0 12px rgba(45, 212, 191, 0.2);
}

.palette-note {
  margin: 10px 0 0;
  font-size: 11px;
  color: var(--aiops-text-tertiary);
  letter-spacing: 0.02em;
}
</style>
