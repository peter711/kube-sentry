export type ToolCall = {
  round: number
  tool: string
  arguments: Record<string, unknown>
  result_summary: string
  proposal_id: string | null
}

export type AskResponse = {
  answer: string
  conversation_id: string
  namespace: string
  model: string
  tool_calls: ToolCall[]
  proposal_ids: string[]
  trace_id?: string | null
}

export type ConversationTurn = {
  role: string
  content: string
  created_at: string
}

export type ProposalStatus = 'pending' | 'queued' | 'running' | 'verified' | 'failed' | 'stale' | 'rejected' | string

export type DeploymentSnapshot = {
  name?: string
  resource_version?: string
  generation?: number
  replicas?: number
  images?: Record<string, string>
  current_replicas?: number
  ready_replicas?: number
  available_replicas?: number
  updated_replicas?: number
  unavailable_replicas?: number
  observed_generation?: number
  conditions?: Array<Record<string, unknown>>
}

export type Proposal = {
  id: string
  conversation_id: string
  deployment_name: string
  action: string
  payload: Record<string, unknown>
  rationale: string
  source_resource_version: string
  before: DeploymentSnapshot | null
  status: ProposalStatus
  created_at: string
  decided_at: string | null
  decision_reason: string | null
  decided_by: string | null
  result: Record<string, unknown> | null
  verification: Record<string, unknown> | null
  rollback_of: string | null
  execution_job_name: string | null
}

export type Operation = {
  proposal_id: string
  status: ProposalStatus
  job: null | {
    name?: string
    active?: number
    succeeded?: number
    failed?: number
    start_time?: string | null
    completion_time?: string | null
    conditions?: Array<Record<string, unknown>>
    error?: string
    status_code?: number
    reason?: string
  }
  verification: null | {
    status?: string
    reason?: string
    snapshot?: DeploymentSnapshot
    pods_observed?: Array<{
      name?: string
      phase?: string
      containers?: Array<Record<string, unknown>>
    }>
  }
  result: Record<string, unknown> | null
  rollback_of: string | null
}

export type AuditEvent = {
  id: number
  proposal_id: string | null
  event_type: string
  actor: string | null
  details: Record<string, unknown>
  created_at: string
}
