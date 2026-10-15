<script setup lang="ts">
/**
 * 可折叠的侧栏卡片。
 * - rail：整个侧栏处于收起状态，渲染为窄条上的竖排标签
 * - 否则渲染为标题栏 + 可纵向展开的内容区
 */
defineProps<{
  title: string
  rail: boolean
  active?: boolean // 显示脉冲点，表示仍在进行中
  badge?: string // 简短的数量信息，如 "3/6"
}>()

const open = defineModel<boolean>('open', { required: true })
</script>

<template>
  <section class="cpanel panel" :class="{ open, rail }">
    <button
      v-if="rail"
      class="rail-tab"
      :title="`展开${title}`"
      aria-expanded="false"
      @click="open = true"
    >
      <span v-if="active" class="pulse" />
      <span class="rail-label">{{ title }}</span>
      <span v-if="badge" class="badge-count">{{ badge }}</span>
    </button>

    <template v-else>
      <button class="header" :aria-expanded="open" @click="open = !open">
        <svg class="chevron" viewBox="0 0 16 16" aria-hidden="true">
          <path
            d="M6 3.5 10.5 8 6 12.5"
            fill="none"
            stroke="currentColor"
            stroke-width="1.6"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
        <span class="title">{{ title }}</span>
        <span v-if="active" class="pulse" />
        <span v-if="badge" class="badge-count">{{ badge }}</span>
      </button>
      <div class="body">
        <div class="inner"><slot /></div>
      </div>
    </template>
  </section>
</template>

<style scoped>
.cpanel {
  overflow: hidden;
  flex-shrink: 0;
}

/* ---- 展开态：标题栏 + 内容区 ---- */
.header {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 12px 14px;
  border: none;
  background: transparent;
  color: var(--text);
  font-size: 15px;
  font-weight: 600;
  text-align: left;
}
.header:hover {
  background: var(--accent-soft);
}
.chevron {
  flex-shrink: 0;
  width: 14px;
  height: 14px;
  color: var(--muted);
  transition: transform 0.2s ease;
}
.open .chevron {
  transform: rotate(90deg);
}
.header .badge-count {
  margin-left: auto;
}
.body {
  display: grid;
  grid-template-rows: 0fr;
  transition: grid-template-rows 0.25s ease;
}
.open .body {
  grid-template-rows: 1fr;
  border-top: 1px solid var(--border);
}
.inner {
  min-height: 0;
  overflow: hidden;
}

/* ---- 收起态：竖排标签 ---- */
.rail-tab {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 14px 0;
  border: none;
  background: transparent;
  color: var(--text);
}
.rail-tab:hover {
  background: var(--accent-soft);
}
.rail-label {
  writing-mode: vertical-rl;
  letter-spacing: 3px;
  font-size: 13px;
  font-weight: 600;
}

.badge-count {
  padding: 0 6px;
  border-radius: 999px;
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 11px;
  font-weight: 500;
  line-height: 18px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.pulse {
  flex-shrink: 0;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--accent);
  animation: pulse 1.2s ease-in-out infinite;
}
@keyframes pulse {
  50% {
    opacity: 0.25;
  }
}

/* 窄屏单列布局下，竖排标签改为横排 */
@media (max-width: 1100px) {
  .rail-tab {
    flex-direction: row;
    justify-content: flex-start;
    padding: 12px 14px;
  }
  .rail-label {
    writing-mode: horizontal-tb;
    letter-spacing: normal;
    font-size: 15px;
  }
}
</style>
