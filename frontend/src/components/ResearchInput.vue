<script setup lang="ts">
import { ref } from 'vue'
import type { AgentMode } from '../types'

defineProps<{ disabled?: boolean }>()
const emit = defineEmits<{ submit: [query: string, mode: AgentMode] }>()

const query = ref('')
const mode = ref<AgentMode>('multi')
const modes: { value: AgentMode; label: string; hint: string }[] = [
  { value: 'multi', label: '深度研究', hint: '拆解子问题，多个 Agent 并行调研并查漏补缺' },
  { value: 'single', label: '快速研究', hint: '单个 Agent 边搜边写，更快更省' },
]
const examples = [
  'MCP 协议是什么？目前有哪些主流实现和应用场景？',
  '对比 Rust 和 Go 在后端开发中的优劣',
  '国产大模型在 Agent 方向的最新进展',
]

function submit() {
  const q = query.value.trim()
  if (q.length < 2) return
  emit('submit', q, mode.value)
  query.value = ''
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
    e.preventDefault()
    submit()
  }
}
</script>

<template>
  <div class="research-input">
    <div class="box panel">
      <textarea
        v-model="query"
        rows="3"
        placeholder="输入你想研究的问题，Ctrl + Enter 提交"
        :disabled="disabled"
        @keydown="onKeydown"
      />
      <div class="actions">
        <div class="modes" role="radiogroup">
          <button
            v-for="m in modes"
            :key="m.value"
            class="mode"
            :class="{ active: mode === m.value }"
            :title="m.hint"
            role="radio"
            :aria-checked="mode === m.value"
            @click="mode = m.value"
          >
            {{ m.label }}
          </button>
        </div>
        <button class="submit" :disabled="disabled || query.trim().length < 2" @click="submit">
          开始研究
        </button>
      </div>
    </div>
    <p class="hint">{{ modes.find((m) => m.value === mode)?.hint }}</p>
    <div class="examples">
      <button v-for="ex in examples" :key="ex" class="example" @click="query = ex">
        {{ ex }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.research-input {
  width: 100%;
  max-width: 760px;
  margin: 0 auto;
}
.box {
  padding: 12px;
}
textarea {
  width: 100%;
  border: none;
  outline: none;
  resize: vertical;
  background: transparent;
  color: var(--text);
  font: inherit;
  font-size: 15px;
}
.actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}
.modes {
  display: inline-flex;
  padding: 2px;
  border-radius: 8px;
  background: var(--code-bg);
}
.mode {
  padding: 4px 12px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--muted);
  font-size: 13px;
}
.mode.active {
  background: var(--panel);
  color: var(--accent);
  box-shadow: 0 1px 2px rgb(0 0 0 / 0.08);
}
.submit {
  padding: 6px 18px;
  border: none;
  border-radius: 8px;
  background: var(--accent);
  color: #fff;
}
.submit:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.hint {
  margin: 8px 4px 0;
  color: var(--muted);
  font-size: 12px;
}
.examples {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}
.example {
  padding: 4px 12px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--panel);
  color: var(--muted);
  font-size: 13px;
}
.example:hover {
  color: var(--accent);
  border-color: var(--accent);
}
</style>
