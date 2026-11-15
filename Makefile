.PHONY: test lint data-check experiment readme check

test:
	python3 -m unittest discover -s tests

lint:
	ruff check . && ruff format --check .

data-check:
	python3 tools/fetch_data.py --verify

experiment:
	python3 experiment.py --out results/metrics.json

readme:
	python3 demo.py --readme README.md --out README.md

check:
	python3 -m snippetcheck
