# Maintainer-only targets. This file lives in tooling/, which is gitignored, so
# it never reaches a candidate. Run from the repo ROOT:
#
#   make -f tooling/Makefile generate   # rebuild seed data + ERP fixtures from the SSOT
#   make -f tooling/Makefile bundle     # optional: tooling-free copy in dist/ (for a zip)
#
# `generate` is the only one you normally need: after editing ground_truth.py,
# run it, then commit the regenerated data/ and erp/*.json and push.

ERPVENV := erp/.venv

.PHONY: generate bundle test

generate: ## Regenerate seed data + ERP fixtures from the SSOT (tooling/ground_truth.py)
	@test -d $(ERPVENV) || python3 -m venv $(ERPVENV)
	@$(ERPVENV)/bin/pip install -q -r erp/requirements.txt
	$(ERPVENV)/bin/python tooling/generate.py

test: ## Run the SSOT consistency checks
	@python3 tooling/test_consistency.py

bundle: ## Build a tooling-free copy in dist/ (e.g. to hand off as a zip, not via git)
	@rm -rf dist && mkdir -p dist
	@rsync -a \
		--exclude='tooling' \
		--exclude='dist' \
		--exclude='.git' \
		--exclude='**/.venv' \
		--exclude='**/node_modules' \
		--exclude='**/__pycache__' \
		--exclude='*.sqlite' \
		./ dist/
	@echo "tooling-free copy written to dist/"
