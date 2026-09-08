# No-Docker fallback orchestration. Each run target bakes its env inline, so
# you never have to export anything by hand.
#
#   make erp     # terminal 1: fake ERP on :9000 (SQLite path needs no DB server)
#   make py      # terminal 2: run the Python app   (or: make node)

DATA_DIR ?= ./data
ERP_PORT ?= 9000

PYVENV  := app/python/.venv
ERPVENV := erp/.venv

.PHONY: help erp py node setup-erp setup-py setup-node clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n",$$1,$$2}'

setup-erp: ## Create the ERP venv and install fastapi/uvicorn
	@test -d $(ERPVENV) || python3 -m venv $(ERPVENV)
	@$(ERPVENV)/bin/pip install -q -r erp/requirements.txt

erp: setup-erp ## Run the fake ERP locally on $(ERP_PORT)
	$(ERPVENV)/bin/uvicorn app:app --app-dir erp --port $(ERP_PORT)

setup-py: ## Create the Python app venv and install deps
	@test -d $(PYVENV) || python3 -m venv $(PYVENV)
	@$(PYVENV)/bin/pip install -q -r app/python/requirements.txt

py: setup-py ## Run the Python app (SQLite + local ERP)
	DATABASE_URL="sqlite:///./app.sqlite" \
	ERP_BASE_URL="http://localhost:$(ERP_PORT)" \
	DATA_DIR="$(DATA_DIR)" \
	$(PYVENV)/bin/python app/python/main.py

setup-node: ## Install the Node app deps
	@cd app/node && npm install --silent

node: setup-node ## Run the Node app (SQLite + local ERP)
	DATABASE_URL="sqlite:///./app.sqlite" \
	ERP_BASE_URL="http://localhost:$(ERP_PORT)" \
	DATA_DIR="$(DATA_DIR)" \
	node app/node/index.js

clean: ## Remove venvs, node_modules, sqlite db, caches
	rm -rf $(ERPVENV) $(PYVENV) app/node/node_modules app.sqlite dist
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
