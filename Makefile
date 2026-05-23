# Demo Controller — CD Pipeline (Cloud Build edition)
#
# Build via Cloud Build, deploy to Cloud Run. Same workflow on a developer
# laptop and in CI. No local Docker required.
#
# Quick start:
#   make help                  # list every target with descriptions
#   make ci                    # full pipeline: validate + infra + deploy + verify
#   make deploy-only           # skip validate + infra, just redeploy
#   make rollback              # revert to previous Cloud Run revision
#
# In CI (e.g., GitHub Actions):
#   export GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa-key.json
#   export ADMIN_TOKEN=<from secrets>
#   make ci

# ---------------------------------------------------------------------------
# Configuration (override via env or `make VAR=value`)
# ---------------------------------------------------------------------------

PROJECT      ?= pe-org-air
REGION       ?= us-central1
SA_NAME      ?= demo-controller-sa
SERVICE_NAME ?= demo-controller
ROLE_ID      ?= democtl_compute
BUCKET       ?= demo-controller-state-$(PROJECT)

# Derived
SA_EMAIL := $(SA_NAME)@$(PROJECT).iam.gserviceaccount.com

# Version (for display + traceability; Cloud Build manages the actual image tag)
GIT_SHA   := $(shell git rev-parse --short HEAD 2>/dev/null || echo "nogit")
GIT_DIRTY := $(shell git diff --quiet 2>/dev/null || echo "-dirty")
VERSION   ?= $(GIT_SHA)$(GIT_DIRTY)

# Runtime secret sourced from env first, then .env file
ADMIN_TOKEN := $(if $(ADMIN_TOKEN),$(ADMIN_TOKEN),$(shell grep -E '^ADMIN_TOKEN=' .env 2>/dev/null | cut -d '=' -f 2-))

.DEFAULT_GOAL := help

.PHONY: help version \
        run-uvicorn \
        test lint validate \
        enable-services bucket sa role iam infra \
        deploy \
        verify health smoke-test \
        url status logs revisions \
        rollback destroy teardown \
        ci deploy-only

# ---------------------------------------------------------------------------
# Help & introspection
# ---------------------------------------------------------------------------

help: ## List available targets with descriptions
	@printf "\n\033[1mDemo Controller CD Pipeline\033[0m\n"
	@printf "  Project:  \033[36m%s\033[0m\n" "$(PROJECT)"
	@printf "  Region:   \033[36m%s\033[0m\n" "$(REGION)"
	@printf "  Service:  \033[36m%s\033[0m\n" "$(SERVICE_NAME)"
	@printf "  Version:  \033[36m%s\033[0m\n\n" "$(VERSION)"
	@awk 'BEGIN {FS = ":.*?## "} \
		/^# -+$$/ {next} \
		/^# [A-Z]/ {gsub(/^# /, ""); printf "\n\033[1m%s\033[0m\n", $$0; next} \
		/^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}' \
		$(MAKEFILE_LIST)

version: ## Print the version string for traceability
	@echo "$(VERSION)"

# ---------------------------------------------------------------------------
# Local development
# ---------------------------------------------------------------------------

run-uvicorn: ## Run uvicorn directly without Docker (fastest dev loop)
	uvicorn app.main:app --reload --port 8080

# ---------------------------------------------------------------------------
# Validate
# ---------------------------------------------------------------------------

test: ## Run the pytest suite
	pytest

lint: ## Run ruff if installed (skips silently otherwise)
	@command -v ruff >/dev/null 2>&1 \
		&& ruff check app tests \
		|| echo "  ruff not installed, skipping"

validate: test lint ## All pre-deploy code checks

# ---------------------------------------------------------------------------
# Infrastructure (idempotent, handles soft-deleted resources)
# ---------------------------------------------------------------------------

enable-services: ## Enable required GCP APIs
	gcloud services enable \
		run.googleapis.com cloudbuild.googleapis.com compute.googleapis.com \
		storage.googleapis.com iam.googleapis.com artifactregistry.googleapis.com \
		--project=$(PROJECT)

bucket: ## Create the state bucket if absent
	@gcloud storage buckets describe gs://$(BUCKET) --project=$(PROJECT) >/dev/null 2>&1 \
		&& echo "  bucket exists: gs://$(BUCKET)" \
		|| gcloud storage buckets create gs://$(BUCKET) \
			--location=$(REGION) --uniform-bucket-level-access --project=$(PROJECT)

sa: ## Create or undelete the service account
	@if gcloud iam service-accounts describe $(SA_EMAIL) --project=$(PROJECT) >/dev/null 2>&1; then \
		echo "  service account exists: $(SA_EMAIL)"; \
	else \
		DELETED_ID=$$(gcloud iam service-accounts list --show-deleted \
			--filter="email:$(SA_EMAIL)" --project=$(PROJECT) \
			--format="value(uniqueId)" 2>/dev/null); \
		if [ -n "$$DELETED_ID" ]; then \
			echo "  SA soft-deleted, undeleting"; \
			gcloud iam service-accounts undelete $$DELETED_ID --project=$(PROJECT); \
		else \
			gcloud iam service-accounts create $(SA_NAME) \
				--display-name="Demo Controller for Portfolio" --project=$(PROJECT); \
		fi; \
	fi

role: ## Create or undelete the custom compute role
	@OUTPUT=$$(gcloud iam roles describe $(ROLE_ID) --project=$(PROJECT) 2>&1); \
	if echo "$$OUTPUT" | grep -q "deleted: true"; then \
		echo "  role soft-deleted, undeleting"; \
		gcloud iam roles undelete $(ROLE_ID) --project=$(PROJECT); \
	elif echo "$$OUTPUT" | grep -q "^name:"; then \
		echo "  role exists: $(ROLE_ID)"; \
	else \
		gcloud iam roles create $(ROLE_ID) --project=$(PROJECT) \
			--title="Demo Controller Compute" \
			--description="Start/stop/describe demo VMs" \
			--permissions="compute.instances.get,compute.instances.start,compute.instances.stop" \
			--stage=GA; \
	fi

iam: sa role bucket ## Bind roles to the SA
	gcloud projects add-iam-policy-binding $(PROJECT) \
		--member="serviceAccount:$(SA_EMAIL)" \
		--role="projects/$(PROJECT)/roles/$(ROLE_ID)" \
		--condition=None --quiet >/dev/null
	gcloud storage buckets add-iam-policy-binding gs://$(BUCKET) \
		--member="serviceAccount:$(SA_EMAIL)" \
		--role="roles/storage.objectAdmin" --quiet >/dev/null
	@echo "  IAM bindings applied"

infra: enable-services iam ## Run every infrastructure step

# ---------------------------------------------------------------------------
# Deploy (Cloud Build builds the image, Cloud Run serves it)
# ---------------------------------------------------------------------------

deploy: ## Build via Cloud Build and deploy to Cloud Run in one step
	@if [ -z "$(ADMIN_TOKEN)" ]; then echo "ERROR: ADMIN_TOKEN missing in .env or env"; exit 1; fi
	gcloud run deploy $(SERVICE_NAME) \
		--source . \
		--region=$(REGION) --project=$(PROJECT) \
		--service-account=$(SA_EMAIL) \
		--allow-unauthenticated \
		--min-instances=0 --max-instances=1 \
		--memory=256Mi --cpu=1 --timeout=120 --port=8080 \
		--set-env-vars="^@^GCP_PROJECT_ID=$(PROJECT)@STATE_BUCKET=$(BUCKET)@ADMIN_TOKEN=$(ADMIN_TOKEN)@DEFAULT_IDLE_MINUTES=10@ALLOWED_ORIGINS=https://portfolio.anirudhraj694.workers.dev,http://localhost:5173"
	@echo ""
	@echo "Deployed $(VERSION) to:"
	@$(MAKE) -s url

# ---------------------------------------------------------------------------
# Verify (retry-aware for first-deploy URL propagation)
# ---------------------------------------------------------------------------

health: ## Hit /health with retry (up to 120s)
	@URL=$$($(MAKE) -s url); \
		echo "GET $$URL/health  (retrying up to 120s)"; \
		for i in $$(seq 1 24); do \
			if curl -sf "$$URL/health" >/dev/null 2>&1; then \
				echo "  ok (attempt $$i)"; exit 0; \
			fi; \
			printf "."; sleep 5; \
		done; \
		echo ""; echo "  FAILED after 120s"; exit 1

smoke-test: ## Hit every public endpoint and confirm 2xx
	@URL=$$($(MAKE) -s url); \
		echo "Smoke test against $$URL"; \
		curl -sf "$$URL/health" >/dev/null && echo "  /health           ok" || { echo "  /health FAILED"; exit 1; }; \
		curl -sf "$$URL/demos/cs5/status" >/dev/null && echo "  /demos/cs5        ok" || { echo "  /demos/cs5 FAILED"; exit 1; }; \
		curl -sf "$$URL/demos/vicinity/status" >/dev/null && echo "  /demos/vicinity   ok" || { echo "  /demos/vicinity FAILED"; exit 1; }; \
		echo "All smoke tests passed."

verify: health smoke-test ## Full post-deploy verification

# ---------------------------------------------------------------------------
# Observability
# ---------------------------------------------------------------------------

url: ## Print the deployed service URL
	@gcloud run services describe $(SERVICE_NAME) \
		--region=$(REGION) --project=$(PROJECT) \
		--format="value(status.url)"

status: ## Admin status dump from the deployed service
	@URL=$$($(MAKE) -s url); \
		curl -s -H "X-Admin-Token: $(ADMIN_TOKEN)" "$$URL/admin/status" | python -m json.tool

logs: ## Show last 100 Cloud Run log entries
	gcloud run services logs read $(SERVICE_NAME) --region=$(REGION) --project=$(PROJECT) --limit=100

revisions: ## List recent revisions (useful before rollback)
	@gcloud run revisions list --service=$(SERVICE_NAME) \
		--region=$(REGION) --project=$(PROJECT) \
		--format="table(metadata.name,status.conditions[0].status,metadata.creationTimestamp)" \
		--limit=10

# ---------------------------------------------------------------------------
# Rollback / Cleanup
# ---------------------------------------------------------------------------

rollback: ## Shift 100% traffic to the previous revision
	@PREV=$$(gcloud run revisions list --service=$(SERVICE_NAME) \
		--region=$(REGION) --project=$(PROJECT) \
		--format="value(metadata.name)" --limit=2 | tail -n 1); \
	if [ -z "$$PREV" ]; then echo "No previous revision found"; exit 1; fi; \
	echo "Rolling back to revision: $$PREV"; \
	gcloud run services update-traffic $(SERVICE_NAME) \
		--region=$(REGION) --project=$(PROJECT) \
		--to-revisions=$$PREV=100

destroy: ## Delete the Cloud Run service only (preserves SA, role, bucket)
	gcloud run services delete $(SERVICE_NAME) \
		--region=$(REGION) --project=$(PROJECT) --quiet

teardown: ## Delete EVERY resource created by `make infra` and `make deploy`
	@echo ""
	@echo "About to DELETE:"
	@echo "  1. Cloud Run service:    $(SERVICE_NAME)"
	@echo "  2. Artifact Registry:    cloud-run-source-deploy (all images)"
	@echo "  3. Project IAM binding"
	@echo "  4. Bucket and contents:  gs://$(BUCKET)"
	@echo "  5. Custom role:          $(ROLE_ID)"
	@echo "  6. Service account:      $(SA_EMAIL)"
	@echo ""
	@echo "NOT touched: the VMs cs5-prod-vm-v2 and vicinity-prod-vm."
	@echo "Press Ctrl-C in 5 seconds to abort..."
	@sleep 5
	-gcloud run services delete $(SERVICE_NAME) --region=$(REGION) --project=$(PROJECT) --quiet
	-gcloud artifacts repositories delete cloud-run-source-deploy --location=$(REGION) --project=$(PROJECT) --quiet
	-gcloud projects remove-iam-policy-binding $(PROJECT) \
		--member="serviceAccount:$(SA_EMAIL)" \
		--role="projects/$(PROJECT)/roles/$(ROLE_ID)" --quiet 2>/dev/null
	-gcloud storage rm --recursive gs://$(BUCKET) --project=$(PROJECT) --quiet 2>/dev/null
	-gcloud storage buckets delete gs://$(BUCKET) --project=$(PROJECT) --quiet
	-gcloud iam roles delete $(ROLE_ID) --project=$(PROJECT) --quiet
	-gcloud iam service-accounts delete $(SA_EMAIL) --project=$(PROJECT) --quiet
	@echo "Teardown complete."

# ---------------------------------------------------------------------------
# Pipelines
# ---------------------------------------------------------------------------

ci: validate infra deploy verify ## Full CD pipeline: validate + infra + deploy + verify

deploy-only: deploy verify ## Skip validate + infra: just redeploy + verify