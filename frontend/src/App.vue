<template>
  <div class="aiops-root">
    <header class="aiops-header">
      <div class="brand">
        <router-link to="/" class="brand-link">AIOps Platform</router-link>
        <span class="brand-tag">L4</span>
      </div>
      <nav class="nav-links">
        <router-link to="/" class="nav-item">概览</router-link>
        <router-link to="/console" class="nav-item">运维台</router-link>
      </nav>
      <div class="header-right">
        <button type="button" class="kbd-hint" @click="openPalette">
          <span>命令面板</span>
          <kbd>{{ modKey }}K</kbd>
        </button>
      </div>
    </header>

    <div class="aiops-body">
      <main class="aiops-main">
        <router-view />
      </main>

      <aside class="aiops-assistant" aria-label="AI 运维助理">
        <p class="assistant-title">运维助理</p>
        <div class="assistant-lamp">
          <span class="dot" :class="sidebarLamp" />
          <span>{{ sidebarStatusText }}</span>
        </div>
        <div class="assistant-stream">
          <p v-if="assistantThinking" class="thinking typing">Thinking…</p>
          <p v-else class="assistant-idle muted">
            在运维台启动 LangGraph 诊断后，此处同步显示分析态；SSE 流式事件在页面内展开。
          </p>
        </div>
      </aside>
    </div>

    <teleport to="body">
      <div v-if="paletteOpen" class="palette-backdrop" @click.self="paletteOpen = false">
        <div class="palette-dialog glass-panel" role="dialog" aria-modal="true" aria-label="命令面板">
          <input
            ref="paletteInputRef"
            v-model="paletteQuery"
            class="palette-input"
            type="text"
            placeholder="自然语言查询状态、跳转…"
            @keydown.esc="paletteOpen = false"
            @keydown.enter="runPaletteCommand"
          />
          <p class="palette-hint muted">
            回车：跳转运维台并带上查询参数（与后续日志检索管道对接）。
          </p>
        </div>
      </div>
    </teleport>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { aiAssistantThinking } from '@/stores/aiAssistant'
import { aiOpsApi } from '@/api/ai_ops'

const router = useRouter()
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
  if (assistantThinking.value) return 'dot-analyze'
  if (dashAiStatus.value === 'analyzing') return 'dot-analyze'
  if (dashAiStatus.value === 'degraded') return 'dot-bad'
  return 'dot-ok'
})

const sidebarStatusText = computed(() => {
  if (assistantThinking.value) return '推理流进行中'
  if (dashAiStatus.value === 'analyzing') return '后台事件分析中'
  if (dashAiStatus.value === 'degraded') return '存在高风险开放事件'
  return '待机'
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
    if (paletteOpen.value) {
      void nextTick(() => paletteInputRef.value?.focus())
    }
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
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background: #000000;
  color: #e5e5e5;
}

.aiops-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 24px;
  border-bottom: 1px solid #333333;
  background: rgba(10, 10, 10, 0.72);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
}

.brand-link {
  font-size: 15px;
  font-weight: 600;
  letter-spacing: -0.02em;
  color: #fafafa;
  text-decoration: none;
}

.brand-link:hover {
  color: #ffffff;
}

.brand-tag {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.12em;
  color: #888888;
  border: 1px solid #333333;
  border-radius: 4px;
  padding: 2px 6px;
}

.nav-links {
  display: flex;
  gap: 8px;
}

.nav-item {
  font-size: 13px;
  color: #888888;
  text-decoration: none;
  padding: 6px 12px;
  border-radius: 6px;
}

.nav-item:hover {
  color: #fafafa;
  background: rgba(255, 255, 255, 0.04);
}

.router-link-active.nav-item {
  color: #fafafa;
  background: rgba(255, 255, 255, 0.06);
}

.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.kbd-hint {
  display: flex;
  align-items: center;
  gap: 8px;
  background: transparent;
  border: 1px solid #333333;
  color: #a3a3a3;
  font-size: 12px;
  padding: 6px 12px;
  border-radius: 8px;
  cursor: pointer;
}

.kbd-hint:hover {
  border-color: #525252;
  color: #fafafa;
}

.kbd-hint kbd {
  font-family: var(--aiops-font-mono);
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 4px;
  background: #141414;
  border: 1px solid #333333;
  color: #888888;
}

.aiops-body {
  display: flex;
  flex: 1;
  min-height: 0;
}

.aiops-main {
  flex: 1;
  min-width: 0;
  padding: 24px 28px 48px;
}

.aiops-assistant {
  width: 280px;
  flex-shrink: 0;
  border-left: 1px solid #333333;
  padding: 20px 18px;
  background: rgba(10, 10, 10, 0.5);
  backdrop-filter: blur(12px);
}

@media (max-width: 900px) {
  .aiops-assistant {
    display: none;
  }
}

.assistant-title {
  margin: 0 0 12px;
  font-size: 11px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: #888888;
}

.assistant-lamp {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: #d4d4d4;
  margin-bottom: 16px;
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.dot-ok {
  background: #22c55e;
  opacity: 0.5;
  box-shadow: 0 0 8px rgba(34, 197, 94, 0.4);
}

.dot-analyze {
  background: #38bdf8;
  animation: shimmer 2s ease-in-out infinite;
}

.dot-bad {
  background: #ef4444;
  box-shadow: 0 0 10px rgba(239, 68, 68, 0.5);
}

@keyframes shimmer {
  0%,
  100% {
    opacity: 0.35;
  }
  50% {
    opacity: 1;
  }
}

.assistant-stream {
  font-size: 13px;
  line-height: 1.55;
}

.thinking {
  margin: 0;
  color: #a3a3a3;
  font-family: var(--aiops-font-mono);
}

.typing {
  overflow: hidden;
  border-right: 2px solid #525252;
  white-space: nowrap;
  animation:
    cursor-blink 1s step-end infinite,
    typing 2.4s steps(12, end) infinite;
}

@keyframes cursor-blink {
  50% {
    border-color: transparent;
  }
}

@keyframes typing {
  0% {
    width: 0;
  }
  40%,
  100% {
    width: 100%;
  }
}

.assistant-idle {
  margin: 0;
}

.muted {
  color: #888888;
}

.palette-backdrop {
  position: fixed;
  inset: 0;
  z-index: 2000;
  background: rgba(0, 0, 0, 0.55);
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding-top: 15vh;
}

.palette-dialog {
  width: min(520px, 92vw);
  padding: 20px;
  border-radius: 12px;
  border: 1px solid #333333;
  background: rgba(12, 12, 12, 0.92);
  backdrop-filter: blur(20px);
}

.palette-input {
  width: 100%;
  box-sizing: border-box;
  background: #0a0a0a;
  border: 1px solid #333333;
  border-radius: 8px;
  color: #fafafa;
  font-size: 15px;
  padding: 12px 14px;
  outline: none;
}

.palette-input:focus {
  border-color: #525252;
}

.palette-hint {
  margin: 12px 0 0;
  font-size: 12px;
  line-height: 1.5;
}
</style>
