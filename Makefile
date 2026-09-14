.PHONY: test dev
install:
	python -m pip install -e '.[dev]'
test:
	pytest -q
dev:
	uvicorn foundry.main:app --app-dir src --reload
