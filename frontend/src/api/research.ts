import type { AgentEvent, AgentMode, TaskDetail, TaskSummary } from '../types'

const BASE = import.meta.env.VITE_API_BASE ?? ''

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    throw new Error(`${res.status} ${await res.text()}`)
  }
  return res.json() as Promise<T>
}

export function createResearch(query: string, mode: AgentMode) {
  return request<{ task_id: string }>('/api/research', {
    method: 'POST',
    body: JSON.stringify({ query, mode }),
  })
}

export function listResearch() {
  return request<TaskSummary[]>('/api/research')
}

export function getResearch(id: string) {
  return request<TaskDetail>(`/api/research/${id}`)
}

/**
 * 订阅任务事件流，返回取消订阅函数。
 *
 * 网络中断时浏览器会自动重连并带上 Last-Event-ID，后端从断点继续推送，这里不需要额外处理。
 * 收到 done 后必须主动 close，否则 EventSource 会在服务端关闭连接后不断重连。
 */
export function subscribeEvents(
  id: string,
  onEvent: (event: AgentEvent) => void,
  onError?: (err: Event) => void,
): () => void {
  const es = new EventSource(`${BASE}/api/research/${id}/events`)

  es.onmessage = (msg) => {
    const event = JSON.parse(msg.data) as AgentEvent
    onEvent(event)
    if (event.type === 'done') es.close()
  }
  es.onerror = (err) => {
    if (es.readyState === EventSource.CLOSED) onError?.(err)
  }

  return () => es.close()
}
