import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ExternalLink, LoaderCircle, Play, RotateCcw, TerminalSquare } from 'lucide-react'
import { useMemo, useState } from 'react'
import { toast } from 'sonner'
import { api } from '../api/client'
import type { AskResponse, ToolCall } from '../api/types'
import { Button, Card, EmptyState, PageTitle } from '../components/ui'
import { shortId } from '../lib/utils'

const storageKey = 'ai-k8s-lab-conversation-id'

function ToolInspector({ calls, traceId }: { calls: ToolCall[]; traceId?: string | null }) {
  const rounds = useMemo(() => {
    const grouped = new Map<number, ToolCall[]>()
    calls.forEach((call) => grouped.set(call.round, [...(grouped.get(call.round) ?? []), call]))
    return [...grouped.entries()]
  }, [calls])
  return <Card className="h-full min-h-[360px] overflow-hidden">
    <div className="border-b border-white/[0.06] px-4 py-4">
      <div className="flex items-center justify-between"><h2 className="text-sm font-semibold text-white">Run Inspector</h2><span className="code-font text-[11px] text-zinc-500">{shortId(traceId, 16)}</span></div>
      <p className="mt-1 text-xs text-zinc-500">Tool decisions from the latest agent run.</p>
    </div>
    <div className="scrollbar-thin max-h-[650px] space-y-5 overflow-y-auto p-4">
      {rounds.length === 0 ? <EmptyState title="No tool calls yet">Ask the agent about the cluster to populate this panel.</EmptyState> : rounds.map(([round, items]) => <div key={round}>
        <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-zinc-500">Round {round}</div>
        <div className="space-y-2">{items.map((call, index) => <details key={`${call.tool}-${index}`} className="group rounded-lg border border-white/[0.06] bg-black/20 open:bg-white/[0.025]">
          <summary className="flex list-none items-center justify-between gap-3 px-3 py-2.5 text-sm">
            <span className="flex min-w-0 items-center gap-2"><span className="size-1.5 shrink-0 rounded-full bg-emerald-400"/><span className="code-font truncate text-zinc-200">{call.tool}</span></span>
            <span className="text-[11px] text-zinc-500">{call.result_summary}</span>
          </summary>
          <pre className="scrollbar-thin overflow-x-auto border-t border-white/[0.06] p-3 text-[11px] leading-5 text-zinc-400">{JSON.stringify(call.arguments, null, 2)}</pre>
        </details>)}</div>
      </div>)}
    </div>
    {traceId && <div className="border-t border-white/[0.06] p-3"><a href="/grafana/" target="_blank" rel="noreferrer"><Button variant="secondary" className="w-full"><ExternalLink size={15}/>Open Grafana</Button></a></div>}
  </Card>
}

export function AgentPage() {
  const [conversationId, setConversationId] = useState<string | null>(() => localStorage.getItem(storageKey))
  const [question, setQuestion] = useState('')
  const queryClient = useQueryClient()
  const [latestRun, setLatestRun] = useState<AskResponse | null>(null)
  const conversation = useQuery({ queryKey: ['conversation', conversationId], queryFn: () => api.conversation(conversationId!), enabled: !!conversationId })
  const ask = useMutation({
    mutationFn: () => api.ask(question, conversationId),
    onSuccess: (response) => {
      setLatestRun(response)
      setConversationId(response.conversation_id)
      localStorage.setItem(storageKey, response.conversation_id)
      setQuestion('')
      void queryClient.invalidateQueries({ queryKey: ['conversation', response.conversation_id] })
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : 'Agent request failed'),
  })
  const turns = conversation.data?.turns ?? []

  const reset = () => {
    localStorage.removeItem(storageKey)
    setConversationId(null)
    setLatestRun(null)
  }

  return <div>
    <PageTitle eyebrow="Operator workflow" title="Agent" description="Ask the Kubernetes agent, keep a conversation context, and inspect every tool it chooses during the latest run." actions={<Button variant="secondary" onClick={reset}><RotateCcw size={15}/>New conversation</Button>} />
    <div className="mt-6 grid gap-5 xl:grid-cols-[minmax(0,1.55fr)_minmax(330px,.75fr)]">
      <Card className="flex min-h-[700px] flex-col overflow-hidden">
        <div className="flex items-center justify-between border-b border-white/[0.06] px-5 py-4">
          <div><div className="text-sm font-medium text-white">Conversation</div><div className="code-font mt-0.5 text-[11px] text-zinc-500">{conversationId ?? 'new conversation'}</div></div>
          {latestRun && <div className="text-right text-xs text-zinc-500"><div>{latestRun.model}</div><div>{latestRun.namespace}</div></div>}
        </div>
        <div className="scrollbar-thin flex-1 space-y-5 overflow-y-auto px-5 py-6">
          {turns.length === 0 && !latestRun ? <div className="grid h-full min-h-[400px] place-items-center"><EmptyState title="Start with a cluster question">Try “Why is broken-nginx failing?” or ask the agent to prepare a repair proposal.</EmptyState></div> : turns.map((turn, index) => <div key={`${turn.created_at}-${index}`} className={turn.role === 'user' ? 'ml-auto max-w-[80%]' : 'mr-auto max-w-[88%]'}>
            <div className={turn.role === 'user' ? 'rounded-2xl rounded-br-md bg-indigo-500 px-4 py-3 text-sm leading-6 text-white' : 'rounded-2xl rounded-bl-md border border-white/[0.07] bg-white/[0.035] px-4 py-3 text-sm leading-6 text-zinc-200'}>
              <div className="whitespace-pre-wrap">{turn.content}</div>
            </div>
          </div>)}
        </div>
        <form className="border-t border-white/[0.06] p-4" onSubmit={(event) => { event.preventDefault(); if (question.trim() && !ask.isPending) ask.mutate() }}>
          <div className="rounded-xl border border-white/[0.09] bg-black/30 p-2 focus-within:border-indigo-400/40">
            <textarea value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="Ask the agent about ai-lab…" rows={3} className="w-full resize-none bg-transparent px-2 py-2 text-sm leading-6 text-white outline-none placeholder:text-zinc-600" />
            <div className="flex items-center justify-between border-t border-white/[0.05] px-1 pt-2"><span className="flex items-center gap-1.5 text-[11px] text-zinc-600"><TerminalSquare size={13}/>tools visible in Run Inspector</span><Button type="submit" disabled={!question.trim() || ask.isPending}>{ask.isPending ? <LoaderCircle className="animate-spin" size={15}/> : <Play size={15}/>}Run agent</Button></div>
          </div>
        </form>
      </Card>
      <ToolInspector calls={latestRun?.tool_calls ?? []} traceId={latestRun?.trace_id} />
    </div>
  </div>
}
