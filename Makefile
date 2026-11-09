SCENARIO ?= scenarios/public_01_dev.yaml
NAME ?= $(basename $(notdir $(SCENARIO)))

baseline:
	python -m sim baseline --scenario $(SCENARIO) --run-dir runs/base_$(NAME)
serve:
	python -m sim serve --scenario $(SCENARIO) --run-dir runs/mine_$(NAME) --force
grade:
	mkdir -p reports && python -m sim grade --run runs/mine_$(NAME) --baseline runs/base_$(NAME) --out reports/$(NAME).md
test:
	python -m pytest -q tests
# ---- controller
run:        ## serve SCENARIO, run the controller against it, grade vs baseline
	scripts/run_scenario.sh $(SCENARIO)
crash:      ## SIGKILL/restart test on public_02
	.venv/bin/python scripts/crash_test.py --scenario scenarios/public_02_incidents.yaml --kills 3
eval:       ## hidden-like robustness eval (6 re-drawn truths)
	.venv/bin/python evals/make_variants.py --n 6 && .venv/bin/python evals/run_evals.py evals/scenarios/*.yaml
load:       ## public_03 load test + report
	scripts/run_scenario.sh scenarios/public_03_load.yaml && .venv/bin/python scripts/load_report.py state/public_03_load logs/ctl_public_03_load.time
