<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { createResearch, listResearch, subscribeEvents } from './api/research'
import CollapsiblePanel from './components/CollapsiblePanel.vue'
import EventTimeline from './components/EventTimeline.vue'
import PlanBoard from './components/PlanBoard.vue'
import ReportView from './components/ReportView.vue'
import ResearchInput from './components/ResearchInput.vue'
import type { AgentEvent, AgentMode, Source, TaskStatus, TaskSummary } from './types'

const MODE_TEXT: Record<AgentMode, string> = {
  multi: '深度 · 多 Agent',
  single: '快速 · 单 Agent',
}

const STATUS_TEXT: Record<TaskStatus, string> = {
  pending: '排队中',
  running: '研究中',
  completed: '已完成',
  failed: '失败',
}

const tasks = ref<TaskSummary[]>([])
const currentId = ref<string | null>(null)
const currentQuery = ref('')
const currentMode = ref<AgentMode>('multi')
const status = ref<TaskStatus>('pending')
const events = ref<AgentEvent[]>([])
const errorMsg = ref('')
let unsubscribe: (() => void) | null = null

const running = computed(() => status.value === 'pending' || status.value === 'running')
const report = computed(() => {
  const e = events.value.find((e) => e.type === 'report')
  return e ? (e.data as { markdown: string; sources: Source[] }) : null
})
const hasPlan = computed(() => events.value.some((e) => e.type === 'plan'))

// 侧栏两张卡片默认收起；都收起时侧栏缩成竖排标签，报告区铺满
const planOpen = ref(false)
const timelineOpen = ref(false)
const sideCollapsed = computed(() => !(hasPlan.value && planOpen.value) && !timelineOpen.value)

const planBadge = computed(() => {
  let total = 0
  let done = 0
  for (const e of events.value) {
    if (e.type === 'plan') total += e.data.sub_questions.length
    else if (e.type === 'reflection') total += e.data.follow_up_questions.length
    else if (e.type === 'researcher_done') done += 1
  }
  return total ? `${done}/${total}` : undefined
})
const toolCallCount = computed(() => events.value.filter((e) => e.type === 'tool_call').length)

async function refreshTasks() {
  try {
    tasks.value = await listResearch()
  } catch {
    // 后端未启动时静默失败，不影响页面使用
  }
}

// 打开一个任务：从头订阅事件流。已完成的任务会回放全部历史事件
function open(task: Pick<TaskSummary, 'id' | 'query' | 'mode' | 'status'>) {
  unsubscribe?.()
  errorMsg.value = ''
  currentId.value = task.id
  currentQuery.value = task.query
  currentMode.value = task.mode
  status.value = task.status
  events.value = []

  unsubscribe = subscribeEvents(
    task.id,
    (event) => {
      events.value.push(event)
      if (event.type === 'done') {
        status.value = event.data.status
        refreshTasks()
      }
    },
    () => {
      errorMsg.value = '与服务器的连接已断开'
    },
  )
}

async function start(query: string, mode: AgentMode) {
  errorMsg.value = ''
  try {
    const { task_id } = await createResearch(query, mode)
    open({ id: task_id, query, mode, status: 'running' })
    refreshTasks()
  } catch (e) {
    errorMsg.value = `创建任务失败：${(e as Error).message}`
  }
}

function newResearch() {
  unsubscribe?.()
  unsubscribe = null
  currentId.value = null
  events.value = []
  errorMsg.value = ''
}

onMounted(refreshTasks)
onUnmounted(() => unsubscribe?.())
</script>

<template>
  <div class="layout">
    <aside class="sidebar">
      <div class="brand">Deep Research</div>
      <button class="new-btn" @click="newResearch">+ 新研究</button>
      <div class="history-title">历史记录</div>
      <ul class="history">
        <li
          v-for="t in tasks"
          :key="t.id"
          :class="{ active: t.id === currentId }"
          :title="t.query"
          @click="open(t)"
        >
          <span class="q">{{ t.query }}</span>
          <span class="badge" :class="t.status">{{ STATUS_TEXT[t.status] }}</span>
        </li>
        <li v-if="!tasks.length" class="empty">暂无记录</li>
      </ul>
    </aside>

    <main class="main">
      <template v-if="!currentId">
        <div class="hero">
          <h1>想研究点什么？</h1>
          <p>Agent 会多轮检索网页、阅读原文，最后写出一份带引用的研究报告。</p>
        </div>
        <ResearchInput @submit="start" />
      </template>

      <template v-else>
        <header class="task-header">
          <h2>{{ currentQuery }}</h2>
          <span class="badge" :class="status">{{ STATUS_TEXT[status] }}</span>
          <span class="badge">{{ MODE_TEXT[currentMode] }}</span>
        </header>
        <div class="workspace" :class="{ collapsed: sideCollapsed }">
          <div class="side">
            <CollapsiblePanel
              v-if="hasPlan"
              v-model:open="planOpen"
              title="研究计划"
              :rail="sideCollapsed"
              :badge="planBadge"
            >
              <PlanBoard :events="events" :finished="!running" />
            </CollapsiblePanel>
            <CollapsiblePanel
              v-model:open="timelineOpen"
              title="研究过程"
              :rail="sideCollapsed"
              :active="running"
              :badge="toolCallCount ? String(toolCallCount) : undefined"
            >
              <EventTimeline :events="events" />
            </CollapsiblePanel>
          </div>
          <ReportView v-if="report" :markdown="report.markdown" :sources="report.sources" />
          <div v-else class="panel placeholder">
            <template v-if="running">
              研究进行中，报告生成后会显示在这里。<br />
              可以展开左侧的「研究计划」「研究过程」查看实时进展。
            </template>
            <template v-else>本次研究没有生成报告</template>
          </div>
        </div>
      </template>

      <p v-if="errorMsg" class="error">{{ errorMsg }}</p>
    </main>
  </div>
</template>

<style scoped>
.layout {
  display: grid;
  grid-template-columns: 260px 1fr;
  min-height: 100vh;
}
.sidebar {
  display: flex;
  flex-direction: column;
  padding: 20px 12px;
  border-right: 1px solid var(--border);
  background: var(--panel);
  height: 100vh;
  position: sticky;
  top: 0;
}
.brand {
  padding: 0 8px 16px;
  font-size: 18px;
  font-weight: 700;
}
.new-btn {
  padding: 8px;
  border: 1px dashed var(--border);
  border-radius: 8px;
  background: transparent;
  color: var(--text);
}
.new-btn:hover {
  border-color: var(--accent);
  color: var(--accent);
}
.history-title {
  margin: 20px 8px 8px;
  color: var(--muted);
  font-size: 12px;
}
.history {
  list-style: none;
  margin: 0;
  padding: 0;
  overflow-y: auto;
}
.history li {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 14px;
}
.history li:hover,
.history li.active {
  background: var(--accent-soft);
}
.history .q {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.history .empty {
  color: var(--muted);
  cursor: default;
}
.history .empty:hover {
  background: transparent;
}
.main {
  min-width: 0;
  padding: 24px 32px;
}
.hero {
  max-width: 760px;
  margin: 18vh auto 24px;
  text-align: center;
}
.hero h1 {
  margin-bottom: 8px;
}
.hero p {
  color: var(--muted);
}
.task-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}
.task-header h2 {
  margin: 0;
  font-size: 20px;
}
.workspace {
  display: grid;
  grid-template-columns: 380px minmax(0, 1fr);
  gap: 20px;
  align-items: start;
  transition: grid-template-columns 0.25s ease;
}
.workspace.collapsed {
  grid-template-columns: 48px minmax(0, 1fr);
}
.side {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
  position: sticky;
  top: 24px;
  max-height: calc(100vh - 48px);
  overflow-y: auto;
}
.placeholder {
  padding: 48px;
  text-align: center;
  color: var(--muted);
}
.error {
  color: var(--danger);
}
@media (max-width: 1100px) {
  .workspace,
  .workspace.collapsed {
    grid-template-columns: minmax(0, 1fr);
  }
  .side {
    position: static;
    max-height: none;
    overflow: visible;
  }
  .workspace :deep(.timeline) {
    max-height: 360px;
  }
}
@media (max-width: 760px) {
  .layout {
    grid-template-columns: 1fr;
  }
  .sidebar {
    position: static;
    height: auto;
    max-height: 240px;
    border-right: none;
    border-bottom: 1px solid var(--border);
  }
  .main {
    padding: 16px;
  }
}
</style>
