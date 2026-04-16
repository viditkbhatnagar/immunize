.PHONY: install test lint format build clean

install:
	pip install -e ".[dev]"

test:
	pytest

lint:
	ruff check .

format:
	ruff format .

build:
	rm -rf dist/ build/ *.egg-info
	python -m build

clean:
	rm -rf dist/ build/ *.egg-info .pytest_cache .ruff_cache .immunize
