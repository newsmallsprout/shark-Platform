<template>
  <div class="empty-state" :class="{ 'is-compact': compact }" role="status">
    <div class="empty-frame" aria-hidden="true">
      <!-- 细线几何占位，禁止 EP 默认 3D 盒子 -->
      <svg class="empty-svg" viewBox="0 0 72 72" fill="none" xmlns="http://www.w3.org/2000/svg">
        <rect
          x="14"
          y="18"
          width="44"
          height="38"
          rx="3"
          stroke="currentColor"
          stroke-width="1"
          class="empty-stroke"
        />
        <path d="M22 30h28M22 38h20M22 46h24" stroke="currentColor" stroke-width="1" class="empty-lines" />
        <circle cx="36" cy="12" r="3" stroke="currentColor" stroke-width="1" class="empty-dot-ring" />
      </svg>
    </div>
    <p class="empty-title">{{ title }}</p>
    <p v-if="hint" class="empty-hint">{{ hint }}</p>
  </div>
</template>

<script setup lang="ts">
withDefaults(
  defineProps<{
    title: string
    hint?: string
    /** 侧栏等窄区域 */
    compact?: boolean
  }>(),
  { hint: '', compact: false },
)
</script>

<style scoped>
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 32px 20px;
  min-height: 200px;
  color: var(--aiops-text-tertiary);
}

.empty-state.is-compact {
  padding: 24px 16px;
  min-height: 140px;
}

.empty-frame {
  margin-bottom: 20px;
}

.empty-state.is-compact .empty-frame {
  margin-bottom: 14px;
}

.empty-svg {
  width: 72px;
  height: 72px;
  color: var(--aiops-text-tertiary);
  opacity: 0.85;
}

.empty-stroke {
  opacity: 0.45;
}

.empty-lines {
  opacity: 0.28;
}

.empty-dot-ring {
  opacity: 0.35;
}

.empty-state.is-compact .empty-svg {
  width: 56px;
  height: 56px;
}

.empty-title {
  margin: 0;
  font-size: 13px;
  font-weight: 500;
  letter-spacing: 0.02em;
  color: var(--aiops-text-secondary);
  max-width: 280px;
  line-height: 1.5;
}

.empty-state.is-compact .empty-title {
  font-size: 12px;
  max-width: 220px;
}

.empty-hint {
  margin: 8px 0 0;
  font-size: 12px;
  color: var(--aiops-text-tertiary);
  max-width: 320px;
  line-height: 1.45;
}
</style>
