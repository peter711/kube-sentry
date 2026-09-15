# Kube Sentry - developer task runner
#
# Run `make` or `make help` to list every target.

SHELL := /bin/bash
.DEFAULT_GOAL := help

CLUSTER   ?= ai-lab
NAMESPACE ?= ai-lab
URL       ?= http://localhost:8080
VENV      ?= .venv
PYTHON    := $(shell [ -x $(VENV)/bin/python ] && echo $(VENV)/bin/python || echo python3)
Q         ?= Why is broken-nginx not working? Diagnose from the cluster.
K         ?=

.PHONY: help \
	venv install install-evals install-ui \
	cluster-create cluster-delete cluster-info cluster-status \
	deploy deploy-ui rebuild redeploy deploy-all \
	health ask proposals audit \
	demo-image-pull demo-crashloop demo-healthy demo-fix-crashy demo-fix-nginx demo-reset demo-clean \
	evals evals-filter evals-live evals-live-diagnosis evals-live-repair evals-clean test \
	observability-test port-forward-prometheus port-forward-tempo logs-agent logs-worker logs-otel logs-tempo \
	rbac-check rbac-list \
	ui-dev ui-build ui-preview ui-typecheck \
	compile lint \
	clean distclean

## ---------------------------------------------------------------------------
## Help
## ---------------------------------------------------------------------------

help: ## Show this help
	@echo "Kube Sentry targets:"
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-24s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo ""
	@echo "Variables: CLUSTER=$(CLUSTER) NAMESPACE=$(NAMESPACE) URL=$(URL) Q=\"$(Q)\""

## ---------------------------------------------------------------------------
## Environment
## ---------------------------------------------------------------------------

venv: ## Create the Python virtualenv
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install --upgrade pip

install: install-evals install-ui ## Install all Python and UI dependencies

install-evals: venv ## Install agent + eval Python dependencies
	$(VENV)/bin/pip install -r evals/requirements-evals.txt

install-ui: ## Install UI dependencies (npm)
	npm --prefix ui install

## ---------------------------------------------------------------------------
## Cluster lifecycle
## ---------------------------------------------------------------------------

cluster-create: ## Create the local k3d cluster (ai-lab)
	./scripts/create-cluster.sh

cluster-delete: ## Delete the local k3d cluster
	k3d cluster delete $(CLUSTER)

cluster-info: ## Show cluster connection info
	kubectl cluster-info

cluster-status: ## Show nodes and ai-lab workloads
	kubectl get nodes
	kubectl -n $(NAMESPACE) get deploy,svc,ingress,pods

## ---------------------------------------------------------------------------
## Deploy
## ---------------------------------------------------------------------------

deploy: ## Build and deploy the agent + observability stack (needs OPENAI_API_KEY)
	./scripts/deploy.sh

deploy-ui: ## Build and deploy the React operator console
	./scripts/deploy-ui.sh

rebuild: ## Rebuild and restart only the agent image
	./scripts/rebuild.sh

redeploy: rebuild ## Alias for rebuild

deploy-all: cluster-create deploy deploy-ui ## Cluster + agent + UI end to end

## ---------------------------------------------------------------------------
## API smoke tests
## ---------------------------------------------------------------------------

health: ## Check the agent liveness endpoint
	@curl -s $(URL)/health | jq

ask: ## Ask the agent a question (Q="...")
	@curl -s -X POST $(URL)/ask \
		-H 'Content-Type: application/json' \
		-d '{"question":"$(Q)"}' | jq

proposals: ## List repair proposals
	@curl -s $(URL)/repair/proposals | jq

audit: ## Show the audit event timeline
	@curl -s $(URL)/audit | jq

## ---------------------------------------------------------------------------
## Demo scenarios
## ---------------------------------------------------------------------------

demo-image-pull: ## Deploy the broken-nginx image-pull scenario
	kubectl apply -f demo/broken-nginx.yaml

demo-crashloop: ## Deploy the crashy-app CrashLoopBackOff scenario
	kubectl apply -f demo/crashy-app.yaml

demo-healthy: ## Deploy the healthy web workload
	kubectl apply -f demo/healthy-web.yaml
	kubectl -n $(NAMESPACE) rollout status deploy/web --timeout=120s

demo-fix-crashy: ## Apply the fixed crashy-app manifest
	kubectl apply -f demo/fixed-crashy-app.yaml
	kubectl -n $(NAMESPACE) rollout status deploy/crashy-app

demo-fix-nginx: ## Apply the fixed broken-nginx manifest
	kubectl apply -f demo/fixed-nginx.yaml
	kubectl -n $(NAMESPACE) rollout status deploy/broken-nginx

demo-reset: ## Reset demo workloads to a known-good baseline
	-kubectl apply -f demo/fixed-nginx.yaml
	-kubectl apply -f demo/fixed-crashy-app.yaml
	-kubectl apply -f demo/healthy-web.yaml
	-kubectl -n $(NAMESPACE) rollout status deploy/broken-nginx --timeout=120s
	-kubectl -n $(NAMESPACE) rollout status deploy/crashy-app --timeout=120s
	-kubectl -n $(NAMESPACE) rollout status deploy/web --timeout=120s

demo-clean: ## Delete demo workloads from the namespace
	kubectl -n $(NAMESPACE) delete deploy broken-nginx crashy-app web --ignore-not-found

## ---------------------------------------------------------------------------
## Evals
## ---------------------------------------------------------------------------

evals: ## Run the deterministic offline eval suite
	./scripts/run-evals.sh

evals-filter: ## Run a subset of offline evals (K=proposal)
	@test -n "$(K)" || (echo "usage: make evals-filter K=<substring>" && exit 1)
	./scripts/run-evals.sh -k "$(K)"

evals-live: ## Run live evals (cluster + deployed agent + API key)
	./scripts/run-evals-live.sh

evals-live-diagnosis: ## Run only the read-only live diagnosis evals
	./scripts/run-evals-live.sh -k diagnosis

evals-live-repair: ## Run only the live human-approved repair roundtrip
	./scripts/run-evals-live.sh -m "live and live_repair"

evals-clean: ## Remove generated eval reports
	rm -rf evals/reports .pytest_cache

test: evals ## Alias for evals

## ---------------------------------------------------------------------------
## Observability
## ---------------------------------------------------------------------------

observability-test: ## Generate a sample trace via the agent
	./scripts/test-observability.sh

port-forward-prometheus: ## Port-forward Prometheus to localhost:9090 (foreground)
	kubectl -n $(NAMESPACE) port-forward svc/prometheus 9090:9090

port-forward-tempo: ## Port-forward Tempo to localhost:3200 (foreground)
	kubectl -n $(NAMESPACE) port-forward svc/tempo 3200:3200

logs-agent: ## Tail the ai-agent logs
	kubectl -n $(NAMESPACE) logs deploy/ai-agent --tail=100 -f

logs-worker: ## Tail repair worker Job logs
	kubectl -n $(NAMESPACE) logs -l app=ai-agent-worker --tail=100 -f

logs-otel: ## Tail the OpenTelemetry Collector logs
	kubectl -n $(NAMESPACE) logs deploy/otel-collector --tail=100 -f

logs-tempo: ## Tail the Tempo logs
	kubectl -n $(NAMESPACE) logs deploy/tempo --tail=100 -f

## ---------------------------------------------------------------------------
## RBAC verification
## ---------------------------------------------------------------------------

rbac-check: ## Verify ServiceAccount read/write boundaries
	@echo "ai-agent  get pods/log      : $$(kubectl -n $(NAMESPACE) auth can-i get pods/log --as=system:serviceaccount:$(NAMESPACE):ai-agent)"
	@echo "ai-agent  patch deployments : $$(kubectl -n $(NAMESPACE) auth can-i patch deployments --as=system:serviceaccount:$(NAMESPACE):ai-agent)"
	@echo "ai-agent  delete deployments: $$(kubectl -n $(NAMESPACE) auth can-i delete deployments --as=system:serviceaccount:$(NAMESPACE):ai-agent)"
	@echo "ai-agent  create jobs.batch : $$(kubectl -n $(NAMESPACE) auth can-i create jobs.batch --as=system:serviceaccount:$(NAMESPACE):ai-agent)"
	@echo "worker    patch deployments : $$(kubectl -n $(NAMESPACE) auth can-i patch deployments --as=system:serviceaccount:$(NAMESPACE):ai-agent-worker)"

rbac-list: ## List Roles and RoleBindings (spot stale objects)
	kubectl -n $(NAMESPACE) get role,rolebinding

## ---------------------------------------------------------------------------
## UI
## ---------------------------------------------------------------------------

ui-dev: ## Run the Vite dev server on :5173 (proxies to $(URL))
	npm --prefix ui run dev

ui-build: ## Type-check and build the UI bundle
	npm --prefix ui run build

ui-preview: ## Preview the built UI bundle
	npm --prefix ui run preview

ui-typecheck: ## Type-check the UI
	npm --prefix ui run typecheck

## ---------------------------------------------------------------------------
## Quality
## ---------------------------------------------------------------------------

compile: ## Byte-compile the agent and eval Python sources
	$(PYTHON) -m compileall -q agent evals
	@echo "Python compile OK"

lint: compile ui-typecheck ## Run all local checks (Python compile + UI typecheck)

## ---------------------------------------------------------------------------
## Cleanup
## ---------------------------------------------------------------------------

clean: evals-clean ## Remove caches and generated reports
	find agent evals -type d -name __pycache__ -prune -exec rm -rf {} +
	@echo "Cleaned caches and reports"

distclean: clean ## Remove caches, virtualenv and node_modules
	rm -rf $(VENV) ui/node_modules ui/dist
	@echo "Removed virtualenv and UI dependencies"
