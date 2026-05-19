# Demo Controller — Deployment Pipeline
#
# Idempotent. Re-running any target is safe.
# Requires: bash-compatible shell (Git Bash on Windows), gcloud CLI, active gcloud auth.
#
# Usage:
#   make help            # list every target
#   make test            # run unit tests
#   make infra           # create bucket + SA + role + IAM bindings
#   make deploy          # full deployment (depends on infra)
#   make verify          # hit /healthz on the deployed service
#   make status          # admin status dump
#   make logs            # tail Cloud Run logs

PROJECT      ?= pe-org-air
REGION       ?= us-east1
SA_NAME      ?= demo-controller-sa
SERVICE_NAME ?= demo-controller
ROLE_ID      ?= democtl_compute
BUCKET       ?= demo-controller-state-$(PROJECT)

SA_EMAIL    := $(SA_NAME)@$(PROJECT).iam.gserviceaccount.com
ADMIN_TOKEN := $(shell grep -E '^ADMIN_TOKEN=' .env 2>/dev/null | cut -d '=' -f 2-)

.DEFAULT_GOAL := help
.PHONY: help test enable-services bucket sa role iam infra deploy url verify status logs destroy

help: ## List available targets
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# ---- Local ----

test: ## Run the unit test suite
	pytest

# ---- GCP infrastructure (each target is idempotent) ----

enable-services: ## Enable required GCP APIs
	gcloud services enable \
		run.googleapis.com \
		cloudbuild.googleapis.com \
		compute.googleapis.com \
		storage.googleapis.com \
		iam.googleapis.com \
		artifactregistry.googleapis.com \
		--project=$(PROJECT)

bucket: ## Create the state bucket if absent
	@gcloud storage buckets describe gs://$(BUCKET) --project=$(PROJECT) >/dev/null 2>&1 \
		&& echo "  bucket exists: gs://$(BUCKET)" \
		|| gcloud storage buckets create gs://$(BUCKET) \
			--location=$(REGION) \
			--uniform-bucket-level-access \
			--project=$(PROJECT)

sa: ## Create the controller service account if absent
	@gcloud iam service-accounts describe $(SA_EMAIL) --project=$(PROJECT) >/dev/null 2>&1 \
		&& echo "  service account exists: $(SA_EMAIL)" \
		|| gcloud iam service-accounts create $(SA_NAME) \
			--display-name="Demo Controller for Portfolio" \
			--project=$(PROJECT)

role: ## Create the custom compute role if absent
	@gcloud iam roles describe $(ROLE_ID) --project=$(PROJECT) >/dev/null 2>&1 \
		&& echo "  custom role exists: $(ROLE_ID)" \
		|| gcloud iam roles create $(ROLE_ID) \
			--project=$(PROJECT) \
			--title="Demo Controller Compute" \
			--description="Start/stop/describe demo VMs" \
			--permissions="compute.instances.get,compute.instances.start,compute.instances.stop" \
			--stage=GA

iam: sa role bucket ## Bind roles to the SA (idempotent in gcloud)
	gcloud projects add-iam-policy-binding $(PROJECT) \
		--member="serviceAccount:$(SA_EMAIL)" \
		--role="projects/$(PROJECT)/roles/$(ROLE_ID)" \
		--condition=None \
		--quiet >/dev/null
	gcloud storage buckets add-iam-policy-binding gs://$(BUCKET) \
		--member="serviceAccount:$(SA_EMAIL)" \
		--role="roles/storage.objectAdmin" \
		--quiet >/dev/null
	@echo "  IAM bindings applied"

infra: enable-services bucket sa role iam ## Run every infra step end-to-end

# ---- Deploy ----

deploy: infra ## Build the container and roll out to Cloud Run
	@if [ -z "$(ADMIN_TOKEN)" ]; then \
		echo "ERROR: ADMIN_TOKEN not found in .env"; exit 1; \
	fi
	gcloud run deploy $(SERVICE_NAME) \
		--source . \
		--region=$(REGION) \
		--project=$(PROJECT) \
		--service-account=$(SA_EMAIL) \
		--allow-unauthenticated \
		--min-instances=0 \
		--max-instances=1 \
		--memory=256Mi \
		--cpu=1 \
		--timeout=120 \
		--set-env-vars="GCP_PROJECT_ID=$(PROJECT),STATE_BUCKET=$(BUCKET),ADMIN_TOKEN=$(ADMIN_TOKEN),DEFAULT_IDLE_MINUTES=10,ALLOWED_ORIGINS=*"
	@echo ""
	@echo "Deployed:"
	@$(MAKE) -s url

url: ## Print the deployed service URL
	@gcloud run services describe $(SERVICE_NAME) \
		--region=$(REGION) --project=$(PROJECT) \
		--format="value(status.url)"

# ---- Verify ----

verify: ## Hit /healthz on the deployed service
	@URL=$$(gcloud run services describe $(SERVICE_NAME) --region=$(REGION) --project=$(PROJECT) --format="value(status.url)"); \
		echo "GET $$URL/healthz"; \
		curl -sf "$$URL/healthz" && echo "  ok"

status: ## Admin status dump from the deployed service
	@URL=$$(gcloud run services describe $(SERVICE_NAME) --region=$(REGION) --project=$(PROJECT) --format="value(status.url)"); \
		curl -s -H "X-Admin-Token: $(ADMIN_TOKEN)" "$$URL/admin/status" | python -m json.tool

logs: ## Tail Cloud Run logs (Ctrl-C to exit)
	gcloud run services logs read $(SERVICE_NAME) --region=$(REGION) --project=$(PROJECT) --limit=100

# ---- Teardown ----

destroy: ## Delete the Cloud Run service (leaves bucket/SA/role intact)
	gcloud run services delete $(SERVICE_NAME) \
		--region=$(REGION) --project=$(PROJECT) --quiet