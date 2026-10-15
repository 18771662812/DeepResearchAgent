// 与后端 app/api/research.py、app/agent/events.py 保持一致

export type TaskStatus = 'pending' | 'running' | 'completed' | 'failed'
export type AgentMode = 'multi' | 'single'

export interface TaskSummary {
  id: string
  query: string
  mode: AgentMode
  status: TaskStatus
  created_at: number
  error: string | null
}

export interface Source {
  id: number
  url: string
  title: string
  snippet: string
}

export interface TaskDetail extends TaskSummary {
  report: string | null
  sources: Source[]
}

export interface SubQuestion {
  id: number
  question: string
  goal: string
  round: number
}

export type Phase = 'planning' | 'researching' | 'reflecting' | 'writing'

export type AgentEventType =
  | 'status'
  | 'phase'
  | 'plan'
  | 'researcher_start'
  | 'researcher_done'
  | 'reflection'
  | 'step'
  | 'thought'
  | 'tool_call'
  | 'tool_result'
  | 'report'
  | 'usage'
  | 'error'
  | 'done'

export interface AgentEvent {
  type: AgentEventType
  data: Record<string, any>
  // 产生事件的子 Agent，如 "R1"；null 表示主流程
  agent: string | null
  ts: number
}
