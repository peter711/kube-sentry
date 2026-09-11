import { useQuery } from '@tanstack/react-query'
import { CheckCircle2, Circle, LoaderCircle, RefreshCw, XCircle } from 'lucide-react'
import { useMemo, useState } from 'react'
import { api } from '../api/client'
import type { Operation, Proposal } from '../api/types'
import { Button, Card, EmptyState, PageTitle, StatusBadge } from '../components/ui'
import { formatTimestamp, shortId } from '../lib/utils'

function activeStatus(status?: string) { return status === 'queued' || status === 'running' }

function Step({ state, title, detail }: { state: 'done' | 'active' | 'failed' | 'todo'; title: string; detail?: string }) {
  const Icon = state === 'done' ? CheckCircle2 : state === 'failed' ? XCircle : state === 'active' ? LoaderCircle : Circle
  const cls = state === 'done' ? 'text-emerald-300' : state === 'failed' ? 'text-red-300' : state === 'active' ? 'text-blue-300' : 'text-zinc-600'
  return <div className="flex gap-3"><Icon size={18} className={`${cls} mt-0.5 shrink-0 ${state === 'active' ? 'animate-spin' : ''}`}/><div><div className="text-sm font-medium text-zinc-200">{title}</div>{detail && <div className="mt-1 text-xs leading-5 text-zinc-500">{detail}</div>}</div></div>
}

function OperationDetail({ proposal }: { proposal: Proposal }) {
  const operation = useQuery({ queryKey: ['operation', proposal.id], queryFn: () => api.operation(proposal.id), refetchInterval: (q) => activeStatus(q.state.data?.status) ? 1000 : false })
  const op: Operation | undefined = operation.data
  const finalFailed = op?.status === 'failed' || op?.status === 'stale'
  const verified = op?.status === 'verified'
  const queuedDone = !!op?.job || ['running','verified','failed','stale'].includes(op?.status ?? '')
  const runningDone = verified || finalFailed
  const snapshot = op?.verification?.snapshot

  return <Card className="overflow-hidden"><div className="border-b border-white/[0.06] p-5"><div className="flex flex-wrap items-center justify-between gap-3"><div><div className="text-sm font-semibold text-white">{proposal.deployment_name}</div><div className="code-font mt-1 text-xs text-zinc-500">{proposal.id}</div></div><StatusBadge status={op?.status ?? proposal.status}/></div></div><div className="grid gap-8 p-5 lg:grid-cols-[1fr_1fr]">
    <div className="space-y-6"><Step state="done" title="Proposal approved" detail={proposal.decided_by ? `${proposal.decided_by} · ${formatTimestamp(proposal.decided_at)}` : 'Human approval recorded'}/><Step state={queuedDone ? 'done' : 'active'} title="Worker Job queued" detail={op?.job?.name ?? proposal.execution_job_name ?? 'Waiting for Job'}/><Step state={runningDone ? 'done' : op?.status === 'running' ? 'active' : 'todo'} title="Deployment mutation & verification" detail={op?.verification?.reason ?? (op?.status === 'running' ? 'Worker is verifying rollout health.' : 'Waiting for worker.')}/><Step state={verified ? 'done' : finalFailed ? 'failed' : 'todo'} title={verified ? 'Operation verified' : finalFailed ? 'Verification failed' : 'Completed'} detail={op?.verification?.reason}/></div>
    <div className="rounded-xl border border-white/[0.06] bg-black/20 p-4"><div className="mb-4 text-xs font-medium uppercase tracking-[0.12em] text-zinc-500">Rollout snapshot</div><div className="grid grid-cols-2 gap-3 text-sm"><div className="rounded-lg bg-white/[0.035] p-3"><div className="text-xs text-zinc-500">Desired</div><div className="mt-1 text-xl font-semibold">{snapshot?.replicas ?? '—'}</div></div><div className="rounded-lg bg-white/[0.035] p-3"><div className="text-xs text-zinc-500">Ready</div><div className="mt-1 text-xl font-semibold">{snapshot?.ready_replicas ?? '—'}</div></div><div className="rounded-lg bg-white/[0.035] p-3"><div className="text-xs text-zinc-500">Updated</div><div className="mt-1 text-xl font-semibold">{snapshot?.updated_replicas ?? '—'}</div></div><div className="rounded-lg bg-white/[0.035] p-3"><div className="text-xs text-zinc-500">Unavailable</div><div className="mt-1 text-xl font-semibold">{snapshot?.unavailable_replicas ?? '—'}</div></div></div>{op?.job?.error && <div className="mt-4 rounded-lg border border-red-400/20 bg-red-400/[0.06] p-3 text-xs leading-5 text-red-300">{op.job.error}: {op.job.reason}</div>}</div>
  </div></Card>
}

export function OperationsPage() {
  const proposals = useQuery({ queryKey: ['proposals'], queryFn: api.proposals, refetchInterval: 5000 })
  const operations = useMemo(() => (proposals.data?.proposals ?? []).filter((p) => p.execution_job_name), [proposals.data])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const selected = operations.find((p) => p.id === selectedId) ?? operations[0] ?? null
  return <div><PageTitle eyebrow="Execution" title="Operations" description="Live view of approved repairs. Active Jobs are polled once per second; terminal operations stop polling automatically." actions={<Button variant="secondary" onClick={() => void proposals.refetch()}><RefreshCw size={15}/>Refresh</Button>}/><div className="mt-6 grid gap-5 xl:grid-cols-[360px_minmax(0,1fr)]"><Card className="overflow-hidden"><div className="border-b border-white/[0.06] px-4 py-3 text-xs font-medium uppercase tracking-[0.12em] text-zinc-500">Recent Jobs</div><div className="divide-y divide-white/[0.05]">{operations.map((proposal) => <button key={proposal.id} onClick={() => setSelectedId(proposal.id)} className={`w-full px-4 py-4 text-left hover:bg-white/[0.025] ${selected?.id === proposal.id ? 'bg-white/[0.04]' : ''}`}><div className="flex items-center justify-between gap-3"><span className="truncate text-sm font-medium text-zinc-200">{proposal.deployment_name}</span><StatusBadge status={proposal.status}/></div><div className="code-font mt-2 text-[11px] text-zinc-600">{shortId(proposal.id, 22)}</div></button>)}</div>{!proposals.isLoading && operations.length === 0 && <div className="p-4"><EmptyState title="No operations">Approve a proposal to create a worker Job.</EmptyState></div>}</Card><div>{selected ? <OperationDetail proposal={selected}/> : <Card className="grid min-h-[300px] place-items-center p-6"><EmptyState title="No operation selected"/></Card>}</div></div></div>
}
