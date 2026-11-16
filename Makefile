.PHONY: test lint data-check experiment holdout readme check

test:
	python3 -m unittest discover -s tests
	python3 -m unittest discover -s tests/acceptance

lint:
	ruff check . && ruff format --check .

data-check:
	python3 tools/fetch_data.py --verify
	python3 tools/fetch_holdout.py --verify

experiment:
	python3 experiment.py --out results/metrics.json

holdout:
	python3 -m snippetspec.holdout --out results/holdout.json

readme:
	python3 demo.py --readme README.md --out README.md

check:
	python3 -m snippetspec
