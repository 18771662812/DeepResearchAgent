<script setup lang="ts">
import { computed } from 'vue'
import type { AgentEvent, Phase, SubQuestion } from '../types'

const props = defineProps<{ events: AgentEvent[]; finished: boolean }>()

type ItemStatus = 'pending' | 'running' | 'done' | 'failed'

interface PlanItem extends SubQuestion {
  status: ItemStatus
  note?: string
  error?: string
  rawChars?: number
  noteChars?: number
}

interface Reflection {
  round: number
  sufficient: boolean
  gaps: string[]
  followUps: number
}

const PHASES: { key: Phase; label: string }[] = [
  { key: 'planning', label: '规划' },
  { key: 'researching', label: '研究' },
  { key: 'reflecting', label: '反思' },
  { key: 'writing', label: '撰写' },
]

const STATUS_TEXT: Record<ItemStatus, string> = {
  pending: '等待中',
  running: '研究中',
  done: '已完成',
  failed: '失败',
}

// 由事件流推导出计划面板的状态
const state = computed(() => {
  let brief = ''
  let phase: Phase | null = null
  const items = new Map<number, PlanItem>()
  const reflections: Reflection[] = []

  for (const e of props.events) {
    const d = e.data
    switch (e.type) {
      case 'phase':
        phase = d.phase
        break
      case 'plan':
        brief = d.brief
        for (const q of d.sub_questions as SubQuestion[]) items.set(q.id, { ...q, status: 'pending' })
        break
      case 'reflection':
        reflections.push({
          round: d.round,
          sufficient: d.sufficient,
          gaps: d.gaps,
          followUps: d.follow_up_questions.length,
        })
        for (const q of d.follow_up_questions as SubQuestion[])
          items.set(q.id, { ...q, status: 'pending' })
        break
      case 'researcher_start': {
        const item = items.get(d.id)
        if (item) item.status = 'running'
        break
      }
      case 'researcher_done': {
        const item = items.get(d.id)
        if (!item) break
        item.status = d.ok ? 'done' : 'failed'
        item.note = d.note
        item.error = d.error
        item.rawChars = d.raw_chars
        item.noteChars = d.note_chars
        break
      }
    }
  }

  const rounds = new Map<number, PlanItem[]>()
  for (const item of items.values()) {
    if (!rounds.has(item.round)) rounds.set(item.round, [])
    rounds.get(item.round)!.push(item)
  }
  return { brief, phase, rounds: [...rounds.entries()], reflections }
})

function phaseState(key: Phase): 'done' | 'active' | 'todo' {
  if (props.finished) return 'done'
  const order = PHASES.map((p) => p.key)
  const current = state.value.phase ? order.indexOf(state.value.phase) : -1
  const idx = order.indexOf(key)
  if (idx < current) return 'done'
  return idx === current ? 'active' : 'todo'
}

function reflectionAfter(round: number) {
  return state.value.reflections.find((r) => r.round === round)
}
</script>

<template>
  <section class="plan">
    <ol class="phases">
      <li v-for="p in PHASES" :key="p.key" :class="phaseState(p.key)">{{ p.label }}</li>
    </ol>

    <p v-if="state.brief" class="brief">{{ state.brief }}</p>

    <template v-for="[round, items] in state.rounds" :key="round">
      <div v-if="round > 1" class="round-label">第 {{ round }} 轮 · 补充研究</div>
      <ul class="items">
        <li v-for="item in items" :key="item.id" :class="item.status">
          <div class="row">
            <span class="id">R{{ item.id }}</span>
            <span class="question">{{ item.question }}</span>
            <span class="status">{{ STATUS_TEXT[item.status] }}</span>
          </div>
          <details v-if="item.note">
            <summary>
              研究笔记 · {{ item.noteChars }} 字
              <template v-if="item.rawChars">（原始资料 {{ item.rawChars }} 字）</template>
            </summary>
            <div class="note">{{ item.note }}</div>
          </details>
          <div v-if="item.error" class="error">{{ item.error }}</div>
        </li>
      </ul>
      <div v-if="reflectionAfter(round)" class="reflection">
        <span class="tag">反思</span>
        <div>
          <template v-if="reflectionAfter(round)!.sufficient">信息已充分，进入撰写</template>
          <template v-else>
            发现 {{ reflectionAfter(round)!.gaps.length }} 个缺口，补充
            {{ reflectionAfter(round)!.followUps }} 个子问题
          </template>
          <ul v-if="reflectionAfter(round)!.gaps.length" class="gaps">
            <li v-for="g in reflectionAfter(round)!.gaps" :key="g">{{ g }}</li>
          </ul>
        </div>
      </div>
    </template>
  </section>
</template>

<style scoped>
.plan {
  padding-bottom: 12px;
  font-size: 13px;
}
.phases {
  display: flex;
  list-style: none;
  margin: 12px 16px 4px;
  padding: 0;
  gap: 4px;
}
.phases li {
  flex: 1;
  padding: 2px 0;
  border-radius: 4px;
  background: var(--code-bg);
  color: var(--muted);
  text-align: center;
  font-size: 12px;
}
.phases li.active {
  background: var(--accent-fill);
  color: var(--accent-on);
  font-weight: 500;
}
.phases li.done {
  background: var(--accent-soft);
  color: var(--accent);
}
.brief {
  margin: 8px 16px 0;
  color: var(--muted);
}
.round-label {
  margin: 12px 16px 0;
  color: var(--muted);
  font-size: 12px;
}
.items {
  list-style: none;
  margin: 8px 0 0;
  padding: 0 16px;
}
.items > li {
  padding: 8px 0;
  border-bottom: 1px dashed var(--border);
}
.items > li:last-child {
  border-bottom: none;
}
.row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}
.id {
  flex-shrink: 0;
  padding: 0 6px;
  border-radius: 4px;
  background: var(--code-bg);
  color: var(--muted);
  font-size: 12px;
  line-height: 20px;
}
.question {
  flex: 1;
  min-width: 0;
}
.status {
  flex-shrink: 0;
  color: var(--muted);
  font-size: 12px;
}
.running .id {
  background: var(--accent-soft);
  color: var(--accent);
}
.running .status {
  color: var(--accent);
}
.done .status {
  color: var(--success);
}
.failed .status,
.error {
  color: var(--danger);
}
details {
  margin: 4px 0 0 36px;
}
summary {
  color: var(--muted);
  font-size: 12px;
  cursor: pointer;
}
.note {
  margin-top: 4px;
  padding: 8px;
  border-radius: 6px;
  background: var(--code-bg);
  white-space: pre-wrap;
  font-size: 12px;
}
.error {
  margin: 4px 0 0 36px;
  font-size: 12px;
}
.reflection {
  display: flex;
  gap: 8px;
  margin: 8px 16px 0;
  padding: 8px;
  border-radius: 6px;
  background: var(--accent-soft);
}
.reflection .tag {
  flex-shrink: 0;
  color: var(--accent);
  font-weight: 600;
}
.gaps {
  margin: 4px 0 0;
  padding-left: 18px;
  color: var(--muted);
}
</style>
