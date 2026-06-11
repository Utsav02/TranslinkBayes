# TransLinkBayes — common entry points.
# Always uses venv/bin/python3 directly; `source activate` does not persist
# across make's per-line subshells (same convention as CLAUDE.md).

PY      := venv/bin/python3
SINCE   ?= 2026-05-09# quality baseline cutoff — see CLAUDE.md "Data quality baseline"
ROUTE   ?= 6641
DIR     ?= 0

.PHONY: help venv test process quality export export-all refresh refresh-render \
        dashboard render collect-status

help:
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-16s %s\n", $$1, $$2}'

venv: ## create venv and install pinned requirements
	python3 -m venv venv
	$(PY) -m pip install -r requirements.txt

test: ## run smoke tests (pure-logic, no DB needed)
	$(PY) -m pytest tests/ -q

process: ## rebuild processed_stops since $(SINCE)
	$(PY) pipeline/process_delays.py --since $(SINCE)

quality: ## run data quality report since $(SINCE) (exits 1 on hard failure)
	$(PY) pipeline/quality_report.py --since $(SINCE)

export: ## export one route ($(ROUTE) dir $(DIR)) since $(SINCE)
	$(PY) pipeline/export_route.py --route $(ROUTE) --direction $(DIR) --since $(SINCE)

export-all: ## export all routes since $(SINCE)
	$(PY) pipeline/export_route.py --route all --since $(SINCE)

refresh: ## full refresh: process + quality + exports (data only)
	bash pipeline/refresh_analysis.sh

refresh-render: ## full refresh, then re-render the Rmds
	bash pipeline/refresh_analysis.sh --rerender

dashboard: ## launch the Streamlit dashboard
	$(PY) -m streamlit run pipeline/dashboard/app.py

render: ## render all three Rmds (uses renv via .Rprofile)
	cd analysis && Rscript -e "rmarkdown::render('brms_analysis.Rmd')"
	cd analysis && Rscript -e "rmarkdown::render('multi_route_analysis.Rmd')"
	cd analysis && Rscript -e "rmarkdown::render('viz_showcase.Rmd')"

collect-status: ## check the launchd collection jobs are loaded
	launchctl list | grep translink || echo "no translink launchd jobs loaded"
