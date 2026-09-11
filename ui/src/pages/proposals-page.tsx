import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, ChevronRight, RefreshCw, ShieldAlert, X } from 'lucide-react'
import { useMemo, useState } from 'react'
import { toast } from 'sonner'
import { api } from '../api/client'
import type { Proposal } from '../api/types'
import { Button, Card, EmptyState, PageTitle, StatusBadge } from '../components/ui'
import { formatTimestamp, shortId } from '../lib/utils'

function proposalChange(proposal: Proposal) {
  if (proposal.action === 'set_image') {
    const container = String(proposal.payload.container_name ?? 'container')
    const next = String(proposal.payload.image ?? '—')
    const previous = proposal.before?.images?.[container] ?? '—'
    return { previous, next }
  }
  if (proposal.action === 'scale') return { previous: String(proposal.before?.replicas ?? '—'), next: String(proposal.payload.replicas ?? '—') }
  return { previous: '—', next: JSON.stringify(proposal.payload) }
}

function ProposalDetail({ proposal, close }: { proposal: Proposal; close: () => void }) {
  const queryClient = useQueryClient()
  const [confirm, setConfirm] = useState(false)
  const [actor, setActor] = useState('Piotr')
    const change = proposalChange(proposal)
  const approve = useMutation({ mutationFn: () => api.approve(proposal.id, actor), onSuccess: async () => { toast.success('Proposal queued'); setConfirm(false); await queryClient.invalidateQueries({ queryKey: ['proposals'] }) }, onError: (e) => toast.error(e instanceof Error ? e.message : 'Approval failed') })
  const reject = useMutation({ mutationFn: (rejectReason: string) => api.reject(proposal.id, actor, rejectReason), onSuccess: async () => { toast.success('Proposal rejected'); await queryClient.invalidateQueries({ queryKey: ['proposals'] }) }, onError: (e) => toast.error(e instanceof Error ? e.message : 'Reject failed') })

  return <Card className="sticky top-8 overflow-hidden">
    <div className="flex items-start justify-between border-b border-white/[0.06] p-5"><div><StatusBadge status={proposal.status}/><h2 className="mt-3 text-lg font-semibold text-white">{proposal.deployment_name}</h2><div className="code-font mt-1 text-xs text-zinc-500">{proposal.id}</div></div><Button variant="ghost" className="px-2" onClick={close}><X size={17}/></Button></div>
    <div className="space-y-5 p-5">
      <div><div className="mb-2 text-xs font-medium uppercase tracking-[0.12em] text-zinc-500">Requested change</div><div className="rounded-lg border border-white/[0.07] bg-black/25 p-3"><div className="code-font break-all text-xs text-zinc-500 line-through">{change.previous}</div><div className="my-2 text-zinc-600">↓</div><div className="code-font break-all text-sm text-zinc-100">{change.next}</div></div></div>
      <div><div className="mb-2 text-xs font-medium uppercase tracking-[0.12em] text-zinc-500">Rationale</div><p className="text-sm leading-6 text-zinc-300">{proposal.rationale}</p></div>
      <div className="grid grid-cols-2 gap-3 text-xs"><div className="rounded-lg bg-white/[0.03] p-3"><div className="text-zinc-500">Generation</div><div className="code-font mt-1 text-zinc-200">{proposal.before?.generation ?? '—'}</div></div><div className="rounded-lg bg-white/[0.03] p-3"><div className="text-zinc-500">Rollback of</div><div className="code-font mt-1 text-zinc-200">{shortId(proposal.rollback_of)}</div></div></div>
      {proposal.status === 'pending' && <div className="border-t border-white/[0.06] pt-5"><label className="mb-1.5 block text-xs text-zinc-500">Actor</label><input value={actor} onChange={(e) => setActor(e.target.value)} className="mb-3 w-full rounded-lg border border-white/10 bg-black/25 px-3 py-2 text-sm text-white outline-none focus:border-indigo-400/40" />{confirm ? <div className="rounded-lg border border-amber-400/20 bg-amber-400/[0.06] p-3"><div className="flex gap-2 text-sm text-amber-200"><ShieldAlert className="mt-0.5 shrink-0" size={16}/><span>This will create an asynchronous worker Job and mutate Kubernetes.</span></div><div className="mt-3 flex gap-2"><Button onClick={() => approve.mutate()} disabled={approve.isPending}><Check size={15}/>APPLY</Button><Button variant="ghost" onClick={() => setConfirm(false)}>Cancel</Button></div></div> : <div className="flex gap-2"><Button className="flex-1" onClick={() => setConfirm(true)}><Check size={15}/>Approve</Button><Button variant="danger" onClick={() => { const r = window.prompt('Reason for rejection?'); if (r !== null) reject.mutate(r) }}><X size={15}/>Reject</Button></div>}</div>}
    </div>
  </Card>
}

export function ProposalsPage() {
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const proposals = useQuery({ queryKey: ['proposals'], queryFn: api.proposals, refetchInterval: 5000 })
  const rows = proposals.data?.proposals ?? []
  const selected = useMemo(() => rows.find((item) => item.id === selectedId) ?? null, [rows, selectedId])
  return <div><PageTitle eyebrow="Human in the loop" title="Repair proposals" description="Review the exact change captured by the agent before a worker is allowed to touch the cluster." actions={<Button variant="secondary" onClick={() => void proposals.refetch()}><RefreshCw size={15}/>Refresh</Button>}/><div className="mt-6 grid gap-5 xl:grid-cols-[minmax(0,1fr)_420px]">
    <Card className="overflow-hidden"><div className="overflow-x-auto"><table className="w-full border-collapse text-left text-sm"><thead className="border-b border-white/[0.06] bg-white/[0.02] text-xs uppercase tracking-[0.08em] text-zinc-500"><tr><th className="px-4 py-3 font-medium">Status</th><th className="px-4 py-3 font-medium">Deployment</th><th className="px-4 py-3 font-medium">Action</th><th className="px-4 py-3 font-medium">Created</th><th className="w-10"/></tr></thead><tbody>{rows.map((proposal) => <tr key={proposal.id} onClick={() => setSelectedId(proposal.id)} className="cursor-pointer border-b border-white/[0.045] last:border-0 hover:bg-white/[0.025]"><td className="px-4 py-3"><StatusBadge status={proposal.status}/></td><td className="px-4 py-3"><div className="font-medium text-zinc-200">{proposal.deployment_name}</div><div className="code-font mt-0.5 text-[11px] text-zinc-600">{shortId(proposal.id, 18)}</div></td><td className="code-font px-4 py-3 text-xs text-zinc-400">{proposal.rollback_of ? `rollback · ${proposal.action}` : proposal.action}</td><td className="px-4 py-3 text-xs text-zinc-500">{formatTimestamp(proposal.created_at)}</td><td className="pr-3 text-zinc-600"><ChevronRight size={16}/></td></tr>)}</tbody></table></div>{!proposals.isLoading && rows.length === 0 && <div className="p-5"><EmptyState title="No proposals yet">Ask the agent to prepare a repair proposal first.</EmptyState></div>}</Card>
    {selected ? <ProposalDetail proposal={selected} close={() => setSelectedId(null)}/> : <Card className="grid min-h-[300px] place-items-center p-6"><EmptyState title="Select a proposal">Its before/after change and approval controls will appear here.</EmptyState></Card>}
  </div></div>
}
