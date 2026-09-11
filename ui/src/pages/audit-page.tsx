import { useQuery } from '@tanstack/react-query'
import { RefreshCw } from 'lucide-react'
import { api } from '../api/client'
import { Button, Card, EmptyState, PageTitle } from '../components/ui'
import { formatTimestamp, shortId } from '../lib/utils'

export function AuditPage() {
  const audit = useQuery({ queryKey: ['audit'], queryFn: () => api.audit(150), refetchInterval: 5000 })
  const events = audit.data?.events ?? []
  return <div><PageTitle eyebrow="History" title="Audit trail" description="Read-only timeline from the agent, operator and worker. Raw details stay expandable instead of taking over the page." actions={<Button variant="secondary" onClick={() => void audit.refetch()}><RefreshCw size={15}/>Refresh</Button>}/><Card className="mt-6 overflow-hidden"><div className="divide-y divide-white/[0.05]">{events.map((event) => <details key={event.id} className="group"><summary className="grid cursor-pointer list-none gap-2 px-4 py-3 hover:bg-white/[0.025] md:grid-cols-[170px_minmax(220px,1fr)_150px_210px]"><span className="text-xs text-zinc-500">{formatTimestamp(event.created_at)}</span><span className="code-font text-xs text-zinc-200">{event.event_type}</span><span className="text-xs text-zinc-400">{event.actor ?? '—'}</span><span className="code-font text-xs text-zinc-600">{shortId(event.proposal_id, 22)}</span></summary><pre className="scrollbar-thin overflow-x-auto border-t border-white/[0.04] bg-black/20 p-4 text-[11px] leading-5 text-zinc-400">{JSON.stringify(event.details, null, 2)}</pre></details>)}</div>{!audit.isLoading && events.length === 0 && <div className="p-5"><EmptyState title="Audit is empty"/></div>}</Card></div>
}
