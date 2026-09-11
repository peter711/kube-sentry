import { Link, useRouterState } from '@tanstack/react-router'
import { Activity, Bot, Boxes, ExternalLink, FileClock, GitPullRequestArrow, Waves } from 'lucide-react'
import type { ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import { cn } from '../lib/utils'

const nav = [
  { to: '/agent', label: 'Agent', icon: Bot },
  { to: '/proposals', label: 'Proposals', icon: GitPullRequestArrow },
  { to: '/operations', label: 'Operations', icon: Boxes },
  { to: '/audit', label: 'Audit', icon: FileClock },
]

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = useRouterState({ select: (state) => state.location.pathname })
  const health = useQuery({ queryKey: ['health'], queryFn: api.health, refetchInterval: 10_000 })

  return <div className="shell-grid">
    <aside className="desktop-sidebar sticky top-0 h-screen border-r border-white/[0.06] bg-[#0a0d13]/92 px-4 py-5 backdrop-blur-xl">
      <div className="mb-8 flex items-center gap-3 px-2">
        <div className="grid size-9 place-items-center rounded-xl border border-indigo-400/20 bg-indigo-400/10 text-indigo-300"><Waves size={19} /></div>
        <div>
          <div className="text-sm font-semibold text-white">KubeSentry</div>
          <div className="text-[11px] text-zinc-500">Operator Console</div>
        </div>
      </div>
      <nav className="space-y-1">
        {nav.map((item) => {
          const Icon = item.icon
          const active = pathname.startsWith(`/ui${item.to}`) || pathname === item.to
          return <Link key={item.to} to={item.to} className={cn('flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition', active ? 'bg-white/[0.07] text-white' : 'text-zinc-400 hover:bg-white/[0.04] hover:text-zinc-200')}>
            <Icon size={17} />{item.label}
          </Link>
        })}
      </nav>
      <div className="absolute inset-x-4 bottom-5 space-y-3">
        <a href="/grafana/" target="_blank" rel="noreferrer" className="flex items-center justify-between rounded-lg border border-white/[0.07] bg-white/[0.03] px-3 py-2.5 text-sm text-zinc-300 hover:bg-white/[0.06]">
          <span className="flex items-center gap-2"><Activity size={16} />Grafana</span><ExternalLink size={14} />
        </a>
        <div className="rounded-lg border border-white/[0.06] bg-black/20 px-3 py-3">
          <div className="flex items-center justify-between text-xs">
            <span className="text-zinc-500">API</span>
            <span className={cn('font-medium', health.data?.status === 'ok' ? 'text-emerald-300' : 'text-amber-300')}>{health.data?.status ?? 'checking'}</span>
          </div>
          <div className="mt-2 flex items-center justify-between text-xs">
            <span className="text-zinc-500">Version</span><span className="code-font text-zinc-300">{health.data?.version ?? '—'}</span>
          </div>
        </div>
      </div>
    </aside>
    <main className="min-w-0">
      <div className="mx-auto w-full max-w-[1500px] px-4 py-6 md:px-8 md:py-8">{children}</div>
    </main>
  </div>
}
