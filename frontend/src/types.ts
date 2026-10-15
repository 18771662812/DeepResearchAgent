// 与后端 app/api/research.py、app/agent/events.py 保持一致

export type TaskStatus = 'pending' | 'running' | 'completed' | 'failed'

export interface TaskSummary {
  id: string
  query: string
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

export interface Usage {
  prompt_tokens: number
  completion_tokens: number
  cache_hit_tokens: number
  calls: number
}

export type AgentEventType =
  | 'status'
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
  ts: number
}
