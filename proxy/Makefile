# Multi-demo proxy: one Cloud Run service per demo.
# Same Caddy image + Dockerfile, different UPSTREAM env var per service.

PROJECT ?= pe-org-air
REGION  ?= us-central1

# Demo-specific path suffix appended after each proxy URL root
CS5_PATH      := /comparative/
VICINITY_PATH := /
BUFFETT_PATH  := /index.html

# Path to the controller's demos.yaml (relative to this Makefile)
CONTROLLER_YAML := ../demos.yaml

.DEFAULT_GOAL := help

.PHONY: help deploy-all deploy-cs5 deploy-vicinity deploy-buffett \
        sync-yaml urls deploy-everything destroy-all

help: ## List targets
	@printf "\n\033[1mDemo Proxies (one per demo)\033[0m\n"
	@printf "  Project: \033[36m%s\033[0m\n" "$(PROJECT)"
	@printf "  Region:  \033[36m%s\033[0m\n\n" "$(REGION)"
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

deploy-cs5: ## Deploy cs5 proxy
	gcloud run deploy cs5-proxy --source . \
		--region=$(REGION) --project=$(PROJECT) \
		--allow-unauthenticated \
		--min-instances=0 --max-instances=1 \
		--memory=128Mi --cpu=1 --timeout=60 --port=8080 \
		--set-env-vars="UPSTREAM=http://34.26.144.212:8501"

deploy-vicinity: ## Deploy vicinity proxy
	gcloud run deploy vicinity-proxy --source . \
		--region=$(REGION) --project=$(PROJECT) \
		--allow-unauthenticated \
		--min-instances=0 --max-instances=1 \
		--memory=128Mi --cpu=1 --timeout=60 --port=8080 \
		--set-env-vars="UPSTREAM=http://34.74.93.251:80"

deploy-buffett: ## Deploy buffett proxy
	gcloud run deploy buffett-proxy --source . \
		--region=$(REGION) --project=$(PROJECT) \
		--allow-unauthenticated \
		--min-instances=0 --max-instances=1 \
		--memory=128Mi --cpu=1 --timeout=60 --port=8080 \
		--set-env-vars="UPSTREAM=http://35.231.218.39:8000"

sync-yaml: ## Patch ../demos.yaml with current proxy URLs
	@CS5_URL=$$(gcloud run services describe cs5-proxy           --region=$(REGION) --project=$(PROJECT) --format='value(status.url)' 2>/dev/null); \
	VICINITY_URL=$$(gcloud run services describe vicinity-proxy  --region=$(REGION) --project=$(PROJECT) --format='value(status.url)' 2>/dev/null); \
	BUFFETT_URL=$$(gcloud run services describe buffett-proxy    --region=$(REGION) --project=$(PROJECT) --format='value(status.url)' 2>/dev/null); \
	if [ -z "$$CS5_URL" ] || [ -z "$$VICINITY_URL" ] || [ -z "$$BUFFETT_URL" ]; then \
	    echo "ERROR: one or more proxy URLs missing - run 'make deploy-all' first"; \
	    exit 1; \
	fi; \
	echo "Syncing $(CONTROLLER_YAML):"; \
	echo "  cs5:      $$CS5_URL$(CS5_PATH)"; \
	echo "  vicinity: $$VICINITY_URL$(VICINITY_PATH)"; \
	echo "  buffett:  $$BUFFETT_URL$(BUFFETT_PATH)"; \
	sed -i.bak \
	    -e "/^  cs5:/,/^  [a-z]/ s|appUrl: .*|appUrl: $$CS5_URL$(CS5_PATH)|" \
	    -e "/^  vicinity:/,/^  [a-z]/ s|appUrl: .*|appUrl: $$VICINITY_URL$(VICINITY_PATH)|" \
	    -e "/^  buffett:/,/^  [a-z]/ s|appUrl: .*|appUrl: $$BUFFETT_URL$(BUFFETT_PATH)|" \
	    $(CONTROLLER_YAML); \
	rm -f $(CONTROLLER_YAML).bak; \
	echo "Done. Run 'cd .. && make deploy' to ship the new yaml."

urls: ## Print all three proxy URLs
	@echo "cs5:      $$(gcloud run services describe cs5-proxy      --region=$(REGION) --project=$(PROJECT) --format='value(status.url)' 2>/dev/null)"
	@echo "vicinity: $$(gcloud run services describe vicinity-proxy --region=$(REGION) --project=$(PROJECT) --format='value(status.url)' 2>/dev/null)"
	@echo "buffett:  $$(gcloud run services describe buffett-proxy  --region=$(REGION) --project=$(PROJECT) --format='value(status.url)' 2>/dev/null)"

deploy-all: deploy-cs5 deploy-vicinity deploy-buffett sync-yaml urls ## Deploy all three + sync yaml

deploy-everything: deploy-all ## Deploy proxies, sync yaml, and redeploy controller
	cd .. && $(MAKE) deploy

destroy-all: ## Delete all three proxy services
	-gcloud run services delete cs5-proxy      --region=$(REGION) --project=$(PROJECT) --quiet
	-gcloud run services delete vicinity-proxy --region=$(REGION) --project=$(PROJECT) --quiet
	-gcloud run services delete buffett-proxy  --region=$(REGION) --project=$(PROJECT) --quiet