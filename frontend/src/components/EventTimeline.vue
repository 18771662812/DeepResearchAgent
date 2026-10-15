<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import type { AgentEvent } from '../types'

const props = defineProps<{ events: AgentEvent[]; running: boolean }>()

interface Item {
  kind: 'divider' | 'line'
  agent?: string | null
  tag?: string
  text: string
  detail?: string
  tone?: 'error' | 'muted'
}

const PHASE_TEXT: Record<string, string> = {
  planning: '规划',
  researching: '研究',
  reflecting: '反思',
  writing: '撰写报告',
}

function describe(e: AgentEvent): Item | null {
  const d = e.data
  switch (e.type) {
    case 'step':
      // 多 Agent 模式下各 Researcher 的轮次交错出现，不再画分隔线
      return e.agent ? null : { kind: 'divider', text: `第 ${d.step} 轮` }
    case 'phase':
      return {
        kind: 'divider',
        text: PHASE_TEXT[d.phase] + (d.round && d.phase === 'researching' ? ` · 第 ${d.round} 轮` : ''),
      }
    case 'plan':
      return { kind: 'line', tag: '规划', text: `拆解为 ${d.sub_questions.length} 个子问题` }
    case 'researcher_start':
      return { kind: 'line', tag: '开始', text: d.question }
    case 'researcher_done':
      return d.ok
        ? {
            kind: 'line',
            tag: '笔记',
            text: `提交研究笔记 ${d.note_chars} 字（原始资料 ${d.raw_chars} 字）`,
          }
        : { kind: 'line', tag: '失败', text: d.error, tone: 'error' }
    case 'reflection':
      return {
        kind: 'line',
        tag: '反思',
        text: d.sufficient
          ? '信息已充分'
          : `发现 ${d.gaps.length} 个缺口，补充 ${d.follow_up_questions.length} 个子问题`,
        detail: d.gaps.length ? d.gaps.join('\n') : undefined,
      }
    case 'status':
      return { kind: 'line', tag: '状态', text: d.message, tone: 'muted' }
    case 'thought':
      return { kind: 'line', tag: '思考', text: d.content }
    case 'tool_call':
      if (d.name === 'web_search') return { kind: 'line', tag: '搜索', text: d.args?.query ?? '' }
      if (d.name === 'fetch_url') return { kind: 'line', tag: '阅读', text: d.args?.url ?? '' }
      return { kind: 'line', tag: d.name, text: JSON.stringify(d.args) }
    case 'tool_result':
      return {
        kind: 'line',
        tag: '结果',
        text: `${d.name} 返回 ${d.length} 字`,
        detail: d.preview,
        tone: 'muted',
      }
    case 'report':
      return { kind: 'line', tag: '完成', text: `报告已生成，引用 ${d.sources.length} 个来源` }
    case 'usage': {
      let text = `LLM 调用 ${d.calls} 次 · 输入 ${d.prompt_tokens} · 输出 ${d.completion_tokens} · 缓存命中 ${d.cache_hit_tokens} tokens`
      if (d.context?.notes_chars) {
        text += ` · 上下文压缩 ${d.context.raw_chars} → ${d.context.notes_chars} 字`
      }
      return { kind: 'line', tag: '用量', text, tone: 'muted' }
    }
    case 'error':
      return { kind: 'line', tag: '错误', text: d.message, tone: 'error' }
    default:
      return null
  }
}

const items = computed<Item[]>(() =>
  props.events.flatMap((e) => {
    const item = describe(e)
    return item ? [{ ...item, agent: e.agent }] : []
  }),
)

const listEl = ref<HTMLElement | null>(null)
watch(
  () => props.events.length,
  async () => {
    await nextTick()
    listEl.value?.scrollTo({ top: listEl.value.scrollHeight, behavior: 'smooth' })
  },
)
</script>

<template>
  <section class="timeline panel">
    <div class="title">
      研究过程
      <span v-if="running" class="pulse" />
    </div>
    <ol ref="listEl" class="list">
      <li v-for="(item, i) in items" :key="i" :class="[item.kind, item.tone]">
        <template v-if="item.kind === 'divider'">{{ item.text }}</template>
        <template v-else>
          <span v-if="item.agent" class="agent">{{ item.agent }}</span>
          <span class="tag">{{ item.tag }}</span>
          <div class="body">
            <div class="text">{{ item.text }}</div>
            <details v-if="item.detail">
              <summary>预览</summary>
              <pre>{{ item.detail }}</pre>
            </details>
          </div>
        </template>
      </li>
    </ol>
  </section>
</template>

<style scoped>
.timeline {
  display: flex;
  flex-direction: column;
  min-height: 0;
  max-height: 70vh;
}
.title {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
  font-weight: 600;
}
.pulse {
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
.list {
  list-style: none;
  margin: 0;
  padding: 8px 16px 16px;
  overflow-y: auto;
  font-size: 13px;
}
.divider {
  margin: 12px 0 6px;
  color: var(--muted);
  font-size: 12px;
  border-bottom: 1px dashed var(--border);
}
.line {
  display: flex;
  gap: 8px;
  padding: 4px 0;
}
.agent {
  flex-shrink: 0;
  padding: 0 5px;
  border-radius: 4px;
  background: var(--code-bg);
  color: var(--muted);
  font-size: 12px;
  line-height: 20px;
  height: 20px;
  font-variant-numeric: tabular-nums;
}
.tag {
  flex-shrink: 0;
  padding: 0 6px;
  border-radius: 4px;
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 12px;
  line-height: 20px;
  height: 20px;
}
.body {
  min-width: 0;
  flex: 1;
}
.text {
  word-break: break-all;
  white-space: pre-wrap;
}
.muted .text {
  color: var(--muted);
}
.error .tag {
  background: transparent;
  color: var(--danger);
}
.error .text {
  color: var(--danger);
}
details summary {
  color: var(--muted);
  cursor: pointer;
  font-size: 12px;
}
pre {
  margin: 4px 0 0;
  padding: 8px;
  border-radius: 6px;
  background: var(--code-bg);
  white-space: pre-wrap;
  word-break: break-all;
  font-size: 12px;
}
</style>
