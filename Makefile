# =============================================================================
# OPNsense Fleet Manager Enterprise - developer entry points
#
# `make help` lists every target. The recipes assume a POSIX shell (Linux,
# macOS, WSL or Git Bash). Docker must be running for the compose targets.
# =============================================================================

SHELL := /bin/bash
COMPOSE ?= docker compose
PYTHON ?= python
VENV ?= backend/.venv
VENV_PY := $(VENV)/bin/python
BACKEND_DIR := backend
FRONTEND_DIR := frontend
PLUGIN_DIR := plugin/os-fleet-agent
TEST_DATABASE_URL ?= postgresql+asyncpg://ofme:ofme@127.0.0.1:55432/ofme_test
TEST_PG ?= ofme-test-pg

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z0-9_.-]+:.*?## ' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# --------------------------------------------------------------------- local stack
.PHONY: env
env: ## Create .env from the template when missing
	@test -f .env || (cp .env.example .env && echo "created .env - edit secrets before production use")

.PHONY: up
up: env ## Build and start the full stack
	$(COMPOSE) up -d --build

.PHONY: up-core
up-core: env ## Start only PostgreSQL, Redis, MinIO and the API
	$(COMPOSE) up -d --build postgres redis minio ofme-api ofme-frontend

.PHONY: down
down: ## Stop the stack, keep volumes
	$(COMPOSE) down --remove-orphans

.PHONY: destroy
destroy: ## Stop the stack and delete every volume (destructive)
	$(COMPOSE) down --volumes --remove-orphans

.PHONY: restart
restart: ## Restart API, worker and beat
	$(COMPOSE) restart ofme-api ofme-worker ofme-beat

.PHONY: ps
ps: ## Show container status
	$(COMPOSE) ps

.PHONY: logs
logs: ## Follow logs of all services
	$(COMPOSE) logs -f --tail=200

.PHONY: logs-api
logs-api: ## Follow API logs
	$(COMPOSE) logs -f --tail=200 ofme-api

# --------------------------------------------------------------------- database
.PHONY: migrate
migrate: ## Apply Alembic migrations inside the API container
	$(COMPOSE) run --rm --no-deps ofme-api alembic upgrade head

.PHONY: migrate-local
migrate-local: ## Apply Alembic migrations from the local virtualenv
	cd $(BACKEND_DIR) && .venv/Scripts/python.exe -m alembic upgrade head 2>/dev/null || .venv/bin/python -m alembic upgrade head

.PHONY: revision
revision: ## Create a migration: make revision M="add table"
	@test -n "$(M)" || (echo "usage: make revision M='message'" && exit 1)
	cd $(BACKEND_DIR) && alembic revision --autogenerate -m "$(M)"

.PHONY: downgrade
downgrade: ## Roll back one migration
	cd $(BACKEND_DIR) && alembic downgrade -1

.PHONY: db-shell
db-shell: ## Open psql in the database container
	$(COMPOSE) exec postgres psql -U $${POSTGRES_USER:-ofme} -d $${POSTGRES_DB:-ofme}

.PHONY: db-dump
db-dump: ## Dump the database to backups/ofme-<timestamp>.sql.gz
	@mkdir -p backups
	$(COMPOSE) exec -T postgres pg_dump -U $${POSTGRES_USER:-ofme} -d $${POSTGRES_DB:-ofme} --clean --if-exists | gzip -9 > backups/ofme-$$(date -u +%Y%m%dT%H%M%SZ).sql.gz

# --------------------------------------------------------------------- backend
.PHONY: install
install: ## Create the backend virtualenv and install dev dependencies
	cd $(BACKEND_DIR) && python -m venv .venv && .venv/bin/python -m pip install --upgrade pip && .venv/bin/pip install -e ".[dev]"

.PHONY: lint
lint: ## Ruff lint + format check for the backend
	cd $(BACKEND_DIR) && ruff check app tests && ruff format --check app tests

.PHONY: fmt
fmt: ## Apply Ruff formatting and safe fixes
	cd $(BACKEND_DIR) && ruff check --fix app tests && ruff format app tests

.PHONY: typecheck
typecheck: ## mypy over the backend application
	cd $(BACKEND_DIR) && mypy app

.PHONY: test-db
test-db: ## Start a disposable PostgreSQL for the test suite
	-docker rm -f $(TEST_PG)
	docker run -d --name $(TEST_PG) \
		-e POSTGRES_USER=ofme -e POSTGRES_PASSWORD=ofme -e POSTGRES_DB=ofme_test \
		-p 55432:5432 postgres:16-alpine
	@until docker exec $(TEST_PG) pg_isready -U ofme -d ofme_test >/dev/null 2>&1; do sleep 1; done

.PHONY: test
test: ## Run the backend test suite against PostgreSQL
	cd $(BACKEND_DIR) && TEST_DATABASE_URL="$(TEST_DATABASE_URL)" python -m pytest tests -q

.PHONY: test-cov
test-cov: ## Run tests with coverage report
	cd $(BACKEND_DIR) && TEST_DATABASE_URL="$(TEST_DATABASE_URL)" python -m pytest tests \
		--cov=app --cov-report=term-missing --cov-report=xml:coverage.xml --cov-fail-under=70

.PHONY: openapi
openapi: ## Regenerate api/openapi.{yaml,json} from the application
	cd $(BACKEND_DIR) && python scripts/export_openapi.py
	cd $(BACKEND_DIR) && python scripts/export_openapi.py -o ../api/openapi.json

.PHONY: grpc
grpc: ## Regenerate Python gRPC stubs from proto/fleet.proto
	cd $(BACKEND_DIR) && python scripts/generate_grpc.py

# --------------------------------------------------------------------- frontend
.PHONY: fe-install
fe-install: ## Install frontend dependencies
	cd $(FRONTEND_DIR) && npm ci

.PHONY: fe-dev
fe-dev: ## Run the Vite dev server on :5173
	cd $(FRONTEND_DIR) && npm run dev

.PHONY: fe-build
fe-build: ## Type-check and build the SPA
	cd $(FRONTEND_DIR) && npm run build

.PHONY: fe-test
fe-test: ## Run Vitest
	cd $(FRONTEND_DIR) && npm run test

.PHONY: fe-lint
fe-lint: ## ESLint the SPA
	cd $(FRONTEND_DIR) && npm run lint

# --------------------------------------------------------------------- plugin
.PHONY: plugin-lint
plugin-lint: ## PHP syntax check of the OPNsense plugin (requires php)
	@find $(PLUGIN_DIR)/src -name '*.php' -print0 | xargs -0 -n1 php -l

.PHONY: plugin-package
plugin-package: ## Build the OPNsense plugin package in a FreeBSD ports tree
	@echo "Copy $(PLUGIN_DIR) into /usr/ports/net-mgmt/os-fleet-agent and run 'make package' there."

# --------------------------------------------------------------------- quality / load
.PHONY: load-smoke
load-smoke: ## Run the k6 smoke test against the local API
	k6 run -e BASE_URL=http://localhost:8000 tests/load/smoke.js

.PHONY: load-fleet
load-fleet: ## Run the k6 fleet read load test (200 VUs)
	k6 run -e BASE_URL=http://localhost:8000 -e VUS=200 -e DURATION=5m tests/load/fleet.js

# --------------------------------------------------------------------- test agent
# tests/agent/ is a minimal stand-in for the real os-fleet-agent plugin. It
# consumes a one-time enrollment token, so `make ztp-token` must run before
# `make agent-build` / `make agent-up`. The token is one-time and is never
# committed — see .env.example for the ENROLLMENT_TOKEN placeholder.

.PHONY: ztp-token
ztp-token: ## Mint a one-time enrollment token for the test agent
	@$(VENV_PY) $(BACKEND_DIR)/scripts/mint_ztp_token.py

.PHONY: agent-build
agent-build: ## Build the test agent image
	$(COMPOSE) --profile testing build ofme-test-agent

.PHONY: agent-up
agent-up: ## Start the test agent (requires ENROLLMENT_TOKEN in .env)
	$(COMPOSE) --profile testing up -d ofme-test-agent

.PHONY: agent-logs
agent-logs: ## Follow the test agent logs
	$(COMPOSE) --profile testing logs -f ofme-test-agent

.PHONY: agent-down
agent-down: ## Stop and remove the test agent container
	$(COMPOSE) rm -fs ofme-test-agent

.PHONY: helm-lint
helm-lint: ## Lint the Helm chart
	helm lint deploy/helm/ofme

.PHONY: helm-template
helm-template: ## Render the Helm chart to stdout
	helm template ofme deploy/helm/ofme --namespace ofme

.PHONY: k8s-dry-run
k8s-dry-run: ## Client-side validation of the raw manifests
	kubectl apply --dry-run=client -f deploy/k8s/

.PHONY: check
check: lint test fe-lint fe-test ## Everything CI runs

.PHONY: clean
clean: ## Remove local caches and build output
	rm -rf $(BACKEND_DIR)/.pytest_cache $(BACKEND_DIR)/.mypy_cache $(BACKEND_DIR)/.ruff_cache \
		$(BACKEND_DIR)/htmlcov $(BACKEND_DIR)/coverage.xml $(FRONTEND_DIR)/dist $(FRONTEND_DIR)/coverage
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
