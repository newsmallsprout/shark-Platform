<!-- 简洁线框球体装饰（参考大屏拓扑球），纯 SVG、无 Three.js -->
<template>
  <svg class="globe" viewBox="0 0 240 240" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
    <defs>
      <linearGradient id="globe-arc" x1="0%" y1="0%" x2="100%" y2="100%">
        <stop offset="0%" stop-color="#5eead4" stop-opacity="0.55" />
        <stop offset="100%" stop-color="#0e7490" stop-opacity="0.25" />
      </linearGradient>
    </defs>
    <circle cx="120" cy="120" r="88" stroke="url(#globe-arc)" stroke-width="0.75" opacity="0.9" />
    <ellipse cx="120" cy="120" rx="88" ry="32" stroke="currentColor" stroke-width="0.6" opacity="0.35" />
    <ellipse cx="120" cy="120" rx="32" ry="88" stroke="currentColor" stroke-width="0.6" opacity="0.35" />
    <ellipse cx="120" cy="120" rx="72" ry="88" stroke="currentColor" stroke-width="0.5" opacity="0.22" transform="rotate(-28 120 120)" />
    <ellipse cx="120" cy="120" rx="72" ry="88" stroke="currentColor" stroke-width="0.5" opacity="0.22" transform="rotate(28 120 120)" />
    <circle v-for="(p, i) in nodes" :key="i" :cx="p.x" :cy="p.y" r="3.5" class="globe-node" />
  </svg>
</template>

<script setup lang="ts">
const nodes = [
  { x: 120, y: 38 },
  { x: 188, y: 78 },
  { x: 200, y: 148 },
  { x: 132, y: 198 },
  { x: 52, y: 162 },
  { x: 48, y: 88 },
  { x: 158, y: 118 },
  { x: 86, y: 124 },
]
</script>

<style scoped>
.globe {
  width: 100%;
  max-width: 220px;
  height: auto;
  color: var(--tech-cyan, #2dd4bf);
  opacity: 0.85;
  filter: drop-shadow(0 0 12px rgba(45, 212, 191, 0.15));
}

.globe-node {
  fill: var(--tech-gold, #fcd34d);
  opacity: 0.75;
}
</style>
