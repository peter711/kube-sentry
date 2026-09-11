import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from 'react'
import { cn } from '../lib/utils'

export function Button({ className, variant = 'default', ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'default' | 'secondary' | 'danger' | 'ghost' }) {
  const variants = {
    default: 'bg-indigo-500 text-white hover:bg-indigo-400 border-indigo-400/30',
    secondary: 'bg-white/[0.06] text-zinc-100 hover:bg-white/[0.1] border-white/10',
    danger: 'bg-red-500/12 text-red-300 hover:bg-red-500/20 border-red-500/25',
    ghost: 'bg-transparent text-zinc-300 hover:bg-white/[0.05] border-transparent',
  }
  return <button className={cn('inline-flex items-center justify-center gap-2 rounded-lg border px-3.5 py-2 text-sm font-medium transition disabled:pointer-events-none disabled:opacity-50', variants[variant], className)} {...props} />
}

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('surface rounded-xl', className)} {...props} />
}

export function PageTitle({ eyebrow, title, description, actions }: { eyebrow?: string; title: string; description?: string; actions?: ReactNode }) {
  return <div className="flex flex-col gap-4 border-b border-white/[0.06] pb-6 md:flex-row md:items-end md:justify-between">
    <div>
      {eyebrow && <p className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-indigo-300">{eyebrow}</p>}
      <h1 className="text-2xl font-semibold tracking-tight text-white md:text-3xl">{title}</h1>
      {description && <p className="mt-2 max-w-3xl text-sm leading-6 text-zinc-400">{description}</p>}
    </div>
    {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
  </div>
}

export function StatusBadge({ status }: { status: string }) {
  const normalized = status.toLowerCase()
  const styles = normalized === 'verified' || normalized === 'healthy' || normalized === 'ok'
    ? 'border-emerald-400/20 bg-emerald-400/10 text-emerald-300'
    : normalized === 'failed' || normalized === 'error'
      ? 'border-red-400/20 bg-red-400/10 text-red-300'
      : normalized === 'pending'
        ? 'border-amber-400/20 bg-amber-400/10 text-amber-300'
        : normalized === 'running' || normalized === 'queued'
          ? 'border-blue-400/20 bg-blue-400/10 text-blue-300'
          : 'border-white/10 bg-white/[0.04] text-zinc-300'
  return <span className={cn('inline-flex items-center rounded-full border px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.08em]', styles)}>{status}</span>
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return <div className="rounded-xl border border-dashed border-white/10 bg-white/[0.02] px-6 py-12 text-center">
    <p className="font-medium text-zinc-200">{title}</p>
    {children && <div className="mt-2 text-sm text-zinc-500">{children}</div>}
  </div>
}
