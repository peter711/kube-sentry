import { createRootRoute, createRoute, createRouter, Navigate, Outlet } from '@tanstack/react-router'
import { AppShell } from './components/app-shell'
import { AgentPage } from './pages/agent-page'
import { AuditPage } from './pages/audit-page'
import { OperationsPage } from './pages/operations-page'
import { ProposalsPage } from './pages/proposals-page'

const rootRoute = createRootRoute({ component: () => <AppShell><Outlet /></AppShell> })
const indexRoute = createRoute({ getParentRoute: () => rootRoute, path: '/', component: () => <Navigate to="/agent" /> })
const agentRoute = createRoute({ getParentRoute: () => rootRoute, path: '/agent', component: AgentPage })
const proposalsRoute = createRoute({ getParentRoute: () => rootRoute, path: '/proposals', component: ProposalsPage })
const operationsRoute = createRoute({ getParentRoute: () => rootRoute, path: '/operations', component: OperationsPage })
const auditRoute = createRoute({ getParentRoute: () => rootRoute, path: '/audit', component: AuditPage })

const routeTree = rootRoute.addChildren([indexRoute, agentRoute, proposalsRoute, operationsRoute, auditRoute])
export const router = createRouter({ routeTree, basepath: '/ui' })

declare module '@tanstack/react-router' {
  interface Register { router: typeof router }
}
