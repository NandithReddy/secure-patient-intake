.PHONY: help install demo eval test api web train verify clean

PY := .venv/bin/python

help:
	@echo "install   create venv, install deid + service"
	@echo "demo      redact one synthetic note, print what leaked"
	@echo "eval      score the rule baseline -> results/rules.json"
	@echo "test      run the test suite"
	@echo "api       run FastAPI on :8000"
	@echo "web       run Vite on :5173 (proxies /api to :8000)"
	@echo "train     fine-tune the local token classifier"
	@echo "verify    check the audit-log hash chain"

install:
	python3.12 -m venv .venv
	$(PY) -m pip install -q --upgrade pip
	$(PY) -m pip install -e '.[dev]'
	cd frontend && npm install

demo:
	$(PY) -m deid.cli demo

eval:
	$(PY) -m deid.cli eval --redactor rules --json-out results/rules.json

test:
	$(PY) -m pytest -q

api:
	.venv/bin/uvicorn service.main:app --reload --port 8000

web:
	cd frontend && npm run dev

train:
	$(PY) -m deid.train --out models/deid-deberta --epochs 4

verify:
	$(PY) -m deid.cli verify-audit --path data/audit.jsonl

clean:
	rm -rf .pytest_cache **/__pycache__ frontend/dist
