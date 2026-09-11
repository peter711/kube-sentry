import type { AskResponse, AuditEvent, ConversationTurn, Operation, Proposal } from './types'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
  })
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`
    try {
      const body = await response.json() as { detail?: string }
      if (body.detail) message = body.detail
    } catch {
      // Keep HTTP status text.
    }
    throw new Error(message)
  }
  return response.json() as Promise<T>
}

export const api = {
  health: () => request<{ status: string; version: string }>('/health'),
  ask: (question: string, conversationId?: string | null) => request<AskResponse>('/ask', {
    method: 'POST',
    body: JSON.stringify({ question, conversation_id: conversationId || null }),
  }),
  conversation: (conversationId: string) => request<{ conversation_id: string; turns: ConversationTurn[] }>(`/conversations/${encodeURIComponent(conversationId)}`),
  proposals: () => request<{ proposals: Proposal[] }>('/repair/proposals'),
  proposal: (id: string) => request<Proposal>(`/repair/proposals/${encodeURIComponent(id)}`),
  approve: (id: string, approvedBy: string) => request<{ proposal_id: string; status: string; job_name: string; trace_id?: string | null }>(`/repair/proposals/${encodeURIComponent(id)}/approve`, {
    method: 'POST',
    body: JSON.stringify({ confirmation: 'APPLY', approved_by: approvedBy }),
  }),
  reject: (id: string, rejectedBy: string, reason: string) => request<{ proposal_id: string; status: string; reason: string }>(`/repair/proposals/${encodeURIComponent(id)}/reject`, {
    method: 'POST',
    body: JSON.stringify({ rejected_by: rejectedBy, reason: reason || null }),
  }),
  operation: (id: string) => request<Operation>(`/operations/${encodeURIComponent(id)}`),
  audit: (limit = 100) => request<{ events: AuditEvent[] }>(`/audit?limit=${limit}`),
}
