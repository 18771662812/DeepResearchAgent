<script setup lang="ts">
import { ref } from 'vue'

defineProps<{ disabled?: boolean }>()
const emit = defineEmits<{ submit: [query: string] }>()

const query = ref('')
const examples = [
  'MCP 协议是什么？目前有哪些主流实现和应用场景？',
  '对比 Rust 和 Go 在后端开发中的优劣',
  '国产大模型在 Agent 方向的最新进展',
]

function submit() {
  const q = query.value.trim()
  if (q.length < 2) return
  emit('submit', q)
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
        <button class="submit" :disabled="disabled || query.trim().length < 2" @click="submit">
          开始研究
        </button>
      </div>
    </div>
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
  justify-content: flex-end;
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
