<template>
  <div class="l5-platform-root">
    <header class="l5-header glass-border">
      <div class="logo">
        L5 AIOps <span>Platform</span>
      </div>
      <div class="status-indicator">
        <span class="dot pulse" aria-hidden="true" />
        Grid Online
      </div>
    </header>
    <main class="l5-main-canvas">
      <router-view />
    </main>
  </div>
</template>

<script setup lang="ts"></script>

<style scoped>
.l5-platform-root {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
}

.l5-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 32px;
  background: rgba(10, 10, 10, 0.72);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border-bottom: 1px solid rgba(14, 165, 233, 0.22);
}

.glass-border {
  box-shadow: 0 0 0 1px rgba(16, 185, 129, 0.08) inset;
}

.logo {
  font-size: 20px;
  font-weight: 800;
  letter-spacing: 0.08em;
  color: #fafafa;
  font-family: 'JetBrains Mono', 'SF Mono', ui-monospace, monospace;
}

.logo span {
  color: #0ea5e9;
}

.status-indicator {
  display: flex;
  align-items: center;
  font-size: 13px;
  color: #a3a3a3;
  letter-spacing: 0.04em;
}

.dot.pulse {
  display: inline-block;
  width: 8px;
  height: 8px;
  margin-right: 10px;
  background: #10b981;
  border-radius: 50%;
  box-shadow: 0 0 12px #10b981, 0 0 24px rgba(16, 185, 129, 0.35);
  animation: blink 2.2s ease-in-out infinite;
}

@keyframes blink {
  50% {
    opacity: 0.35;
    transform: scale(0.92);
  }
}

.l5-main-canvas {
  flex: 1;
  padding: 24px 28px 40px;
  min-height: 0;
}
</style>
